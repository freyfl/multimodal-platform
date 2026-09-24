"""Single-process annotation jobs with durable, owner-scoped frame checkpoints.

T5 calls submit_job(*, session, user_id, request). Imports use annotate_import.
Only this service schedules annotation-only retries; it never calls tags/vectors.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from time import monotonic
from uuid import uuid4

from sqlalchemy import select, update

from app.api.deps import effective_user_settings
from app.config import settings
from app.errors import MissingConfigurationError, ServiceError
from app.models.database import async_session_maker
from app.models.models import AnnotationFrame, AnnotationRun, ImportTask, MediaFile, UserSystemSettings
from app.models.annotation_schemas import (
    ANNOTATION_MODEL, AnnotationJobRequest, AnnotationJobResponse, AnnotationOptions,
    AnnotationRuleSnapshot, AnnotationTaskProgress,
)
from app.services.annotation_frame_service import (
    FrameStorageContext, PreparedFrame, annotation_frame_service,
)
from app.services.annotation_rules import build_rule_snapshot
from app.services.annotation_service import annotation_service
from app.services.tos_service import borrow_tos
from app.utils.helpers import parse_tos_url
from app.utils.logger import logger


ACTIVE = ("pending", "running")
RETRYABLE = ("partial", "failed", "cancelled")
TASK_SNAPSHOT_FIELDS = (
    "annotation_mode", "annotation_box_mode",
    "annotation_sample_interval_seconds", "annotation_max_frames",
)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def safe_error(exc):
    if isinstance(exc, ServiceError):
        return exc.category
    return "timeout" if isinstance(exc, TimeoutError) else "unavailable"


def source_snapshot(snapshot, etag, version):
    payload = snapshot.model_dump(exclude={"rule_hash"})
    payload.update(source_etag=etag, source_version=version)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return AnnotationRuleSnapshot(
        **payload, rule_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def public_task_snapshot(snapshot):
    return {field: getattr(snapshot, field) for field in TASK_SNAPSHOT_FIELDS}


def task_progress(task):
    fields = AnnotationTaskProgress.model_fields
    values = {name: getattr(task, "annotation_" + name, None) for name in fields}
    for name in fields:
        if values[name] is None and name not in {"current_media_id", "current_frame_index"}:
            values[name] = 0
    if task.annotation_started_at and task.annotation_status in ACTIVE:
        values["elapsed_ms"] = max(
            values["elapsed_ms"], int((now() - task.annotation_started_at).total_seconds() * 1000),
        )
    return AnnotationTaskProgress(**values)


class AnnotationJobService:
    def __init__(self):
        self.workers = {}
        self._lock = None
        self._limiter = None
        self._stopping = False

    def prepare(self):
        self._lock = asyncio.Lock()
        self._limiter = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)
        self._stopping = False

    @asynccontextmanager
    async def submission(self):
        if self._lock is None:
            self.prepare()
        async with self._lock:
            if self._stopping:
                raise ServiceError("application", "unavailable", retryable=True)
            yield

    @staticmethod
    def validate_config(config):
        for field, public in (("ark_api_key", "ARK_API_KEY"), ("tag_model", "ARK_TAG_MODEL")):
            if not isinstance(config.get(field), str) or not config[field].strip():
                raise MissingConfigurationError("ark", [public])
        if config["tag_model"] != ANNOTATION_MODEL:
            raise ServiceError("ark", "invalid_request", status_code=422)

    async def owner_config(self, session, user_id):
        row = await session.scalar(select(UserSystemSettings).where(
            UserSystemSettings.user_id == user_id,
        ))
        saved = None if row is None else {
            column.name: getattr(row, column.name)
            for column in UserSystemSettings.__table__.columns
            if column.name not in {"id", "user_id", "created_at", "updated_at"}
        }
        config = effective_user_settings(saved)
        self.validate_config(config)
        return config

    def import_config(self, request, config):
        if not request.generate_annotations:
            return {"enabled": False}
        self.validate_config(config)
        options = AnnotationOptions.model_validate({
            key: getattr(request, key) for key in AnnotationOptions.model_fields
        })
        snapshot = build_rule_snapshot(
            options, model=config["tag_model"], source_etag=None, source_version=None,
        )
        return {"enabled": True, "snapshot": snapshot.model_dump(), "run_ids": [], "media_ids": []}

    async def head_source(self, media, config):
        parsed = parse_tos_url(media.tos_url)
        if not parsed or not parsed["path"] or parsed["bucket"] != config.get("tos_bucket_name"):
            raise ServiceError("application", "not_found", status_code=404)
        async with borrow_tos(config) as tos:
            head = await tos.open_object(media.tos_url, method="HEAD")
            try:
                if head.status_code != 200:
                    raise ServiceError("tos", "not_found" if head.status_code == 404 else "unavailable")
                headers = {key.lower(): value for key, value in head.headers.items()}
                etag, version = headers.get("etag"), headers.get("x-tos-version-id")
                if not etag and not version:
                    raise ServiceError("tos", "invalid_response", status_code=502)
                return etag, version
            finally:
                await head.aclose()

    async def owned_media(self, session, user_id, media_id, *, lock=False):
        query = select(MediaFile).where(MediaFile.id == media_id, MediaFile.user_id == user_id)
        media = await session.scalar(query.with_for_update() if lock else query)
        if media is None or not user_id:
            raise ServiceError("application", "not_found", status_code=404)
        return media

    async def select_run(self, session, user_id, media, task_id, snapshot, action):
        runs = (await session.scalars(select(AnnotationRun).where(
            AnnotationRun.user_id == user_id, AnnotationRun.media_id == media.id,
        ).order_by(AnnotationRun.revision.desc()).with_for_update())).all()
        active = next((run for run in runs if run.status in ACTIVE), None)
        if active:
            if action == "regenerate" or active.idempotency_hash != snapshot.rule_hash:
                raise ServiceError("application", "invalid_request", status_code=409)
            return active
        if action == "retry":
            if not runs or runs[0].status not in RETRYABLE:
                raise ServiceError("application", "invalid_request", status_code=409)
            run = runs[0]
            if run.idempotency_hash != snapshot.rule_hash:
                raise ServiceError("application", "invalid_request", status_code=409)
            run.status, run.active_key, run.task_id = "pending", run.idempotency_hash, task_id
            run.error, run.completed_at = None, None
        else:
            if action == "generate":
                complete = next((
                    run for run in runs
                    if run.status == "completed" and run.idempotency_hash == snapshot.rule_hash
                ), None)
                if complete:
                    return complete
            run = AnnotationRun(
                id=str(uuid4()), user_id=user_id, media_id=media.id, task_id=task_id,
                revision=runs[0].revision + 1 if runs else 1, status="pending",
                snapshot=snapshot.model_dump(), source_etag=snapshot.source_etag,
                source_version=snapshot.source_version, idempotency_hash=snapshot.rule_hash,
                active_key=snapshot.rule_hash,
            )
            session.add(run)
        media.annotation_status = "pending"
        await session.flush()
        return run

    async def submit_job(self, *, session, user_id, request):
        request = AnnotationJobRequest.model_validate(request.model_dump())
        async with self.submission():
            # Check the entire batch before touching cloud storage or creating work.
            media = [await self.owned_media(session, user_id, identity)
                     for identity in request.media_ids]
            config = await self.owner_config(session, user_id)
            snapshots = {}
            async with asyncio.timeout(settings.TASK_TIMEOUT):
                for item in media:
                    etag, version = await self.head_source(item, config)
                    if request.action == "retry":
                        latest = await session.scalar(select(AnnotationRun).where(
                            AnnotationRun.user_id == user_id, AnnotationRun.media_id == item.id,
                        ).order_by(AnnotationRun.revision.desc()).limit(1))
                        if latest is None:
                            raise ServiceError("application", "invalid_request", status_code=409)
                        snapshot = AnnotationRuleSnapshot.model_validate(latest.snapshot)
                        if snapshot.model != ANNOTATION_MODEL:
                            raise ServiceError("ark", "invalid_request", status_code=409)
                        if (etag, version) != (snapshot.source_etag, snapshot.source_version):
                            raise ServiceError("application", "invalid_request", status_code=409)
                    else:
                        snapshot = build_rule_snapshot(
                            request.options or AnnotationOptions(), model=config["tag_model"],
                            source_etag=etag, source_version=version,
                        )
                    snapshots[item.id] = snapshot
            task_id = "task_" + uuid4().hex[:24]
            task = ImportTask(
                user_id=user_id, task_id=task_id, tos_directory="annotations",
                status="pending", total_files=len(media), annotation_status="pending",
                annotation_total_files=len(media),
            )
            session.add(task)
            try:
                await session.flush()
                runs = []
                for item in sorted(media, key=lambda item: item.id):
                    item = await self.owned_media(session, user_id, item.id, lock=True)
                    runs.append(await self.select_run(
                        session, user_id, item, task_id, snapshots[item.id], request.action,
                    ))
                # Identical in-flight submissions share the original task too.
                owners = {run.task_id for run in runs if run.status in ACTIVE}
                if len(owners) == 1 and task_id not in owners and all(run.status in ACTIVE for run in runs):
                    existing = await session.scalar(select(ImportTask).where(
                        ImportTask.task_id == next(iter(owners)), ImportTask.user_id == user_id,
                    ))
                    if existing and set((existing.annotation_config or {}).get("run_ids", [])) == {r.id for r in runs}:
                        result = AnnotationJobResponse(
                            task_id=existing.task_id, status=existing.annotation_status,
                            media_ids=request.media_ids, run_ids=[r.id for r in runs],
                        )
                        await session.rollback()
                        return result
                task.annotation_config = {
                    "enabled": True, "job": True, "media_ids": request.media_ids,
                    "run_ids": [run.id for run in runs],
                    "display_options": (
                        public_task_snapshot(next(iter(snapshots.values())))
                        if len({
                            tuple(public_task_snapshot(snapshot).items())
                            for snapshot in snapshots.values()
                        }) == 1 else None
                    ),
                }
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
            response = AnnotationJobResponse(
                task_id=task_id, status="pending", media_ids=request.media_ids,
                run_ids=[run.id for run in runs],
            )
            worker = asyncio.create_task(self.run_job(user_id, task_id, dict(config)))
            self.workers[task_id] = worker
            worker.add_done_callback(lambda done: self._finished(task_id, done))
            return response

    def _finished(self, task_id, worker):
        self.workers.pop(task_id, None)
        if not worker.cancelled() and worker.exception() is not None:
            logger.error("Annotation persistence failed: %s", safe_error(worker.exception()))

    async def checkpoint(self, user_id, task_id):
        async with async_session_maker() as session:
            status = await session.scalar(select(ImportTask.status).where(
                ImportTask.user_id == user_id, ImportTask.task_id == task_id,
            ))
        if status not in ACTIVE:
            raise asyncio.CancelledError

    async def progress(self, user_id, task_id, *, media_id=None, frame_index=None, finish=False):
        async with async_session_maker() as session:
            task = await session.scalar(select(ImportTask).where(
                ImportTask.user_id == user_id, ImportTask.task_id == task_id,
            ).with_for_update())
            if task is None or task.status not in ACTIVE or not (task.annotation_config or {}).get("enabled"):
                return
            runs = (await session.scalars(select(AnnotationRun).where(
                AnnotationRun.user_id == user_id,
                AnnotationRun.id.in_(task.annotation_config.get("run_ids", [])),
            ))).all()
            task.annotation_started_at = task.annotation_started_at or now()
            task.annotation_elapsed_ms = max(
                0, int((now() - task.annotation_started_at).total_seconds() * 1000),
            )
            for field in ("planned_frames", "processed_frames", "completed_frames", "failed_frames"):
                setattr(task, "annotation_" + field, sum(getattr(run, field) or 0 for run in runs))
            complete = sum(run.status == "completed" for run in runs)
            failed = sum(run.status in RETRYABLE for run in runs)
            task.annotation_completed_files = complete
            task.annotation_failed_files = failed
            task.annotation_processed_files = complete + failed
            task.annotation_status = "running"
            task.annotation_current_media_id = media_id
            task.annotation_current_frame_index = frame_index
            if finish:
                total = task.annotation_total_files
                task.annotation_failed_files = total - complete
                task.annotation_processed_files = total
                task.annotation_status = (
                    "completed" if complete == total else
                    "partial" if task.annotation_completed_frames else "failed"
                )
                task.annotation_completed_at = now()
                task.annotation_current_media_id = None
                task.annotation_current_frame_index = None
            await session.commit()

    @asynccontextmanager
    async def heartbeat(self, callback):
        async def pulse():
            while True:
                await asyncio.sleep(1)
                await callback()
        await callback()
        worker = asyncio.create_task(pulse())
        try:
            yield
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def annotate_import(self, user_id, task_id, media_id, config):
        await self.checkpoint(user_id, task_id)
        async with self.submission():
            async with async_session_maker() as session:
                task = await session.scalar(select(ImportTask).where(
                    ImportTask.user_id == user_id, ImportTask.task_id == task_id,
                ))
                if task is None or not (task.annotation_config or {}).get("enabled"):
                    if task is not None and (task.annotation_config or {}).get("enabled") is False:
                        await session.execute(update(MediaFile).where(
                            MediaFile.id == media_id, MediaFile.user_id == user_id,
                            MediaFile.annotation_status == "not_started",
                        ).values(annotation_status="skipped"))
                        await session.commit()
                    return
                stored = dict(task.annotation_config)
                stored["media_ids"] = list(dict.fromkeys([*stored.get("media_ids", []), media_id]))
                task.annotation_config = stored
                await session.commit()
                media = await self.owned_media(session, user_id, media_id)
                etag, version = await self.head_source(media, config)
                snapshot = source_snapshot(
                    AnnotationRuleSnapshot.model_validate(stored["snapshot"]), etag, version,
                )
                await self.checkpoint(user_id, task_id)
                media = await self.owned_media(session, user_id, media_id, lock=True)
                run = await self.select_run(session, user_id, media, task_id, snapshot, "generate")
                task.annotation_config = {
                    **stored, "run_ids": list(dict.fromkeys([*stored.get("run_ids", []), run.id])),
                }
                await session.commit()
                run_id = run.id
        status = await self.execute_run(user_id, task_id, run_id, config)
        if status != "completed":
            raise ServiceError("application", "unavailable", retryable=True)

    async def _counts(self, session, run):
        frames = (await session.scalars(select(AnnotationFrame).where(
            AnnotationFrame.user_id == run.user_id, AnnotationFrame.run_id == run.id,
        ))).all()
        run.completed_frames = sum(frame.status == "completed" for frame in frames)
        run.failed_frames = sum(frame.status in RETRYABLE for frame in frames)
        run.processed_frames = run.completed_frames + run.failed_frames
        run.model_elapsed_ms = sum(frame.model_elapsed_ms or 0 for frame in frames)
        return frames

    async def terminal_run(self, user_id, task_id, run_id, *, error=None, cancelled=False):
        async with async_session_maker() as session:
            # Lock task first, matching cancel/progress, to serialize publication.
            task = await session.scalar(select(ImportTask).where(
                ImportTask.user_id == user_id, ImportTask.task_id == task_id,
            ).with_for_update())
            run = await session.scalar(select(AnnotationRun).where(
                AnnotationRun.id == run_id, AnnotationRun.user_id == user_id,
                AnnotationRun.task_id == task_id,
            ).with_for_update())
            if run is None or run.status not in ACTIVE:
                return run.status if run else "failed"
            frames = await self._counts(session, run)
            cancelled = cancelled or task is None or task.status == "cancelled"
            complete = (
                bool(frames) and all(frame.status == "completed" for frame in frames)
                and not error and task is not None and task.status in ACTIVE
            )
            run.status = (
                "cancelled" if cancelled else "completed" if complete else
                "partial" if run.completed_frames else "failed"
            )
            run.active_key, run.error, run.completed_at = None, error, now()
            media = await self.owned_media(session, user_id, run.media_id, lock=True)
            media.annotation_status = run.status
            if run.status == "completed" and task.status in ACTIVE:
                media.published_annotation_run_id = run.id
            await session.commit()
            return run.status

    async def execute_run(self, user_id, task_id, run_id, config):
        # A wrapper task may observe another task's run, never execute or cancel it.
        while True:
            await self.checkpoint(user_id, task_id)
            async with async_session_maker() as session:
                run = await session.scalar(select(AnnotationRun).where(
                    AnnotationRun.id == run_id, AnnotationRun.user_id == user_id,
                ))
                if run is None:
                    raise ServiceError("application", "not_found", status_code=404)
                if run.status not in ACTIVE:
                    await self.progress(user_id, task_id)
                    return run.status
                if run.task_id == task_id:
                    break
            await self.progress(user_id, task_id, media_id=run.media_id)
            await asyncio.sleep(0.25)
        media_id = run.media_id
        frame_index = None

        async def callback():
            await self.checkpoint(user_id, task_id)
            await self.progress(user_id, task_id, media_id=media_id, frame_index=frame_index)

        try:
            async with self.heartbeat(callback):
                snapshot = AnnotationRuleSnapshot.model_validate(run.snapshot)
                context = FrameStorageContext.from_settings(
                    user_id, media_id, run.id, source_etag=run.source_etag,
                    source_version=run.source_version, config=settings,
                )
                execution_config = {**config, "tag_model": snapshot.model}
                async with async_session_maker() as session:
                    media = await self.owned_media(session, user_id, media_id)
                    if await self.head_source(media, execution_config) != (run.source_etag, run.source_version):
                        raise ServiceError("application", "invalid_request", status_code=409)
                    frames = (await session.scalars(select(AnnotationFrame).where(
                        AnnotationFrame.user_id == user_id, AnnotationFrame.run_id == run_id,
                    ).order_by(AnnotationFrame.frame_index))).all()
                    await session.execute(update(AnnotationRun).where(
                        AnnotationRun.id == run_id, AnnotationRun.user_id == user_id,
                    ).values(status="running", started_at=now()))
                    await session.execute(update(MediaFile).where(
                        MediaFile.id == media_id, MediaFile.user_id == user_id,
                    ).values(annotation_status="running"))
                    await session.commit()
                if not frames:
                    await callback()
                    prepared = await annotation_frame_service.prepare_frames(
                        media, execution_config, context=context,
                        interval_seconds=snapshot.annotation_sample_interval_seconds,
                        max_frames=snapshot.annotation_max_frames,
                    )
                    await self.checkpoint(user_id, task_id)
                    if (prepared.source_etag, prepared.source_version) != (run.source_etag, run.source_version):
                        raise ServiceError("application", "invalid_request", status_code=409)
                    async with async_session_maker() as session:
                        for frame in prepared.frames:
                            session.add(AnnotationFrame(
                                id=frame.id, user_id=user_id, run_id=run_id,
                                frame_index=frame.frame_index, timestamp_ms=frame.timestamp_ms,
                                width=frame.width, height=frame.height, storage_key=frame.storage_key,
                                status="pending", objects=[],
                            ))
                        await session.execute(update(AnnotationRun).where(
                            AnnotationRun.id == run_id, AnnotationRun.user_id == user_id,
                        ).values(planned_frames=prepared.planned_frames))
                        await session.commit()
                        frames = (await session.scalars(select(AnnotationFrame).where(
                            AnnotationFrame.run_id == run_id, AnnotationFrame.user_id == user_id,
                        ).order_by(AnnotationFrame.frame_index))).all()
                pending_frames = [frame for frame in frames if frame.status != "completed"]
                frame_limiter = asyncio.Semaphore(settings.ARK_MAX_CONCURRENCY)

                async def process_frame(frame):
                    nonlocal frame_index
                    async with frame_limiter:
                        frame_index = frame.frame_index
                        await callback()
                        started = monotonic()
                        try:
                            path = annotation_frame_service.resolve_frame_path(
                                context, frame.storage_key,
                            )
                            prepared_frame = PreparedFrame(
                                frame.id, frame.frame_index, frame.timestamp_ms, frame.width,
                                frame.height, frame.storage_key, path,
                            )
                            objects = await annotation_service.annotate_frame(
                                prepared_frame, execution_config, snapshot=snapshot, context=context,
                            )
                            status, error = "completed", None
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            objects, status, error = [], "failed", safe_error(exc)
                        # A finished paid request remains a checkpoint even if cancelled next.
                        async with async_session_maker() as frame_session:
                            await frame_session.execute(update(AnnotationFrame).where(
                                AnnotationFrame.id == frame.id,
                                AnnotationFrame.user_id == user_id,
                            ).values(
                                status=status, objects=objects, error=error,
                                model_elapsed_ms=(frame.model_elapsed_ms or 0)
                                + int((monotonic() - started) * 1000),
                            ))
                            stored_run = await frame_session.get(AnnotationRun, run_id)
                            await self._counts(frame_session, stored_run)
                            await frame_session.commit()
                        await callback()

                async with asyncio.TaskGroup() as group:
                    for frame in pending_frames:
                        group.create_task(process_frame(frame))
                await self.checkpoint(user_id, task_id)
                if await self.head_source(media, execution_config) != (run.source_etag, run.source_version):
                    raise ServiceError("application", "invalid_request", status_code=409)
                status = await self.terminal_run(user_id, task_id, run_id)
        except asyncio.CancelledError:
            await self.terminal_run(user_id, task_id, run_id, cancelled=True)
            raise
        except Exception as exc:
            status = await self.terminal_run(user_id, task_id, run_id, error=safe_error(exc))
        await self.progress(user_id, task_id)
        return status

    async def run_job(self, user_id, task_id, config):
        try:
            async with self._limiter, asyncio.timeout(settings.TASK_TIMEOUT):
                await self.checkpoint(user_id, task_id)
                async with async_session_maker() as session:
                    task = await session.scalar(select(ImportTask).where(
                        ImportTask.user_id == user_id, ImportTask.task_id == task_id,
                    ))
                    run_ids = task.annotation_config["run_ids"]
                    await session.execute(update(ImportTask).where(
                        ImportTask.task_id == task_id, ImportTask.status.in_(ACTIVE),
                    ).values(status="running"))
                    await session.commit()
                for run_id in run_ids:
                    await self.execute_run(user_id, task_id, run_id, config)
                await self.progress(user_id, task_id, finish=True)
                async with async_session_maker() as session:
                    task = await session.scalar(select(ImportTask).where(
                        ImportTask.user_id == user_id, ImportTask.task_id == task_id,
                    ).with_for_update())
                    if task.status in ACTIVE:
                        task.processed_files = task.total_files
                        task.failed_files = task.annotation_failed_files
                        task.status = "failed" if task.failed_files else "completed"
                        task.completed_at = now()
                        await session.commit()
        except asyncio.CancelledError:
            await self.interrupt_task(user_id, task_id, cancelled=True)
            raise
        except Exception as exc:
            await self.interrupt_task(user_id, task_id, error=safe_error(exc))

    async def interrupt_task(self, user_id, task_id, *, cancelled=False, error="unavailable"):
        async with async_session_maker() as session:
            ids = (await session.scalars(select(AnnotationRun.id).where(
                AnnotationRun.user_id == user_id, AnnotationRun.task_id == task_id,
                AnnotationRun.status.in_(ACTIVE),
            ))).all()
        for run_id in ids:
            await self.terminal_run(user_id, task_id, run_id, error=error, cancelled=cancelled)
        await self.progress(user_id, task_id, finish=True)
        async with async_session_maker() as session:
            task = await session.scalar(select(ImportTask).where(
                ImportTask.user_id == user_id, ImportTask.task_id == task_id,
            ).with_for_update())
            if task is None:
                return
            if (task.annotation_config or {}).get("enabled") and (
                task.annotation_status in ACTIVE or cancelled
            ):
                task.annotation_status = "cancelled" if cancelled else "failed"
                task.annotation_completed_at = now()
            if task.status in ACTIVE:
                task.status = "cancelled" if cancelled else "failed"
                task.completed_at = now()
                task.processed_files = task.total_files
                task.failed_files = max(task.failed_files or 0, task.total_files - task.annotation_completed_files)
                task.error_message = json.dumps(ServiceError(
                    "application", error, retryable=True,
                ).to_dict())
            await session.commit()

    async def cancel(self, user_id, task_id):
        worker = self.workers.get(task_id)
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await self.interrupt_task(user_id, task_id, cancelled=True)

    async def recover(self):
        """No scheduling or cloud calls: a restart only makes interrupted work retryable."""
        async with async_session_maker() as session:
            runs = (await session.scalars(select(AnnotationRun).where(
                AnnotationRun.status.in_(ACTIVE),
            ))).all()
            for run in runs:
                await self._counts(session, run)
                run.status = "partial" if run.completed_frames else "failed"
                run.active_key, run.error, run.completed_at = None, "interrupted", now()
                await session.execute(update(MediaFile).where(
                    MediaFile.id == run.media_id, MediaFile.user_id == run.user_id,
                ).values(annotation_status=run.status))
            await session.execute(update(ImportTask).where(
                ImportTask.annotation_status.in_(ACTIVE),
            ).values(
                annotation_status="failed", annotation_completed_at=now(),
                status="failed", completed_at=now(),
            ))
            await session.commit()

    async def cleanup_temporary(self):
        if settings.ANNOTATION_STORAGE_DIR and settings.ANNOTATION_TEMP_DIR:
            context = FrameStorageContext.from_settings("startup", "startup", "startup", config=settings)
            await annotation_frame_service.cleanup_temporary(context)

    async def shutdown(self):
        async with self.submission():
            self._stopping = True
            workers = tuple(self.workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await self.recover()
        self.workers.clear()

    async def retry_media_ids(self, session, task):
        config = task.annotation_config or {}
        if not config.get("enabled"):
            return []
        runs = (await session.scalars(select(AnnotationRun).where(
            AnnotationRun.user_id == task.user_id,
            AnnotationRun.id.in_(config.get("run_ids", [])),
        ))).all()
        retryable = {
            run.media_id for run in runs
            if (
                run.status in RETRYABLE
                and AnnotationRuleSnapshot.model_validate(run.snapshot).model == ANNOTATION_MODEL
            )
        }
        return [
            identity for identity in config.get("media_ids", [])
            if identity in retryable
        ]


annotation_job_service = AnnotationJobService()
