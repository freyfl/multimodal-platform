"""Three search entry points sharing effective user configuration."""

import base64
import json
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_user_settings
from app.errors import ServiceError
from app.models import (
    ApiResponse, SearchHistory, SearchResultItem, TagSearchRequest,
    TextSearchRequest, get_session,
)
from app.services.search_service import search_service


router = APIRouter(prefix="/search", tags=["搜索"])
# Ark's officially supported Base64 image input must be smaller than 10 MiB.
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _history_text(value: str) -> str:
    value = re.sub(r"data:[^\s]+", "[redacted media]", value, flags=re.IGNORECASE)
    return re.sub(
        r"https?://[^\s]+",
        lambda match: re.split(r"[?#]", match.group(0), maxsplit=1)[0],
        value, flags=re.IGNORECASE,
    )


def _error_response(error):
    if isinstance(error, SQLAlchemyError):
        error = ServiceError("mysql", "unavailable")
    elif not isinstance(error, ServiceError):
        error = ServiceError("application", "unavailable")
    return JSONResponse(
        status_code=error.status_code,
        content=ApiResponse(
            code=error.status_code, message=error.message, data=error.to_dict(),
        ).model_dump(),
    )


async def _complete(session, result, search_type, history, user_id):
    items = [SearchResultItem(**item) for item in result["results"]]
    session.add(SearchHistory(
        user_id=user_id, search_type=search_type, query_content=history,
        result_count=result["total"],
    ))
    await session.commit()
    data = {"items": items, "total": result["total"]}
    for key in ("page", "size"):
        if key in result:
            data[key] = result[key]
    return ApiResponse(data=data)


@router.post("/tags", response_model=ApiResponse)
async def search_by_tags(
    request: TagSearchRequest,
    current_user: dict = Depends(get_current_user),
    user_settings: dict = Depends(get_user_settings),
    session: AsyncSession = Depends(get_session),
):
    try:
        tags = [tag.model_dump() for tag in request.tags]
        result = await search_service.search_by_tags(
            session=session, tags=tags, logic=request.logic,
            page=request.page, size=request.size, user_settings=user_settings,
            user_id=None if current_user.get("role") == "admin" else current_user["id"],
        )
        history = json.dumps([
            {key: _history_text(tag[key]) for key in ("source", "category", "name")}
            for tag in tags
        ], ensure_ascii=False)
        return await _complete(session, result, "tag", history, current_user["id"])
    except Exception as error:
        await session.rollback()
        return _error_response(error)


@router.post("/text", response_model=ApiResponse)
async def search_by_text(
    request: TextSearchRequest,
    current_user: dict = Depends(get_current_user),
    user_settings: dict = Depends(get_user_settings),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await search_service.search_by_text(
            session=session, query_text=request.query, top_k=request.top_k,
            user_settings=user_settings,
            user_id=None if current_user.get("role") == "admin" else current_user["id"],
        )
        return await _complete(
            session, result, "text", _history_text(request.query), current_user["id"],
        )
    except Exception as error:
        await session.rollback()
        return _error_response(error)


@router.post("/image", response_model=ApiResponse)
async def search_by_image(
    image: UploadFile = File(...),
    threshold: float = Form(0.0, ge=0.0, le=1.0),
    top_k: int = Form(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    user_settings: dict = Depends(get_user_settings),
    session: AsyncSession = Depends(get_session),
):
    try:
        content_type = image.content_type or "image/jpeg"
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="不支持的图片格式")
        image_data = await image.read(MAX_IMAGE_BYTES)
        if not image_data:
            raise HTTPException(status_code=400, detail="图片不能为空")
        if len(image_data) >= MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail="图片文件必须小于10MiB")
        image_url = (
            f"data:{content_type};base64,"
            f"{base64.b64encode(image_data).decode('ascii')}"
        )
        result = await search_service.search_by_image(
            session=session, image_url=image_url, top_k=top_k,
            threshold=threshold, user_settings=user_settings,
            user_id=None if current_user.get("role") == "admin" else current_user["id"],
        )
        # Uploaded filenames are untrusted and may themselves contain signed URLs.
        return await _complete(
            session, result, "image", "uploaded_image", current_user["id"],
        )
    except HTTPException:
        raise
    except Exception as error:
        await session.rollback()
        return _error_response(error)
    finally:
        await image.close()
