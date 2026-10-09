"""Global-bucket TOS proxy. User-specific buckets use signed preview URLs."""

from contextlib import AsyncExitStack
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    effective_deployment_settings, effective_user_settings, get_current_user,
    get_user_settings, get_user_settings_row,
)
from app.errors import ServiceError
from app.models.database import get_session
from app.models.models import MediaFile
from app.services.tos_service import borrow_tos
from app.utils.helpers import build_tos_url


router = APIRouter(prefix="/tos", tags=["TOS"])

_CONTENT_HEADERS = {
    "content-type", "content-length", "content-range", "content-encoding",
    "content-disposition", "accept-ranges", "etag", "last-modified",
}


class _ProxyResponse(StreamingResponse):
    def __init__(self, stream, *, resources=None, **kwargs):
        super().__init__(stream.aiter_bytes(), **kwargs)
        self._upstream = stream
        self._resources = resources

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also runs if the ASGI send fails before iteration begins.
            with anyio.CancelScope(shield=True):
                try:
                    await self._upstream.aclose()
                finally:
                    if self._resources is not None:
                        await self._resources.aclose()


@router.get("/{bucket}/{path:path}", operation_id="proxy_tos_object")
async def proxy_tos_file(
    request: Request,
    bucket: str,
    path: str,
    current_user: dict = Depends(get_current_user),
    user_cfg: dict = Depends(get_user_settings),
    session: AsyncSession = Depends(get_session),
):
    try:
        # ASGI path is decoded already. Do not unquote it a second time.
        uri = build_tos_url(bucket, path)
        if not path:
            raise ValueError("Empty key")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid TOS object key") from None
    media_query = select(MediaFile).where(MediaFile.tos_url == uri)
    if current_user.get("role") != "admin":
        media_query = media_query.where(MediaFile.user_id == current_user["id"])
    media = await session.scalar(media_query)
    if media is None:
        raise HTTPException(status_code=404, detail="Media object not found")

    effective = user_cfg
    if current_user.get("role") == "admin":
        if media.user_id is None:
            effective = effective_deployment_settings()
        else:
            owner_row = await get_user_settings_row(session, media.user_id)
            effective = effective_user_settings(owner_row)
    async with AsyncExitStack() as resources:
        try:
            storage = await resources.enter_async_context(borrow_tos(effective))
            if bucket != storage.bucket_name:
                raise HTTPException(status_code=403, detail="TOS bucket access denied")
            upstream = await storage.open_object(
                uri, method=request.method, range_header=request.headers.get("range"),
            )
        except ServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from None
        resources.push_async_callback(upstream.aclose)
        headers = {
            key.lower(): value for key, value in upstream.headers.items()
            if key.lower() in _CONTENT_HEADERS
        }
        headers["cache-control"] = "private, no-store"
        status = upstream.status_code
        if request.method == "HEAD":
            return Response(status_code=status, headers=headers)
        if status not in (200, 206):
            # Do not expose upstream XML bodies or signed redirect locations.
            # Content-Range (notably bytes */size on 416) is retained.
            headers.pop("content-length", None)
            headers.pop("content-encoding", None)
            return Response(status_code=status, headers=headers)
        headers.setdefault("content-type", "application/octet-stream")
        headers.setdefault("accept-ranges", "bytes")
        headers.setdefault(
            "content-disposition",
            f"inline; filename*=UTF-8''{quote(path.rsplit('/', 1)[-1], safe='')}",
        )
        return _ProxyResponse(
            upstream, status_code=status, headers=headers,
            resources=resources.pop_all(),
        )


@router.head("/{bucket}/{path:path}", include_in_schema=False)
async def head_tos_file(
    request: Request,
    bucket: str,
    path: str,
    current_user: dict = Depends(get_current_user),
    user_cfg: dict = Depends(get_user_settings),
    session: AsyncSession = Depends(get_session),
):
    return await proxy_tos_file(
        request, bucket, path, current_user, user_cfg, session,
    )
