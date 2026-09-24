"""Single-process, restartable TOS import jobs with durable stage checkpoints."""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_user_settings
from app.config import settings
from app.errors import MissingConfigurationError, ServiceError
from app.models.database import async_session_maker, get_session
from app.models.models import ImportTask, MediaFile, MediaTag
from app.models.schemas import ApiResponse, ImportStartRequest, ImportTaskDetail
from app.services.embedding_service import embedding_service
from app.services.annotation_job_service import (
    TASK_SNAPSHOT_FIELDS, annotation_job_service, task_progress,
)
from app.services.annotation_cleanup_service import AnnotationCleanupService
from app.services.milvus_service import milvus_service
from app.services.tag_service import tag_service
from app.services.tos_service import borrow_tos
from app.utils.logger import logger


router = APIRouter(prefix="/import", tags=["数据导入"])
_tasks: dict[str, asyncio.Task] = {}
_media_locks: dict[str, list] = {}
_limiter: Optional[asyncio.Semaphore] = None
_registry_lock: Optional[asyncio.Lock] = None
_stopping = False
_ACTIVE = ("pending", "running")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_error(exc: BaseException, service="application") -> dict:
    if isinstance(exc, ServiceError):
        return exc.to_dict()
    category = "timeout" if isinstance(exc, TimeoutError) else "unavailable"
    return ServiceError(service, category, retryable=True).to_dict()


def _error_text(error: dict) -> str:
    return json.dumps(error, ensure_ascii=True)


def _public_error(value: Optional[str]) -> Optional[str]:
    """Do not expose legacy free-text errors stored by an older deployment."""
    if not value:
        return None
    try:
        data = json.loads(value)
        return _error_text(ServiceError(
            data["service"], data["category"], request_id=data.get("request_id"),
            retryable=data.get("retryable") is True,
        ).to_dict())
    except (ValueError, TypeError, KeyError):
        return _error_text(ServiceError("application", "unavailable").to_dict())


async def _update_active(user_id: str, task_id: str, **values) -> bool:
    # Conditional SQL prevents a late completion/progress write undoing cancel.
    async with async_session_maker() as session:
        result = await session.execute(
            update(ImportTask)
            .where(
                ImportTask.user_id == user_id,
                ImportTask.task_id == task_id,
                ImportTask.status.in_(_ACTIVE),
            )
            .values(**values)
        )
        await session.commit()
        return bool(result.rowcount)


async def _checkpoint(user_id: str, task_id: str):
    # Short sessions avoid MySQL REPEATABLE READ hiding a concurrent cancel.
    async with async_session_maker() as session:
        status = await session.scalar(
            select(ImportTask.status).where(
                ImportTask.user_id == user_id,
                ImportTask.task_id == task_id,
            )
        )
    if status not in _ACTIVE:
        raise asyncio.CancelledError


async def _fail_remaining(user_id: str, task_id: str, error: dict):
    async with async_session_maker() as session:
        task = await session.scalar(select(ImportTask).where(
            ImportTask.user_id == user_id,
            ImportTask.task_id == task_id,
        ))
        if task is None or task.status not in _ACTIVE:
            return
        total = task.total_files or 0
        processed = min(max(task.processed_files or 0, 0), total)
        remaining = total - processed
        failed = min(total, max(task.failed_files or 0, 0) + remaining)
    await _update_active(
        user_id, task_id, status="failed",
        processed_files=total, failed_files=failed,
        error_message=_error_text(error), completed_at=_now(),
    )


