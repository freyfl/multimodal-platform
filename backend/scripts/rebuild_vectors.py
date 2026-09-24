"""Rebuild legacy media vectors using TOS -> Ark -> Milvus -> MySQL ordering."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import and_, create_engine, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.errors import ServiceError
from app.api.deps import effective_user_settings
from app.models.models import MediaFile, UserSystemSettings
from app.services.embedding_service import embedding_service
from app.services.milvus_service import milvus_service
from app.services.tos_service import borrow_tos, close_tos_services
from app.vector_space import VectorSpace


@dataclass
class RebuildReport:
    limit: int | None
    after_id: str | None
    failed_only: bool
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    remaining: int = 0
    completed_for_space: int = 0
    milvus_vector_count: int = 0
    count_matches_mysql: bool = False
    last_media_id: str | None = None
    failures: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "after_id": self.after_id,
            "failed_only": self.failed_only,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "remaining": self.remaining,
            "completed_for_space": self.completed_for_space,
            "milvus_vector_count": self.milvus_vector_count,
            "count_matches_mysql": self.count_matches_mysql,
            "last_media_id": self.last_media_id,
            "failures": list(self.failures),
        }


def vector_is_current(media: MediaFile, space: VectorSpace) -> bool:
    return (
        media.vector_status == "done"
        and media.vector_id == media.id
        and media.vector_model == space.model
        and media.vector_dimension == space.dimension
        and media.vector_instruction_version == space.corpus_instruction_version
        and media.vector_collection == space.collection
    )


def _stale_filter(space: VectorSpace):
    return or_(
        MediaFile.vector_status != "done",
        MediaFile.vector_status.is_(None),
        MediaFile.vector_id != MediaFile.id,
        MediaFile.vector_id.is_(None),
        MediaFile.vector_model != space.model,
        MediaFile.vector_model.is_(None),
        MediaFile.vector_dimension != space.dimension,
        MediaFile.vector_dimension.is_(None),
        MediaFile.vector_instruction_version != space.corpus_instruction_version,
        MediaFile.vector_instruction_version.is_(None),
        MediaFile.vector_collection != space.collection,
        MediaFile.vector_collection.is_(None),
    )


def _safe_failure(error: BaseException) -> str:
    if isinstance(error, ServiceError):
        return f"{error.service}:{error.category}"
    return "internal:failed"


class VectorRebuilder:
    def __init__(
        self,
        session_factory,
        *,
        tos=None,
        embedding=embedding_service,
        milvus=milvus_service,
        space: VectorSpace | None = None,
    ):
        self._session_factory = session_factory
        self._tos = tos
        self._embedding = embedding
        self._milvus = milvus
        self._space = space or settings.vector_space

    def _candidate_ids(
        self,
        *,
        limit: int | None,
        after_id: str | None,
        failed_only: bool,
    ) -> list[str]:
        criteria = [MediaFile.user_id.is_not(None)]
        if after_id:
            criteria.append(MediaFile.id > after_id)
        if failed_only:
            criteria.append(MediaFile.vector_status == "failed")
        else:
            criteria.append(_stale_filter(self._space))
        statement = select(MediaFile.id).where(and_(*criteria)).order_by(MediaFile.id)
        if limit is not None:
            statement = statement.limit(limit)
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def _media_snapshot(self, media_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            media = session.get(MediaFile, media_id)
            if media is None:
                return None
            saved = session.scalar(select(UserSystemSettings).where(
                UserSystemSettings.user_id == media.user_id,
            ))
            saved_values = None if saved is None else {
                column.name: getattr(saved, column.name)
                for column in UserSystemSettings.__table__.columns
            }
            return {
                "id": media.id,
                "user_id": media.user_id,
                "tos_url": media.tos_url,
                "file_type": media.file_type,
                "settings": effective_user_settings(saved_values),
            }

    def _has_ownerless_candidates(self, failed_only: bool) -> bool:
        stale = (
            MediaFile.vector_status == "failed"
            if failed_only else _stale_filter(self._space)
        )
        with self._session_factory() as session:
            return bool(session.scalar(
                select(func.count()).select_from(MediaFile).where(
                    MediaFile.user_id.is_(None), stale,
                )
            ))

    def _mark_success(self, media_id: str, vector_id: str) -> None:
        with self._session_factory() as session:
            media = session.get(MediaFile, media_id)
            if media is None:
                raise RuntimeError("media disappeared during rebuild")
            media.vector_status = "done"
            media.vector_id = vector_id
            media.vector_model = self._space.model
            media.vector_dimension = self._space.dimension
            media.vector_instruction_version = self._space.corpus_instruction_version
            media.vector_collection = self._space.collection
            session.commit()

    def _mark_failed(self, media_id: str) -> None:
        with self._session_factory() as session:
            media = session.get(MediaFile, media_id)
            if media is not None:
                media.vector_status = "failed"
                session.commit()

    def _counts(self) -> tuple[int, int]:
        with self._session_factory() as session:
            remaining = session.scalar(
                select(func.count()).select_from(MediaFile).where(
                    MediaFile.user_id.is_not(None), _stale_filter(self._space),
                )
            )
            completed = session.scalar(
                select(func.count()).select_from(MediaFile).where(
                    MediaFile.user_id.is_not(None),
                    MediaFile.vector_status == "done",
                    MediaFile.vector_id == MediaFile.id,
                    MediaFile.vector_model == self._space.model,
                    MediaFile.vector_dimension == self._space.dimension,
                    MediaFile.vector_instruction_version
                    == self._space.corpus_instruction_version,
                    MediaFile.vector_collection == self._space.collection,
                )
            )
        return int(remaining or 0), int(completed or 0)

    async def run(
        self,
        *,
        limit: int | None = None,
        after_id: str | None = None,
        failed_only: bool = False,
    ) -> dict[str, Any]:
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("limit must be a positive integer")
        if self._has_ownerless_candidates(failed_only):
            raise ServiceError("application", "invalid_request", status_code=409)
        actual = await self._milvus.get_collection_config()
        self._space.assert_compatible(actual)
        report = RebuildReport(limit, after_id, failed_only)
        for media_id in self._candidate_ids(
            limit=limit, after_id=after_id, failed_only=failed_only
        ):
            report.attempted += 1
            report.last_media_id = media_id
            media = self._media_snapshot(media_id)
            if media is None:
                continue
            try:
                # MySQL completion state changes only after all three remote steps
                # have succeeded. A retry uses the same stable Milvus primary key.
                if self._tos is not None:
                    signed_url = await self._tos.get_file_url(media["tos_url"])
                else:
                    async with borrow_tos(media["settings"]) as tos:
                        signed_url = await tos.get_file_url(media["tos_url"])
                vector = await self._embedding.embed_media(
                    media["tos_url"],
                    signed_url,
                    model=self._space.model,
                    dimension=self._space.dimension,
                    api_key=media["settings"].get("ark_api_key") or "",
                )
                vector_id = await self._milvus.upsert(
                    media_id=media["id"],
                    user_id=media["user_id"],
                    tos_url=media["tos_url"],
                    file_type=media["file_type"],
                    embedding=vector,
                )
                if vector_id != media["id"]:
                    raise ServiceError("milvus", "invalid_response", status_code=502)
                self._mark_success(media_id, vector_id)
                report.succeeded += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._mark_failed(media_id)
                report.failed += 1
                report.failures.append(
                    {"media_id": media_id, "error": _safe_failure(error)}
                )
        report.remaining, report.completed_for_space = self._counts()
        report.milvus_vector_count = await self._milvus.get_vector_count()
        report.count_matches_mysql = (
            report.milvus_vector_count == report.completed_for_space
        )
        return report.to_dict()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild media vectors into Milvus")
    parser.add_argument("--limit", type=int, help="maximum stale rows attempted this run")
    parser.add_argument("--after-id", help="exclusive stable UUID cursor")
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="retry rows whose last vector rebuild failed",
    )
    return parser


async def _run_cli(args) -> dict[str, Any]:
    settings.require_config("mysql")
    engine = create_engine(
        settings.mysql_sync_url,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        try:
            return await VectorRebuilder(factory).run(
                limit=args.limit,
                after_id=args.after_id,
                failed_only=args.failed_only,
            )
        finally:
            await asyncio.gather(
                close_tos_services(),
                embedding_service.aclose(),
                milvus_service.aclose(),
                return_exceptions=True,
            )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run_cli(args))
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0 if not result["failed"] and result["count_matches_mysql"] else 2
    except Exception:
        print(json.dumps({"status": "failed", "error": "vector_rebuild_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
