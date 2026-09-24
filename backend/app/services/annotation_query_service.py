"""Owner-scoped annotation reads and immutable tag-result membership.

No model calls. Read access is global for admins; job submission is owner-only.
All timestamps in storage are naive UTC; wire timestamps are explicitly UTC.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.api.deps import effective_user_settings, get_user_settings_row
from app.config import settings
from app.errors import MissingConfigurationError, ServiceError
from app.models import annotation_schemas as schema
from app.models.models import (
    AnnotationFrame, AnnotationResultSet, AnnotationResultSetMember,
    AnnotationRun, MediaFile,
)
from app.services.annotation_frame_service import AnnotationFrameService, FrameStorageContext
from app.services.annotation_rules import parse_filenames
from app.services.search_service import _preview_uri, exact_text, tag_match_condition
from app.services.tos_service import borrow_tos


class ResultSetTooLarge(ServiceError):
    def __init__(self):
        super().__init__("application", "invalid_request", status_code=422)
        self.message = "More than 10000 media match; narrow the tag search before importing"


def _now():
    return datetime.now(timezone.utc)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _not_found():
    return ServiceError("application", "not_found", status_code=404)


def _scope(user):
    return None if user.get("role") == "admin" else user["id"]


def _progress(run):
    return schema.AnnotationProgress(**{
        key: getattr(run, key) for key in schema.AnnotationProgress.model_fields
    }) if run else schema.AnnotationProgress()


def _public_error(value):
    # Persistence stores sanitized errors, but never expose arbitrary legacy text.
    return "Annotation processing failed; retry or contact the administrator." if value else None


def _summary(run):
    if run is None:
        return None
    public_snapshot_fields = (
        "annotation_mode", "annotation_box_mode", "template_version", "model",
        "annotation_sample_interval_seconds", "annotation_max_frames",
    )
    return schema.AnnotationRunSummary(
        id=run.id, user_id=run.user_id, media_id=run.media_id,
        task_id=run.task_id, revision=run.revision, status=run.status,
        **{key: run.snapshot[key] for key in public_snapshot_fields},
        progress=_progress(run), model_elapsed_ms=run.model_elapsed_ms,
        error=_public_error(run.error), created_at=_utc(run.created_at),
        updated_at=_utc(run.updated_at), completed_at=_utc(run.completed_at),
    )


def _published(media, by_id):
    run = by_id.get(media.published_annotation_run_id)
    return run if run and (run.media_id, run.user_id) == (media.id, media.user_id) else None


class AnnotationQueryService:
    async def media(self, session, user, media_id, *, owner_only=False):
        query = select(MediaFile).where(MediaFile.id == media_id)
        if owner_only or _scope(user) is not None:
            query = query.where(MediaFile.user_id == user["id"])
        media = await session.scalar(query)
        if media is None:
            raise _not_found()
        return media

    async def owned_job_media(self, session, user, media_ids):
        """Check the entire batch before invoking the paid T4 boundary."""
        rows = (await session.scalars(select(MediaFile).where(
            MediaFile.id.in_(media_ids), MediaFile.user_id == user["id"],
        ))).all()
        by_id = {row.id: row for row in rows}
        if any(media_id not in by_id for media_id in media_ids):
            raise _not_found()
        return [by_id[media_id] for media_id in media_ids]

    async def _runs(self, session, media):
        if not media:
            return {}, {}
        newer = aliased(AnnotationRun)
        is_latest = ~exists().where(
            newer.user_id == AnnotationRun.user_id,
            newer.media_id == AnnotationRun.media_id,
            newer.revision > AnnotationRun.revision,
        )
        rows = (await session.scalars(
            select(AnnotationRun).join(MediaFile, and_(
                MediaFile.id == AnnotationRun.media_id,
                MediaFile.user_id == AnnotationRun.user_id,
            )).where(
                MediaFile.id.in_([item.id for item in media]),
                or_(is_latest, AnnotationRun.id == MediaFile.published_annotation_run_id),
            )
        )).all()
        by_id = {run.id: run for run in rows}
        latest = {}
        for run in rows:
            previous = latest.get(run.media_id)
            if previous is None or run.revision > previous.revision:
                latest[run.media_id] = run
        return by_id, latest

    async def _items(self, session, user, media):
        by_id, latest = await self._runs(session, media)
        # Match the initially displayed version: published, or latest partial.
        display = {
            item.id: _published(item, by_id) or latest.get(item.id)
            for item in media
        }
        run_ids = [run.id for run in display.values() if run is not None]
        counts = {}
        if run_ids:
            length = (
                func.json_array_length(AnnotationFrame.objects)
                if session.get_bind().dialect.name == "sqlite"
                else func.json_length(AnnotationFrame.objects)
            )
            rows = await session.execute(
                select(AnnotationFrame.run_id, func.sum(length))
                .join(AnnotationRun, and_(
                    AnnotationRun.id == AnnotationFrame.run_id,
                    AnnotationRun.user_id == AnnotationFrame.user_id,
                )).where(
                    AnnotationFrame.run_id.in_(run_ids),
                    AnnotationFrame.status == "completed",
                ).group_by(AnnotationFrame.run_id)
            )
            counts = dict(rows.all())
        results = []
        for item in media:
            last, shown = latest.get(item.id), display[item.id]
            results.append(schema.AnnotationMediaItem(
                media_id=item.id, user_id=item.user_id if _scope(user) is None else None,
                file_name=item.file_name or "", tos_url=item.tos_url,
                file_type=item.file_type, status=item.annotation_status,
                published_run_id=(
                    item.published_annotation_run_id
                    if _published(item, by_id) else None
                ),
                latest_run_id=last.id if last else None,
                object_count=int(counts.get(shown.id, 0) or 0) if shown else 0,
                progress=_progress(last),
                annotation_mode=shown.snapshot["annotation_mode"] if shown else None,
                created_at=_utc(item.created_at), updated_at=_utc(item.updated_at),
            ))
        return results, by_id, latest

    async def search(self, session, user, request: schema.AnnotationSearchRequest):
        names = parse_filenames(request.filenames)
        conditions = []
        if _scope(user) is not None:
            conditions.append(MediaFile.user_id == user["id"])
        if request.result_set_id is not None:
            snapshot = await self.result_set(session, user, request.result_set_id)
            conditions.append(exists().where(
                AnnotationResultSetMember.snapshot_id == snapshot.id,
                AnnotationResultSetMember.user_id == snapshot.user_id,
                AnnotationResultSetMember.media_id == MediaFile.id,
            ))
        if names:
            conditions.append(or_(*(exact_text(MediaFile.file_name, name) for name in names)))
        if request.file_type is not None:
            conditions.append(MediaFile.file_type == request.file_type)
        if request.status is not None:
            conditions.append(MediaFile.annotation_status == request.status)
        total = await session.scalar(select(func.count()).select_from(MediaFile).where(*conditions))
        media = (await session.scalars(
            select(MediaFile).where(*conditions)
            .order_by(MediaFile.created_at.desc(), MediaFile.id.desc())
            .offset((request.page - 1) * request.size).limit(request.size)
        )).all()
        results, _, _ = await self._items(session, user, media)
        return schema.AnnotationSearchResponse(
            results=results, total=total, page=request.page, size=request.size,
        )

    async def detail(self, session, user, media_id):
        media = await self.media(session, user, media_id)
        items, by_id, latest = await self._items(session, user, [media])
        return schema.AnnotationMediaDetail(
            media=items[0], published_run=_summary(_published(media, by_id)),
            latest_run=_summary(latest.get(media.id)),
        )

    async def run(self, session, user, run_id):
        query = select(AnnotationRun).join(MediaFile, and_(
            MediaFile.id == AnnotationRun.media_id,
            MediaFile.user_id == AnnotationRun.user_id,
        )).where(AnnotationRun.id == run_id)
        if _scope(user) is not None:
            query = query.where(MediaFile.user_id == user["id"])
        run = await session.scalar(query)
        if run is None:
            raise _not_found()
        return run

    async def frames(self, session, user, run_id, page=1, size=20):
        run = await self.run(session, user, run_id)
        conditions = (AnnotationFrame.run_id == run.id, AnnotationFrame.user_id == run.user_id)
        total = await session.scalar(select(func.count()).select_from(AnnotationFrame).where(*conditions))
        frames = (await session.scalars(
            select(AnnotationFrame).where(*conditions)
            .order_by(AnnotationFrame.frame_index, AnnotationFrame.id)
            .offset((page - 1) * size).limit(size)
        )).all()
        return schema.AnnotationFramesResponse(
            results=[schema.AnnotationFrame(
                id=frame.id, user_id=frame.user_id, run_id=frame.run_id,
                frame_index=frame.frame_index, timestamp_ms=frame.timestamp_ms,
                width=frame.width, height=frame.height, status=frame.status,
                objects=frame.objects if frame.status == "completed" else [],
                error=_public_error(frame.error),
            ) for frame in frames],
            total=total, page=page, size=size,
        )

    async def frame_path(self, session, user, frame_id):
        query = select(AnnotationFrame, AnnotationRun).join(AnnotationRun, and_(
            AnnotationRun.id == AnnotationFrame.run_id,
            AnnotationRun.user_id == AnnotationFrame.user_id,
        )).join(MediaFile, and_(
            MediaFile.id == AnnotationRun.media_id,
            MediaFile.user_id == AnnotationRun.user_id,
        )).where(AnnotationFrame.id == frame_id)
        if _scope(user) is not None:
            query = query.where(MediaFile.user_id == user["id"])
        row = (await session.execute(query)).first()
        if row is None or not row[0].storage_key:
            raise _not_found()
        frame, run = row
        parts = frame.storage_key.split("/")
        if len(parts) != 4:
            raise _not_found()
        # The persisted storage version may precede this run when frames are reused.
        try:
            context = FrameStorageContext.from_settings(
                run.user_id, run.media_id, parts[2], config=settings,
            )
            return AnnotationFrameService.resolve_frame_path(context, frame.storage_key)
        except MissingConfigurationError:
            raise
        except (ServiceError, OSError):
            raise _not_found() from None

    async def preview(self, session, user, media_id):
        media = await self.media(session, user, media_id)
        if not media.user_id:
            raise MissingConfigurationError("tos", ["MEDIA_OWNER"])
        config = effective_user_settings(await get_user_settings_row(session, media.user_id))
        async with borrow_tos(config) as storage:
            uri = _preview_uri(media.tos_url, storage.bucket_name)
            now = _now()
            try:
                url = await storage.get_preview_url(uri, expires=settings.TOS_SIGNED_URL_EXPIRES)
            except ServiceError:
                raise
            except Exception:
                raise ServiceError("tos", "unavailable") from None
        return schema.AnnotationPreviewResponse(
            media_id=media.id, preview_url=url,
            expires_at=now + timedelta(seconds=settings.TOS_SIGNED_URL_EXPIRES),
        )

    async def create_result_set(self, session, user, request: schema.AnnotationResultSetRequest):
        condition = tag_match_condition(
            [tag.model_dump() for tag in request.tags], request.logic, _scope(user),
        )
        # One bounded SELECT freezes all IDs; never iterate changing live pages.
        ids = (await session.scalars(
            select(MediaFile.id).where(condition)
            .order_by(MediaFile.created_at.desc(), MediaFile.id.desc()).limit(10001)
        )).all()
        if len(ids) > 10000:
            raise ResultSetTooLarge()
        now = _now().replace(tzinfo=None)
        snapshot = AnnotationResultSet(
            id=str(uuid4()), user_id=user["id"], source=request.model_dump(mode="json"),
            total=len(ids), created_at=now, expires_at=now + timedelta(hours=24),
        )
        session.add(snapshot)
        await session.flush()
        session.add_all([
            AnnotationResultSetMember(snapshot_id=snapshot.id, media_id=media_id, user_id=user["id"])
            for media_id in ids
        ])
        await session.flush()
        response = self.result_set_info(snapshot)
        await session.commit()
        return response

    async def result_set(self, session, user, snapshot_id):
        query = select(AnnotationResultSet).where(AnnotationResultSet.id == snapshot_id)
        if _scope(user) is not None:
            query = query.where(AnnotationResultSet.user_id == user["id"])
        snapshot = await session.scalar(query)
        if snapshot is None:
            raise _not_found()
        if _utc(snapshot.expires_at) <= _now():
            raise ServiceError("application", "not_found", status_code=410)
        return snapshot

    @staticmethod
    def result_set_info(snapshot):
        return schema.AnnotationResultSetResponse(
            result_set_id=snapshot.id, total=snapshot.total, source=snapshot.source,
            created_at=_utc(snapshot.created_at), expires_at=_utc(snapshot.expires_at),
        )


annotation_query_service = AnnotationQueryService()
