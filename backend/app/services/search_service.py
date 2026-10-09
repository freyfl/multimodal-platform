"""MySQL-backed search results with Ark queries and effective TOS previews."""

from collections.abc import Mapping
from urllib.parse import unquote

from sqlalchemy import LargeBinary, and_, cast, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import ServiceError, VectorSpaceMismatchError
from app.api.deps import effective_deployment_settings, effective_user_settings
from app.models.models import MediaFile, MediaTag, UserSystemSettings
from app.services.embedding_service import embedding_service
from app.services.milvus_service import milvus_service
from app.services.tos_service import borrow_tos
from app.utils.helpers import build_tos_url, parse_tos_url
from app.vector_space import cosine_to_similarity


async def _service_call(service, operation):
    try:
        return await operation
    except ServiceError:
        raise
    except Exception:
        raise ServiceError(service, "unavailable") from None


def _preview_uri(tos_url: str, expected_bucket: str) -> str:
    parsed = parse_tos_url(tos_url)
    if parsed is None:
        prefix, separator, remainder = (
            tos_url.removeprefix("tos://").partition("/")
            if isinstance(tos_url, str) and tos_url.startswith("tos://")
            else ("", "", "")
        )
        if not prefix or not separator or not remainder:
            raise ServiceError("tos", "invalid_request", status_code=400)
        try:
            key = unquote(remainder, encoding="utf-8", errors="strict")
        except (UnicodeError, ValueError):
            raise ServiceError("tos", "invalid_request", status_code=400) from None
        parsed = {"bucket": prefix, "path": key}
    if parsed["bucket"] != expected_bucket:
        raise ServiceError("tos", "permission", status_code=403)
    try:
        return build_tos_url(parsed["bucket"], parsed["path"])
    except ValueError:
        raise ServiceError("tos", "invalid_request", status_code=400) from None


def exact_text(column, value: str):
    """Byte-exact identity on both MySQL (BINARY) and SQLite (BLOB).

    The first predicate retains index eligibility; the second excludes case,
    accent and trailing-space aliases under the database's default collation.
    """
    return and_(column == value, cast(column, LargeBinary) == value.encode("utf-8"))


def tag_match_condition(tags: list[dict], logic: str, user_id: str | None):
    """Shared by paginated tag search and immutable annotation snapshots."""
    if logic not in ("AND", "OR"):
        raise ServiceError("application", "invalid_request", status_code=422)
    filters = []
    for tag in tags:
        source, category, name = tag.get("source"), tag.get("category"), tag.get("name")
        if (
            source not in ("default", "custom")
            or not isinstance(category, str) or not category.strip()
            or not isinstance(name, str) or not name.strip()
        ):
            raise ServiceError("application", "invalid_request", status_code=422)
        filters.append(exists().where(
            MediaTag.media_id == MediaFile.id,
            MediaTag.user_id == MediaFile.user_id,
            exact_text(MediaTag.source, source),
            exact_text(MediaTag.category, category),
            exact_text(MediaTag.tag_name, name),
        ))
    condition = (and_(*filters) if logic == "AND" else or_(*filters)) if filters else false()
    if user_id is not None:
        condition = and_(condition, MediaFile.user_id == user_id)
    return condition