@asynccontextmanager
async def _media_lock(user_id: str, tos_url: str):
    lock_key = f"{user_id}\0{tos_url}"
    entry = _media_locks.setdefault(lock_key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if not entry[1]:
            _media_locks.pop(lock_key, None)


async def _set_media(user_id: str, media_id: str, **values):
    async with async_session_maker() as session:
        await session.execute(update(MediaFile).where(
            MediaFile.id == media_id, MediaFile.user_id == user_id,
        ).values(**values))
        await session.commit()


def _vector_done(media: MediaFile) -> bool:
    space = settings.vector_space
    return (
        media.vector_status == "done"
        and media.vector_model == space.model
        and media.vector_dimension == space.dimension
        and media.vector_instruction_version == space.corpus_instruction_version
        and media.vector_collection == space.collection
    )


async def _replace_auto_tags(
    user_id: str, media_id: str, tags: list, tag_mode: str,
):
    unique = {}
    for tag in tags:
        key = (tag["category"], tag["tag_name"])
        if key not in unique or tag["confidence"] > unique[key]["confidence"]:
            unique[key] = tag
    async with async_session_maker() as session:
        manual = set((await session.execute(
            select(MediaTag.source, MediaTag.category, MediaTag.tag_name).where(
                MediaTag.media_id == media_id, MediaTag.user_id == user_id,
                MediaTag.is_manual == 1,
            )
        )).all())
        await session.execute(delete(MediaTag).where(
            MediaTag.media_id == media_id, MediaTag.user_id == user_id,
            MediaTag.is_manual == 0,
        ))
        for key, tag in unique.items():
            if (tag_mode, *key) not in manual:
                session.add(MediaTag(
                    user_id=user_id, media_id=media_id, source=tag_mode,
                    is_manual=0, **tag,
                ))
        await session.execute(update(MediaFile).where(
            MediaFile.id == media_id, MediaFile.user_id == user_id,
        ).values(tag_status="done"))
        await session.commit()


async def _process_file(user_id, task_id, info, tos, api_key, embedding_model,
                        embedding_dimension, tag_model, generate_vectors, generate_tags,
                        tag_mode, custom_tag_prompt, user_settings):
    async with _media_lock(user_id, info["tos_url"]):
        await _checkpoint(user_id, task_id)
        async with async_session_maker() as session:
            media = await session.scalar(select(MediaFile).where(
                MediaFile.user_id == user_id, MediaFile.tos_url == info["tos_url"],
            ))
            if media is None:
                media = MediaFile(
                    user_id=user_id,
                    **{key: info[key] for key in ("tos_url", "file_name", "file_size", "file_type")},
                    vector_status="pending" if generate_vectors else "skipped",
                    tag_status="pending" if generate_tags else "skipped",
                )
                session.add(media)
                await session.commit()
                await session.refresh(media)
            else:
                media.file_name = info["file_name"]
                media.file_size = info["file_size"]
                media.file_type = info["file_type"]
                await session.commit()
            media_id = media.id
            need_vector = generate_vectors and not _vector_done(media)
            # Every tag-enabled import must honor this task's mode and prompt snapshot.
            need_tags = generate_tags

        error = None
        if need_vector:
            await _checkpoint(user_id, task_id)
            await _set_media(user_id, media_id, vector_status="processing")
            try:
                await _checkpoint(user_id, task_id)
                await milvus_service.ensure_collection()
                await _checkpoint(user_id, task_id)
                signed_url = await tos.get_file_url(info["tos_url"])
                await _checkpoint(user_id, task_id)
                vector = await embedding_service.embed_media(
                    info["tos_url"], signed_url, model=embedding_model,
                    dimension=embedding_dimension, api_key=api_key,
                )
                await _checkpoint(user_id, task_id)
                vector_id = await milvus_service.upsert(
                    user_id=user_id, media_id=media_id, tos_url=info["tos_url"],
                    file_type=info["file_type"], embedding=vector,
                )
                await _checkpoint(user_id, task_id)
                space = settings.vector_space
                await _set_media(
                    user_id, media_id, vector_status="done", vector_id=vector_id,
                    vector_model=space.model, vector_dimension=space.dimension,
                    vector_instruction_version=space.corpus_instruction_version,
                    vector_collection=space.collection,
                )
            except asyncio.CancelledError:
                await _set_media(user_id, media_id, vector_status="failed")
                raise
            except Exception as exc:
                await _set_media(user_id, media_id, vector_status="failed")
                error = _safe_error(exc)
                logger.warning("Import vector stage failed: %s", error)

        if need_tags:
            await _checkpoint(user_id, task_id)
            await _set_media(user_id, media_id, tag_status="processing")
            try:
                await _checkpoint(user_id, task_id)
                signed_url = await tos.get_file_url(info["tos_url"])
                await _checkpoint(user_id, task_id)
                tags = await tag_service.generate_tags(
                    info["tos_url"], signed_url, model=tag_model, api_key=api_key,
                    tag_mode=tag_mode, custom_prompt=custom_tag_prompt,
                )
                await _checkpoint(user_id, task_id)
                await _replace_auto_tags(user_id, media_id, tags, tag_mode)
            except asyncio.CancelledError:
                await _set_media(user_id, media_id, tag_status="failed")
                raise
            except Exception as exc:
                await _set_media(user_id, media_id, tag_status="failed")
                error = _safe_error(exc)
                logger.warning("Import tag stage failed: %s", error)
        await _checkpoint(user_id, task_id)
        try:
            await annotation_job_service.annotate_import(
                user_id, task_id, media_id, user_settings,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = _safe_error(exc)
            logger.warning("Import annotation stage failed: %s", error)
            async with async_session_maker() as session:
                await session.execute(update(MediaFile).where(
                    MediaFile.id == media_id, MediaFile.user_id == user_id,
                    MediaFile.annotation_status.not_in(("partial", "cancelled")),
                ).values(annotation_status="failed"))
                await session.commit()
        await _checkpoint(user_id, task_id)
        return error


async def _run_import(user_id, task_id, files, embedding_model, embedding_dimension,
                      tag_model, generate_vectors, generate_tags, tag_mode,
                      custom_tag_prompt, user_settings):
    if not await _update_active(user_id, task_id, status="running"):
        return
    async with borrow_tos(user_settings or {}) as tos:
        api_key = (user_settings or {}).get("ark_api_key") or ""
        processed = failed = 0
        last_error = None
        for info in files:
            await _checkpoint(user_id, task_id)
            try:
                error = await _process_file(
                    user_id, task_id, info, tos, api_key, embedding_model, embedding_dimension,
                    tag_model, generate_vectors, generate_tags, tag_mode, custom_tag_prompt,
                    user_settings,
                )
            except Exception as exc:
                error = _safe_error(exc)
                logger.warning("Import file failed: %s", error)
            if error:
                failed += 1
                last_error = error
            processed += 1
            if not await _update_active(
                user_id, task_id, processed_files=processed, failed_files=failed,
                error_message=_error_text(last_error) if last_error else None,
            ):
                return
        await _checkpoint(user_id, task_id)
        await annotation_job_service.progress(user_id, task_id, finish=True)
        await _update_active(
            user_id, task_id,
            status="failed" if failed else "completed", completed_at=_now(),
        )


async def process_import_task(
    task_id: str, files: list[dict], user_id: str,
    embedding_model: Optional[str] = None, embedding_dimension: Optional[int] = None,
    tag_model: Optional[str] = None, generate_vectors: bool = True,
    generate_tags: bool = True, user_settings: Optional[dict] = None,
):
    global _limiter
    if _limiter is None:
        _limiter = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)
    try:
        async with async_session_maker() as session:
            snapshot = await session.scalar(
                select(ImportTask).where(
                    ImportTask.user_id == user_id,
                    ImportTask.task_id == task_id,
                )
            )
        if snapshot is None:
            raise ServiceError("application", "not_found")
        tag_mode, custom_tag_prompt = snapshot.tag_mode, snapshot.custom_tag_prompt
        saved = (snapshot.annotation_config or {}).get("import", {})
        embedding_model = saved.get("embedding_model", embedding_model)
        embedding_dimension = saved.get("embedding_dimension", embedding_dimension)
        tag_model = saved.get("tag_model", tag_model)
        generate_vectors = saved.get("generate_vectors", generate_vectors)
        generate_tags = saved.get("generate_tags", generate_tags)
        async with _limiter:
            async with asyncio.timeout(settings.TASK_TIMEOUT):
                await _run_import(
                    user_id, task_id, files, embedding_model or settings.ARK_EMBEDDING_MODEL,
                    embedding_dimension or settings.EMBEDDING_DIMENSION,
                    tag_model or settings.ARK_TAG_MODEL, generate_vectors,
                    generate_tags, tag_mode, custom_tag_prompt, user_settings,
                )
    except asyncio.CancelledError:
        await annotation_job_service.interrupt_task(user_id, task_id, cancelled=True)
        await _fail_remaining(
            user_id, task_id,
            _safe_error(ServiceError("application", "unavailable", retryable=True)),
        )
        raise
    except Exception as exc:
        error = _safe_error(exc)
        logger.warning("Import task failed: %s", error)
        await annotation_job_service.interrupt_task(user_id, task_id)
        await _fail_remaining(user_id, task_id, error)


def _task_finished(task_id, worker):
    _tasks.pop(task_id, None)
    if not worker.cancelled() and worker.exception() is not None:
        logger.error("Import task persistence failed: %s", _safe_error(worker.exception(), "mysql"))


def prepare_import_tasks():
    global _limiter, _registry_lock, _stopping
    _limiter = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)
    _registry_lock = asyncio.Lock()
    _stopping = False


