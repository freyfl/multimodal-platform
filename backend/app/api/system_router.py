"""Liveness, dependency readiness and aggregate system statistics."""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_user_settings
from app.config import get_model_catalog, settings
from app.errors import ServiceError
from app.models.database import async_session_maker, get_session
from app.models.schemas import ApiResponse, HealthCheck, SystemStats
from app.services.milvus_service import milvus_service
from app.services.tos_service import tos_service

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/health", response_model=ApiResponse)
async def health_check():
    """Process liveness only: no database, storage or billable model calls."""
    return ApiResponse(data=HealthCheck(status="ok", version=settings.APP_VERSION))


async def _check_mysql():
    async with async_session_maker() as session:
        result = await session.execute(text("SELECT 1"))
        if result.scalar_one() != 1:
            raise ServiceError("mysql", "invalid_response")
    return {"status": "ready"}


async def _check_dependency(name, check):
    try:
        result = await check()
        if not isinstance(result, dict):
            raise ServiceError(name, "invalid_response")
        if result.get("success") is False or result.get("status") not in ("ok", "ready"):
            raise ServiceError(name, "unavailable")
        return {"status": "ready", "error": None}
    except ServiceError as error:
        return {"status": "unavailable", "error": error.to_dict()}
    except Exception:
        return {"status": "unavailable", "error": ServiceError(name, "unavailable").to_dict()}


@router.get("/readiness", response_model=ApiResponse)
async def readiness_check():
    names = ("tos", "mysql", "milvus")
    results = await asyncio.gather(
        _check_dependency("tos", tos_service.check_connection),
        _check_dependency("mysql", _check_mysql),
        _check_dependency("milvus", milvus_service.check_connection),
    )
    ready = all(item["status"] == "ready" for item in results)
    response = ApiResponse(
        code=200 if ready else 503,
        message="就绪" if ready else "依赖服务未就绪",
        data={"status": "ready" if ready else "unavailable", "services": dict(zip(names, results))},
    )
    return JSONResponse(status_code=200 if ready else 503, content=response.model_dump(mode="json"))


@router.get("/stats", response_model=ApiResponse)
async def get_system_stats(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    scoped_user_id = None if current_user.get("role") == "admin" else current_user["id"]
    scope_sql = "" if scoped_user_id is None else " WHERE user_id = :uid"
    params = {"uid": scoped_user_id}
    try:
        media = (await session.execute(text(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN file_type = 'video' THEN 1 ELSE 0 END), 0) AS videos, "
            "COALESCE(SUM(CASE WHEN file_type = 'image' THEN 1 ELSE 0 END), 0) AS images, "
            f"COALESCE(SUM(file_size), 0) AS storage_bytes FROM media_files{scope_sql}"
        ), params)).mappings().one()
        tasks = (await session.execute(text(
            "SELECT COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0) AS running, "
            "COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending, "
            "COALESCE(SUM(CASE WHEN status = 'completed' AND completed_at >= :today "
            "AND completed_at < :tomorrow THEN 1 ELSE 0 END), 0) AS completed_today "
            f"FROM import_tasks{scope_sql}"
        ), {
            **params, "today": today, "tomorrow": today + timedelta(days=1),
        })).mappings().one()
        searches = (await session.execute(text(
            "SELECT COUNT(*) AS total_searches, "
            "COALESCE(SUM(CASE WHEN search_type = 'tag' THEN 1 ELSE 0 END), 0) AS tag_searches, "
            "COALESCE(SUM(CASE WHEN search_type = 'text' THEN 1 ELSE 0 END), 0) AS text_searches, "
            "COALESCE(SUM(CASE WHEN search_type = 'image' THEN 1 ELSE 0 END), 0) AS image_searches "
            f"FROM search_history{scope_sql}"
        ), params)).mappings().one()
    except SQLAlchemyError:
        raise ServiceError("mysql", "unavailable") from None

    try:
        vector_count = await milvus_service.get_vector_count(scoped_user_id)
        if type(vector_count) is not int or vector_count < 0:
            raise ServiceError("milvus", "invalid_response")
    except ServiceError:
        raise
    except Exception:
        raise ServiceError("milvus", "unavailable") from None

    return ApiResponse(data=SystemStats(
        media={
            "total": int(media["total"]), "videos": int(media["videos"]),
            "images": int(media["images"]),
            "storage_used_gb": round(float(media["storage_bytes"]) / 1024 ** 3, 2),
        },
        vectors={
            "total": vector_count, "dimension": settings.EMBEDDING_DIMENSION,
            "count_is_exact": True,
        },
        tasks={key: int(value) for key, value in tasks.items()},
        performance={key: int(value) for key, value in searches.items()},
    ))


@router.get("/config", response_model=ApiResponse)
async def get_public_config():
    return ApiResponse(data={
        "apiPrefix": settings.API_PREFIX,
        "appName": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "model_catalog": get_model_catalog(settings),
    })


@router.get("/dashboard", response_model=ApiResponse)
async def get_dashboard_info(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
    user_cfg: dict = Depends(get_user_settings),
):
    # This is configured bucket metadata, not a claim that the bucket is ready.
    bucket = {
        "bucket_name": user_cfg["tos_bucket_name"],
        "endpoint": user_cfg["tos_endpoint"],
        "region": user_cfg["tos_region"],
    }
    try:
        scope_sql = "" if current_user.get("role") == "admin" else " WHERE user_id = :uid"
        result = await session.execute(text(
            "SELECT task_id, tos_directory, status, total_files, processed_files, created_at "
            f"FROM import_tasks{scope_sql} ORDER BY created_at DESC, task_id DESC"
        ), {"uid": current_user["id"]})
        directories = {}
        for row in result.mappings():
            directory = row["tos_directory"]
            if not directory or directory in directories:
                continue
            directories[directory] = {
                "task_id": row["task_id"], "tos_directory": directory,
                "status": row["status"], "total_files": row["total_files"],
                "processed_files": row["processed_files"],
                "created_at": str(row["created_at"]) if row["created_at"] else None,
            }
    except SQLAlchemyError:
        raise ServiceError("mysql", "unavailable") from None
    return ApiResponse(data={"bucket": bucket, "imported_dirs": list(directories.values())})
