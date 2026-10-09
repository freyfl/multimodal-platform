"""
标签管理API路由
处理标签体系查询和标签更新请求
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, delete, select

from app.models import (
    ApiResponse, TagIdentity, TagSystemResponse, TagUpdateRequest, TagItem,
    MediaFile, MediaTag, get_session
)
from app.api.deps import get_current_user
from app.services.tag_service import DEFAULT_TAG_PROMPT, TAG_SYSTEM
from app.utils.logger import logger


router = APIRouter(prefix="/tags", tags=["标签管理"])


@router.get("", response_model=ApiResponse)
async def get_tag_system(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """
    获取标签体系

    返回默认标签和当前用户可见媒体中实际存在的自定义标签
    """
    default_tags = []
    seen_defaults = set()
    for category, names in TAG_SYSTEM.items():
        for name in names:
            identity = (category, name)
            if identity in seen_defaults:
                continue
            seen_defaults.add(identity)
            default_tags.append(
                TagIdentity(source="default", category=category, name=name)
            )
    custom_query = (
        select(MediaTag.category, MediaTag.tag_name)
        .join(
            MediaFile,
            and_(
                MediaFile.id == MediaTag.media_id,
                MediaFile.user_id == MediaTag.user_id,
            ),
        )
        .where(MediaTag.source == "custom")
    )
    if current_user.get("role") != "admin":
        custom_query = custom_query.where(MediaFile.user_id == current_user["id"])
    custom_rows = (
        await session.execute(
            custom_query.distinct().order_by(MediaTag.category, MediaTag.tag_name)
        )
    ).all()
    custom_tags = [
        TagIdentity(source="custom", category=category, name=name)
        for category, name in custom_rows
    ]
    return ApiResponse(data=TagSystemResponse(
        default=default_tags,
        custom=custom_tags,
        default_prompt=DEFAULT_TAG_PROMPT,
    ))


@router.get("/media/{media_id}", response_model=List[TagItem])
async def get_media_tags(
    media_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    获取媒体的标签列表
    """
    # 检查媒体文件是否存在
    query = select(MediaFile).where(MediaFile.id == media_id)
    if current_user.get("role") != "admin":
        query = query.where(MediaFile.user_id == current_user["id"])
    media = await session.scalar(query)
    if not media:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    # 获取标签
    result = await session.execute(
        select(MediaTag).where(
            MediaTag.media_id == media_id,
            MediaTag.user_id == media.user_id,
        )
    )
    tag_list = [
        TagItem(
            source=tag.source,
            category=tag.category,
            tag_name=tag.tag_name,
            confidence=tag.confidence,
            is_manual=tag.is_manual
        )
        for tag in result.scalars().all()
    ]
    return tag_list


@router.put("/media/{media_id}", response_model=ApiResponse)
async def update_media_tags(
    media_id: str,
    request: TagUpdateRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    更新媒体的标签

    支持手动修正标签, 会标记为手动修正
    """
    # 检查媒体文件是否存在
    query = select(MediaFile).where(MediaFile.id == media_id)
    if current_user.get("role") != "admin":
        query = query.where(MediaFile.user_id == current_user["id"])
    media = await session.scalar(query)
    if not media:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    normalized_tags = []
    for tag in request.tags:
        source = tag.get("source")
        category = tag.get("category")
        name = tag.get("name")
        if source not in ("default", "custom"):
            raise HTTPException(status_code=400, detail="无效的标签来源")
        if not isinstance(category, str) or not category.strip():
            raise HTTPException(status_code=400, detail="标签类别不能为空")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=400, detail="标签名称不能为空")
        category, name = category.strip(), name.strip()
        if len(category) > 50:
            raise HTTPException(status_code=400, detail="标签类别长度不能超过50")
        if len(name) > 100:
            raise HTTPException(status_code=400, detail="标签名称长度不能超过100")
        if source == "default" and category not in TAG_SYSTEM:
            raise HTTPException(
                status_code=400,
                detail=f"无效的标签类别: {category}"
            )
        if source == "default" and name not in TAG_SYSTEM.get(category, []):
            raise HTTPException(
                status_code=400,
                detail=f"无效的标签名称: {name}"
            )
        normalized_tags.append({
            "source": source,
            "category": category,
            "name": name,
            "confidence": tag.get("confidence", 1.0),
        })
    # 删除现有标签
    await session.execute(delete(MediaTag).where(
        MediaTag.media_id == media_id, MediaTag.user_id == media.user_id,
    ))
    # 添加新标签
    seen = set()
    for tag in normalized_tags:
        identity = (tag["source"], tag["category"], tag["name"])
        if identity in seen:
            continue
        seen.add(identity)
        media_tag = MediaTag(
            user_id=media.user_id,
            media_id=media_id,
            source=tag["source"],
            category=tag["category"],
            tag_name=tag["name"],
            confidence=tag.get("confidence", 1.0),
            is_manual=1
        )
        session.add(media_tag)
    media.tag_status = "done"
    await session.commit()
    logger.info(f"媒体标签已更新: media_id={media_id}")
    return ApiResponse(message="标签更新成功")


@router.delete("/media/{media_id}/tags/{tag_id}", response_model=ApiResponse)
async def delete_media_tag(
    media_id: str,
    tag_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    删除单个标签
    """
    query = select(MediaTag).where(
        MediaTag.id == tag_id, MediaTag.media_id == media_id,
    )
    if current_user.get("role") != "admin":
        query = query.where(MediaTag.user_id == current_user["id"])
    tag = await session.scalar(query)
    if not tag or tag.media_id != media_id:
        raise HTTPException(status_code=404, detail="标签不存在")
    await session.delete(tag)
    await session.commit()
    logger.info(f"标签已删除: tag_id={tag_id}")
    return ApiResponse(message="标签删除成功")