async def recover_interrupted_imports():
    """Only called during single-process startup, before admitting new jobs."""
    error = _error_text(ServiceError("application", "unavailable", retryable=True).to_dict())
    total = func.coalesce(ImportTask.total_files, 0)
    processed = func.coalesce(ImportTask.processed_files, 0)
    failed = func.coalesce(ImportTask.failed_files, 0)
    remaining = case((total > processed, total - processed), else_=0)
    recovered_failed = case((failed + remaining > total, total), else_=failed + remaining)
    async with async_session_maker() as session:
        await session.execute(update(ImportTask).where(ImportTask.status.in_(_ACTIVE)).values(
            status="failed", failed_files=recovered_failed, processed_files=total,
            error_message=error, completed_at=_now(),
        ))
        for field in (MediaFile.vector_status, MediaFile.tag_status):
            await session.execute(update(MediaFile).where(field == "processing").values({field: "failed"}))
        await session.commit()


async def shutdown_import_tasks():
    global _registry_lock, _stopping
    if _registry_lock is None:
        _registry_lock = asyncio.Lock()
    async with _registry_lock:
        _stopping = True
        workers = tuple(_tasks.values())
    for worker in workers:
        worker.cancel()
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)
    # Includes jobs cancelled while waiting for a slot, before their first await.
    await recover_interrupted_imports()
    _tasks.clear()