class SearchService:
    """Shared cloud clients are owned and closed by the application lifespan."""

    async def _fetch_tags_by_ids(self, session, media_ids, user_id):
        if not media_ids:
            return {}
        query = (
            select(MediaTag)
            .join(
                MediaFile,
                and_(
                    MediaFile.id == MediaTag.media_id,
                    MediaFile.user_id == MediaTag.user_id,
                ),
            )
            .where(MediaTag.media_id.in_(media_ids))
        )
        if user_id is not None:
            query = query.where(MediaTag.user_id == user_id)
        result = await session.execute(query.order_by(MediaTag.id))
        tags_by_id = {}
        for tag in result.scalars():
            tags_by_id.setdefault(tag.media_id, []).append({
                "source": tag.source,
                "category": tag.category,
                "tag_name": tag.tag_name,
                "confidence": tag.confidence,
                "is_manual": bool(tag.is_manual),
            })
        return tags_by_id

    async def _results(self, session, scored_media, user_settings, user_id):
        if not scored_media:
            return []
        tags = await self._fetch_tags_by_ids(
            session, [media.id for media, _ in scored_media], user_id,
        )
        owner_settings = {}
        if user_id is None:
            owner_ids = {media.user_id for media, _ in scored_media if media.user_id}
            if owner_ids:
                rows = (await session.scalars(select(UserSystemSettings).where(
                    UserSystemSettings.user_id.in_(owner_ids),
                ))).all()
                owner_settings = {
                    row.user_id: effective_user_settings({
                        column.name: getattr(row, column.name)
                        for column in UserSystemSettings.__table__.columns
                    })
                    for row in rows
                }
        results = []
        for media, score in scored_media:
            effective = user_settings
            if user_id is None:
                effective = (
                    effective_deployment_settings()
                    if media.user_id is None
                    else owner_settings.get(media.user_id, effective_user_settings())
                )
            async with borrow_tos(effective) as storage:
                preview_uri = _preview_uri(media.tos_url, storage.bucket_name)
                preview = await _service_call(
                    "tos", storage.get_preview_url(
                        preview_uri, expires=settings.TOS_SIGNED_URL_EXPIRES,
                    ),
                )
            results.append({
                "media_id": media.id,
                "tos_url": media.tos_url,
                "preview_url": preview,
                "file_type": media.file_type or "",
                "file_name": media.file_name or "",
                "similarity": score,
                "tags": tags.get(media.id, []),
            })
        return results

    async def search_by_tags(
        self, session: AsyncSession, tags: list[dict], logic: str = "AND",
        page: int = 1, size: int = 20, user_settings: dict | None = None,
        user_id: str | None = None,
    ) -> dict:
        condition = tag_match_condition(tags, logic, user_id)
        total = await session.scalar(
            select(func.count()).select_from(MediaFile).where(condition),
        )
        media = (await session.execute(
            select(MediaFile).where(condition).order_by(MediaFile.id)
            .offset((page - 1) * size).limit(size),
        )).scalars().all()
        results = await self._results(
            session, [(item, 1.0) for item in media], user_settings or {},
            user_id,
        )
        return {"results": results, "total": total, "page": page, "size": size}

    async def _query_space(self, user_settings):
        space = settings.vector_space
        model = user_settings.get("embedding_model", space.model)
        dimension = user_settings.get("embedding_dimension", space.dimension)
        if (
            model != space.model or type(dimension) is not int
            or dimension != space.dimension
        ):
            raise VectorSpaceMismatchError()
        actual = await _service_call(
            "milvus", milvus_service.get_collection_config(),
        )
        if not isinstance(actual, Mapping):
            raise VectorSpaceMismatchError()
        space.assert_compatible(actual)
        return space

    async def _vector_search(
        self, session, query, kind, top_k, threshold, user_settings, user_id,
    ):
        space = await self._query_space(user_settings)
        embed = embedding_service.embed_text if kind == "text" else embedding_service.embed_image
        vector = await _service_call("ark", embed(
            query, model=space.model, dimension=space.dimension,
            api_key=user_settings.get("ark_api_key") or "",
        ))
        vector = space.validate_vector(vector)
        hits = await _service_call("milvus", milvus_service.search(
            query_vector=vector, top_k=top_k, min_score=threshold,
            user_id=user_id,
        ))
        # Validate the service boundary as well as the SDK adapter. Clamp before
        # filtering so negative COSINE values remain predictable at threshold 0.
        scored_hits = []
        try:
            for hit in hits:
                if any(not isinstance(hit[key], str) or not hit[key]
                       for key in ("media_id", "user_id", "tos_url", "file_type")):
                    raise ValueError
                if user_id is not None and hit["user_id"] != user_id:
                    raise ValueError
                score = cosine_to_similarity(hit["score"])
                if score >= threshold:
                    scored_hits.append((hit, score))
        except (KeyError, TypeError, ValueError):
            raise ServiceError("milvus", "invalid_response", status_code=502) from None
        scored_hits.sort(key=lambda item: item[1], reverse=True)
        scored_hits = scored_hits[:top_k]
        if not scored_hits:
            return {"results": [], "total": 0}
        media_query = select(MediaFile).where(
            MediaFile.id.in_([hit["media_id"] for hit, _ in scored_hits]),
        )
        if user_id is not None:
            media_query = media_query.where(MediaFile.user_id == user_id)
        media = (await session.execute(media_query)).scalars().all()
        media_by_id = {item.id: item for item in media}
        scored_media = []
        for hit, score in scored_hits:
            item = media_by_id.get(hit["media_id"])
            if item is None:
                continue
            if (
                item.vector_model != space.model
                or item.vector_dimension != space.dimension
                or item.vector_instruction_version != space.corpus_instruction_version
                or item.vector_collection != space.collection
            ):
                raise VectorSpaceMismatchError()
            if (
                item.user_id != hit["user_id"]
                or item.tos_url != hit["tos_url"]
                or item.file_type != hit["file_type"]
            ):
                raise ServiceError("milvus", "invalid_response", status_code=502)
            scored_media.append((item, score))
        results = await self._results(session, scored_media, user_settings, user_id)
        return {"results": results, "total": len(results)}

    async def search_by_text(
        self, session: AsyncSession, query_text: str, top_k: int = 20,
        user_settings: dict | None = None, user_id: str | None = None,
    ) -> dict:
        return await self._vector_search(
            session, query_text, "text", top_k, settings.TEXT_SEARCH_MIN_SCORE,
            user_settings or {}, user_id,
        )

    async def search_by_image(
        self, session: AsyncSession, image_url: str, top_k: int = 20,
        threshold: float = 0.0, user_settings: dict | None = None,
        user_id: str | None = None,
    ) -> dict:
        return await self._vector_search(
            session, image_url, "image", top_k, threshold, user_settings or {},
            user_id,
        )


search_service = SearchService()
