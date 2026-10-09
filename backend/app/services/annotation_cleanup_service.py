"""Owner-scoped annotation cleanup, never original media or TOS objects.

Call prepare_* inside the caller's transaction, commit, then reclaim_frames.
Keep the returned resources for retry if filesystem cleanup fails. Never invoke
cleanup while a worker is still writing that media/run; cancel and join it first.
Published runs and active runs cannot be reclaimed individually.
"""

from dataclasses import dataclass
from pathlib import Path
import re

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ServiceError
from app.models.models import (
    AnnotationFrame, AnnotationResultSetMember, AnnotationRun, MediaFile,
)


_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
_FRAME_NAME = re.compile(r"[0-9a-f]{32}\.png")


@dataclass(frozen=True)
class FrameResource:
    user_id: str
    media_id: str
    storage_key: str


def _not_found():
    return ServiceError("application", "not_found", status_code=404)


class AnnotationCleanupService:
    def __init__(self, storage_dir: str | Path):
        # No directory creation or settings/client access during construction.
        self.storage_dir = Path(storage_dir).absolute()

    async def _owned_media(self, session, user_id, media_id):
        media = await session.scalar(
            select(MediaFile).where(
                MediaFile.id == media_id, MediaFile.user_id == user_id,
            ).with_for_update()
        )
        if media is None or not user_id:
            raise _not_found()
        return media

    async def _resources(self, session, user_id, media_id, run_ids):
        keys = (await session.scalars(
            select(AnnotationFrame.storage_key).where(
                AnnotationFrame.user_id == user_id,
                AnnotationFrame.run_id.in_(run_ids),
                AnnotationFrame.storage_key.is_not(None),
            ).distinct()
        )).all()
        return [FrameResource(user_id, media_id, key) for key in keys]

    async def prepare_media_cleanup(
        self, session: AsyncSession, *, user_id: str, media_id: str,
    ) -> list[FrameResource]:
        """Remove only owned annotation rows; caller commits and retains media.

        A future media-deletion workflow may delete the media in the same
        transaction after this method. Other creators' snapshot membership for
        this media is removed too; their snapshots/other media are preserved.
        """
        await self._owned_media(session, user_id, media_id)
        active = await session.scalar(select(AnnotationRun.id).where(
            AnnotationRun.user_id == user_id,
            AnnotationRun.media_id == media_id,
            AnnotationRun.status.in_(("pending", "running")),
        ).limit(1))
        if active is not None:
            raise ServiceError("application", "invalid_request", status_code=409)
        run_ids = select(AnnotationRun.id).where(
            AnnotationRun.user_id == user_id, AnnotationRun.media_id == media_id,
        )
        resources = await self._resources(session, user_id, media_id, run_ids)
        await session.execute(update(MediaFile).where(
            MediaFile.id == media_id, MediaFile.user_id == user_id,
        ).values(published_annotation_run_id=None, annotation_status="not_started"))
        # Explicit deletes also support SQLite callers with foreign_keys disabled.
        await session.execute(delete(AnnotationFrame).where(
            AnnotationFrame.user_id == user_id, AnnotationFrame.run_id.in_(run_ids),
        ))
        await session.execute(delete(AnnotationRun).where(
            AnnotationRun.user_id == user_id, AnnotationRun.media_id == media_id,
        ))
        await session.execute(delete(AnnotationResultSetMember).where(
            AnnotationResultSetMember.media_id == media_id,
        ))
        return resources

    async def prepare_run_cleanup(
        self, session: AsyncSession, *, user_id: str, media_id: str, run_id: str,
    ) -> list[FrameResource]:
        """Reclaim an unpublished terminal version, preserving the published one."""
        media = await self._owned_media(session, user_id, media_id)
        run = await session.scalar(select(AnnotationRun).where(
            AnnotationRun.id == run_id, AnnotationRun.user_id == user_id,
            AnnotationRun.media_id == media_id,
        ).with_for_update())
        if run is None:
            raise _not_found()
        if (
            media.published_annotation_run_id == run_id
            or run.active_key is not None or run.status in {"pending", "running"}
        ):
            raise ServiceError("application", "invalid_request", status_code=409)
        resources = await self._resources(session, user_id, media_id, [run_id])
        await session.execute(delete(AnnotationFrame).where(
            AnnotationFrame.run_id == run_id, AnnotationFrame.user_id == user_id,
        ))
        await session.delete(run)
        await session.flush()
        return resources

    def _resource_path(self, resource: FrameResource) -> Path:
        parts = resource.storage_key.split("/")
        if (
            len(parts) != 4
            or parts[:2] != [resource.user_id, resource.media_id]
            or not all(_IDENTIFIER.fullmatch(part) for part in parts[:3])
            or not _FRAME_NAME.fullmatch(parts[3])
        ):
            raise ServiceError("application", "invalid_request", status_code=422)
        path = self.storage_dir.joinpath(*parts)
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ServiceError("application", "invalid_request", status_code=422)
        return path

    async def reclaim_frames(
        self, session: AsyncSession, resources: list[FrameResource],
    ) -> int:
        """Post-commit, retryable unlink of unreferenced private frame files.

        Start with a clean session/transaction so an uncommitted delete cannot
        cause irreversible loss. Successful-frame references in any run protect
        reused files. Does not recurse, follow symlinks or touch temporary files.
        """
        if session.in_transaction():
            raise RuntimeError("Commit annotation cleanup before reclaiming frame files")
        paths = [(resource, self._resource_path(resource)) for resource in set(resources)]
        removed = 0
        for resource, path in paths:
            reference = await session.scalar(select(AnnotationFrame.id).where(
                AnnotationFrame.storage_key == resource.storage_key,
            ).limit(1))
            if reference is not None:
                continue
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
            # Only remove empty version/media directories, never another subtree.
            for parent in (path.parent, path.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break
        return removed