async def parse_import_request(request: Request) -> ImportStartRequest:
    """JSON and form transports converge before the strict shared contract."""
    try:
        if request.headers.get("content-type", "").split(";", 1)[0] in {
            "multipart/form-data", "application/x-www-form-urlencoded",
        }:
            async with request.form() as form:
                if len(form) != len(form.multi_items()):
                    raise ValueError
                payload = dict(form)
                for name in ("generate_annotations", "generate_vectors", "generate_tags"):
                    if name in payload:
                        value = payload[name]
                        if value not in ("true", "false"):
                            raise ValueError
                        payload[name] = value == "true"
                for name in (
                    "embedding_dimension", "annotation_sample_interval_seconds", "annotation_max_frames",
                ):
                    if name in payload:
                        payload[name] = int(payload[name])
        else:
            payload = await request.json()
        return ImportStartRequest.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError([
            {"type": error["type"], "loc": ("body", *error["loc"]), "msg": "Invalid field value"}
            for error in exc.errors(include_input=False, include_context=False)
        ]) from None
    except (ValueError, TypeError):
        raise RequestValidationError([
            {"type": "value_error", "loc": ("body",), "msg": "Invalid import request"}
        ]) from None


@router.post("/start", response_model=ApiResponse)
async def start_import(
    request: ImportStartRequest = Depends(parse_import_request),
    current_user: dict = Depends(get_current_user),
    user_settings: dict = Depends(get_user_settings),
    session: AsyncSession = Depends(get_session),
):
    global _registry_lock
    if _stopping:
        raise ServiceError("application", "unavailable", retryable=True)
    annotation_config = annotation_job_service.import_config(request, user_settings)
    annotation_config["import"] = {
        key: getattr(request, key) for key in (
            "embedding_model", "embedding_dimension", "tag_model",
            "generate_vectors", "generate_tags",
        )
    }
    try:
        async with borrow_tos(user_settings) as tos, asyncio.timeout(settings.TASK_TIMEOUT):
            files = await tos.list_files(request.tos_directory)
        files = list({info["tos_url"]: info for info in files}.values())
        if not files:
            raise ServiceError("tos", "not_found", status_code=400)
    except Exception as exc:
        error = exc if isinstance(exc, ServiceError) else ServiceError("tos", "unavailable", retryable=True)
        raise HTTPException(status_code=error.status_code, detail=error.to_dict()) from None
    if _registry_lock is None:
        _registry_lock = asyncio.Lock()
    async with _registry_lock:
        if _stopping:
            raise ServiceError("application", "unavailable", retryable=True)
        task_id = f"task_{uuid.uuid4().hex[:24]}"
        task = ImportTask(
            user_id=current_user["id"], task_id=task_id,
            tos_directory=request.tos_directory, status="pending",
            tag_mode=request.tag_mode,
            custom_tag_prompt=request.custom_tag_prompt,
            annotation_config=annotation_config,
            annotation_status="pending" if request.generate_annotations else "skipped",
            annotation_total_files=len(files) if request.generate_annotations else 0,
            total_files=len(files), processed_files=0, failed_files=0,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        worker = asyncio.create_task(process_import_task(
            task_id, files, current_user["id"],
            request.embedding_model, request.embedding_dimension,
            request.tag_model, request.generate_vectors, request.generate_tags,
            dict(user_settings),
        ))
        _tasks[task_id] = worker
        worker.add_done_callback(lambda done: _task_finished(task_id, done))
    return ApiResponse(data={
        "task_id": task_id, "status": "pending", "tos_directory": request.tos_directory,
        "created_at": task.created_at,
    })


def _task_detail(task: ImportTask, retry_media_ids=None):
    annotation_config = task.annotation_config or {}
    annotation_snapshot = (
        annotation_config.get("display_options")
        or annotation_config.get("snapshot")
        or {}
    )
    return ImportTaskDetail(
        task_id=task.task_id, tos_directory=task.tos_directory, status=task.status,
        tag_mode=task.tag_mode,
        total_files=task.total_files, processed_files=task.processed_files,
        failed_files=task.failed_files, error_message=_public_error(task.error_message),
        created_at=task.created_at, completed_at=task.completed_at,
        generate_annotations=annotation_config.get("enabled"),
        **{
            field: annotation_snapshot.get(field)
            for field in TASK_SNAPSHOT_FIELDS
        },
        annotation_status=task.annotation_status or "not_started",
        annotation_progress=task_progress(task),
        annotation_retry_media_ids=retry_media_ids or [],
    )


@router.get("/tasks", response_model=ApiResponse)
async def get_tasks(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(ImportTask)
    if current_user.get("role") != "admin":
        query = query.where(ImportTask.user_id == current_user["id"])
    tasks = (await session.scalars(
        query.order_by(ImportTask.created_at.desc()).limit(20)
    )).all()
    details = [
        _task_detail(task, await annotation_job_service.retry_media_ids(session, task))
        for task in tasks
    ]
    return ApiResponse(data={"tasks": details, "total": len(tasks)})


@router.get("/tasks/{task_id}", response_model=ApiResponse)
async def get_task_status(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(ImportTask).where(ImportTask.task_id == task_id)
    if current_user.get("role") != "admin":
        query = query.where(ImportTask.user_id == current_user["id"])
    task = await session.scalar(query)
    if task is None:
        raise HTTPException(status_code=404, detail=ServiceError("application", "not_found").to_dict())
    return ApiResponse(data=_task_detail(
        task, await annotation_job_service.retry_media_ids(session, task),
    ))


@router.delete("/tasks/{task_id}", response_model=ApiResponse)
async def cancel_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(ImportTask).where(
        ImportTask.task_id == task_id,
        ImportTask.user_id == current_user["id"],
    )
    task = await session.scalar(query)
    if task is None:
        raise HTTPException(status_code=404, detail=ServiceError("application", "not_found").to_dict())
    if task.status not in (*_ACTIVE, "cancelled"):
        raise HTTPException(status_code=409, detail=ServiceError("application", "invalid_request").to_dict())
    await session.execute(update(ImportTask).where(
        ImportTask.id == task.id, ImportTask.status.in_(_ACTIVE),
    ).values(status="cancelled", completed_at=_now(), error_message=None))
    await session.commit()
    worker = _tasks.get(task_id)
    if worker is not None:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    await annotation_job_service.cancel(task.user_id, task_id)
    return ApiResponse(message="任务已取消")


@router.delete("/media/{media_id}", response_model=ApiResponse)
async def delete_media(
    media_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete owned media metadata, then reclaim its unreferenced private frames."""
    cleanup = AnnotationCleanupService(settings.ANNOTATION_STORAGE_DIR)
    try:
        resources = await cleanup.prepare_media_cleanup(
            session, user_id=current_user["id"], media_id=media_id,
        )
        if resources and not settings.ANNOTATION_STORAGE_DIR:
            raise MissingConfigurationError("application", ["ANNOTATION_STORAGE_DIR"])
        await session.execute(delete(MediaTag).where(
            MediaTag.media_id == media_id,
            MediaTag.user_id == current_user["id"],
        ))
        result = await session.execute(delete(MediaFile).where(
            MediaFile.id == media_id,
            MediaFile.user_id == current_user["id"],
        ))
        if result.rowcount != 1:
            raise ServiceError("application", "not_found", status_code=404)
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    await cleanup.reclaim_frames(session, resources)
    return ApiResponse(message="媒体已删除")
