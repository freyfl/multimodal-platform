"""Annotation JSON uses ApiResponse; exact-frame images require Bearer auth.

T4 integration: include router with the existing API prefix in main.py, and
provide annotation_job_service.submit_job(*, session, user_id, request), returning
AnnotationJobResponse. That service owns task persistence/scheduling and must
recheck ownership when executing. This module never starts paid work itself.
"""

from importlib import import_module

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, security
from app.errors import ServiceError
from app.models import annotation_schemas as schema
from app.models.database import get_session
from app.models.schemas import ApiResponse
from app.services.annotation_query_service import annotation_query_service
from app.services.annotation_rules import get_annotation_config


class AnnotationRoute(APIRoute):
    """Keep dependency/validation failures in the same sanitized JSON envelope."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request):
            try:
                # Reject anonymous requests even before JSON parsing or DB setup.
                provider = getattr(request, "app", None) or self.dependency_overrides_provider
                overrides = getattr(provider, "dependency_overrides", {})
                if get_current_user not in overrides and await security(request) is None:
                    raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
                return await handler(request)
            except RequestValidationError as error:
                return JSONResponse(status_code=422, content=ApiResponse(
                    code=422, message="Invalid annotation request",
                    data={"errors": [
                        {"type": item["type"], "loc": item["loc"], "msg": "Invalid field value"}
                        for item in error.errors()
                    ]},
                ).model_dump(mode="json"))
            except HTTPException as error:
                return JSONResponse(
                    status_code=error.status_code, headers=error.headers,
                    content=ApiResponse(
                        code=error.status_code,
                        message="Authentication required" if error.status_code == 401 else "Access denied",
                    ).model_dump(mode="json"),
                )
            except Exception as error:
                if isinstance(error, SQLAlchemyError):
                    error = ServiceError("mysql", "unavailable")
                elif not isinstance(error, ServiceError):
                    error = ServiceError("application", "unavailable")
                return JSONResponse(status_code=error.status_code, content=ApiResponse(
                    code=error.status_code,
                    message=(
                        "Result set expired; repeat the tag search and import its results again"
                        if error.status_code == 410 else error.message
                    ),
                    data=error.to_dict(),
                ).model_dump(mode="json"))

        return wrapped


router = APIRouter(prefix="/annotations", tags=["annotations"], route_class=AnnotationRoute)


@router.get("/config", response_model=ApiResponse)
async def config(current_user: dict = Depends(get_current_user)):
    return ApiResponse(data=get_annotation_config())


@router.post("/search", response_model=ApiResponse)
async def search(
    request: schema.AnnotationSearchRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return ApiResponse(data=await annotation_query_service.search(session, current_user, request))


@router.get("/media/{media_id}", response_model=ApiResponse)
async def media_detail(
    media_id: schema.Identifier,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return ApiResponse(data=await annotation_query_service.detail(session, current_user, media_id))


@router.get("/runs/{run_id}/frames", response_model=ApiResponse)
async def frames(
    run_id: schema.Identifier,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return ApiResponse(data=await annotation_query_service.frames(
        session, current_user, run_id, page=page, size=size,
    ))


@router.get("/frames/{frame_id}/image", response_class=FileResponse)
async def frame_image(
    frame_id: schema.Identifier,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    path = await annotation_query_service.frame_path(session, current_user, frame_id)
    return FileResponse(path, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/media/{media_id}/preview", response_model=ApiResponse)
async def preview(
    media_id: schema.Identifier,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await annotation_query_service.preview(session, current_user, media_id)
    return JSONResponse(
        content=ApiResponse(data=result).model_dump(mode="json"),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/result-sets", response_model=ApiResponse)
async def create_result_set(
    request: schema.AnnotationResultSetRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return ApiResponse(data=await annotation_query_service.create_result_set(
        session, current_user, request,
    ))


@router.get("/result-sets/{result_set_id}", response_model=ApiResponse)
async def result_set_info(
    result_set_id: schema.Identifier,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    snapshot = await annotation_query_service.result_set(session, current_user, result_set_id)
    return ApiResponse(data=annotation_query_service.result_set_info(snapshot))


async def submit_annotation_job(*, session, user_id, request):
    """Lazy, mockable T4 boundary; missing integration explicitly returns 503."""
    module_name = "app.services.annotation_job_service"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name != module_name:
            raise
        raise ServiceError("application", "unavailable") from None
    return await module.annotation_job_service.submit_job(
        session=session, user_id=user_id, request=request,
    )


@router.post("/jobs", response_model=ApiResponse)
async def jobs(
    request: schema.AnnotationJobRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await annotation_query_service.owned_job_media(session, current_user, request.media_ids)
    result = await submit_annotation_job(session=session, user_id=current_user["id"], request=request)
    return ApiResponse(data=schema.AnnotationJobResponse.model_validate(result))
