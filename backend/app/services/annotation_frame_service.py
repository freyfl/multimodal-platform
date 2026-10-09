"""Private, bounded media preparation. No database or public URL inputs."""

import asyncio
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import math
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile
from typing import Mapping
from uuid import uuid4
import warnings
from weakref import WeakKeyDictionary
from collections.abc import Awaitable, Callable

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.errors import MissingConfigurationError, ServiceError
from app.services.ark_client import strict_json_loads
from app.services.tos_service import borrow_tos
from app.utils.helpers import parse_tos_url


_DECODE_LOCKS = WeakKeyDictionary()
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_FORMATS = "mov,matroska,avi,mpegts,mpeg,mpegvideo"
_TEMP_PREFIX = "annotation-decode-"
ProgressCallback = Callable[[dict], Awaitable[None]]


def _decode_lock():
    loop = asyncio.get_running_loop()
    return _DECODE_LOCKS.setdefault(loop, asyncio.Lock())


async def _progress(callback, stage, planned_frames=None, prepared_frames=0):
    if callback is not None:
        await callback({
            "stage": stage, "planned_frames": planned_frames,
            "prepared_frames": prepared_frames,
        })


def _error(category="invalid_request", status=422):
    return ServiceError("application", category, status_code=status)


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise _error()
    return value


def _field(record, name, default=None):
    return record.get(name, default) if isinstance(record, Mapping) else getattr(record, name, default)


def _root(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise _error()
    return path


def _mkdir(path):
    if path.is_symlink():
        raise _error()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


@dataclass(frozen=True)
class FrameStorageContext:
    """Trusted job context; IDs and owner are checked again before any download.

    revision identifies an immutable media/run version. The caller owns cleanup
    of abandoned persistent versions; temporary startup cleanup never touches it.
    """

    user_id: str
    media_id: str
    revision: str
    storage_dir: Path
    temp_dir: Path
    source_etag: str | None = None
    source_version: str | None = None

    @classmethod
    def from_settings(
        cls, user_id: str, media_id: str, revision: str, *,
        source_etag=None, source_version=None, config=None,
    ):
        config = config if config is not None else settings
        names = ("ANNOTATION_STORAGE_DIR", "ANNOTATION_TEMP_DIR")
        missing = [name for name in names if not getattr(config, name, "")]
        if missing:
            raise MissingConfigurationError("application", missing)
        context = cls(
            user_id, media_id, revision, Path(config.ANNOTATION_STORAGE_DIR),
            Path(config.ANNOTATION_TEMP_DIR), source_etag, source_version,
        )
        context.validate()
        return context

    def validate(self):
        for value in (self.user_id, self.media_id, self.revision):
            _identifier(value)
        storage, temporary = _root(self.storage_dir), _root(self.temp_dir)
        if storage == temporary or storage in temporary.parents or temporary in storage.parents:
            raise _error()
        return storage, temporary


@dataclass(frozen=True)
class PreparedFrame:
    id: str
    frame_index: int
    timestamp_ms: float | None
    width: int
    height: int
    storage_key: str
    path: Path = field(repr=False)


@dataclass(frozen=True)
class PreparedFrames:
    frames: list[PreparedFrame]
    planned_frames: int
    source_etag: str | None
    source_version: str | None
    duration_ms: int | None = None


class AnnotationFrameService:
    def __init__(
        self, *, tos_borrower=borrow_tos, ffmpeg="ffmpeg", ffprobe="ffprobe",
        subprocess_timeout=None, download_timeout=300,
        max_video_bytes=None, max_image_bytes=100 * 1024**2,
        max_duration_seconds=None, max_pixels=None,
        max_frame_long_edge=None, max_frame_short_edge=None,
        max_decode_bytes=1024**3, config=None,
    ):
        config = config if config is not None else settings
        self._borrow_tos = tos_borrower
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.subprocess_timeout = (
            subprocess_timeout if subprocess_timeout is not None
            else getattr(config, "ANNOTATION_DECODE_TIMEOUT", 300)
        )
        self.download_timeout = download_timeout
        self.max_video_bytes = (
            max_video_bytes if max_video_bytes is not None
            else getattr(config, "ANNOTATION_MAX_VIDEO_BYTES", 2 * 1024**3)
        )
        self.max_image_bytes = max_image_bytes
        self.max_duration_seconds = (
            max_duration_seconds if max_duration_seconds is not None
            else getattr(config, "ANNOTATION_MAX_VIDEO_SECONDS", 1800)
        )
        self.max_pixels = (
            max_pixels if max_pixels is not None
            else getattr(config, "ANNOTATION_MAX_FRAME_PIXELS", 7680 * 4320)
        )
        self.max_frame_long_edge = (
            max_frame_long_edge if max_frame_long_edge is not None
            else getattr(config, "ANNOTATION_MAX_FRAME_LONG_EDGE", 7680)
        )
        self.max_frame_short_edge = (
            max_frame_short_edge if max_frame_short_edge is not None
            else getattr(config, "ANNOTATION_MAX_FRAME_SHORT_EDGE", 4320)
        )
        self.max_decode_bytes = max_decode_bytes
        if getattr(config, "ANNOTATION_DECODE_CONCURRENCY", 1) != 1:
            raise ValueError("Annotation decoding requires concurrency 1")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0
            for value in (
                self.subprocess_timeout, self.download_timeout, self.max_video_bytes,
                self.max_image_bytes, self.max_duration_seconds, self.max_pixels,
                self.max_frame_long_edge, self.max_frame_short_edge,
                self.max_decode_bytes,
            )
        ):
            raise ValueError("Annotation limits must be positive finite numbers")

    @staticmethod
    def sample_targets(duration_seconds, interval_seconds=1, max_frames=60):
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(interval_seconds) or not 1 <= interval_seconds <= 60
            or type(max_frames) is not int or not 1 <= max_frames <= 120
            or not math.isfinite(duration_seconds) or duration_seconds <= 0
        ):
            raise _error()
        count = math.ceil(duration_seconds / interval_seconds)
        if count > max_frames:
            return [duration_seconds * index / max_frames for index in range(max_frames)]
        return [index * interval_seconds for index in range(count)]

    @staticmethod
    def resolve_frame_path(context: FrameStorageContext, storage_key: str) -> Path:
        """Resolve only this owner's immutable version. Call after API owner check."""
        storage, _ = context.validate()
        if not isinstance(storage_key, str):
            raise _error()
        parts = storage_key.split("/")
        if (
            len(parts) != 4 or parts[:3] != [context.user_id, context.media_id, context.revision]
            or not re.fullmatch(r"[0-9a-f]{32}\.png", parts[-1])
        ):
            raise _error()
        path = storage.joinpath(*parts)
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise _error()
        if not path.is_file():
            raise _error("not_found", 404)
        return path

    async def cleanup_temporary(self, context: FrameStorageContext) -> int:
        """Startup-only hook. Invoke before accepting jobs, never delete frames."""
        _, temporary = context.validate()
        async with _decode_lock():
            if not temporary.exists():
                return 0
            count = 0
            for path in temporary.glob(_TEMP_PREFIX + "*"):
                if path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
                else:
                    continue
                count += 1
            return count

    async def _download(self, media, user_config, context, destination):
        uri = _field(media, "tos_url")
        parsed = parse_tos_url(uri)
        if (
            _field(media, "user_id") != context.user_id
            or _field(media, "id") != context.media_id
            or not parsed or not parsed["path"]
            or parsed["bucket"] != user_config.get("tos_bucket_name")
        ):
            raise _error("not_found", 404)
        kind = _field(media, "file_type")
        if kind not in {"image", "video"}:
            raise _error()
        limit = self.max_video_bytes if kind == "video" else self.max_image_bytes
        declared = _field(media, "file_size")
        if declared is not None and (type(declared) is not int or not 0 < declared <= limit):
            raise _error()
        try:
            async with asyncio.timeout(self.download_timeout):
                async with self._borrow_tos(user_config) as tos:
                    head = await tos.open_object(uri, method="HEAD")
                    try:
                        metadata = self._headers(head, limit)
                    finally:
                        await head.aclose()
                    size, etag, version = metadata
                    if (
                        context.source_etag is not None and context.source_etag != etag
                        or context.source_version is not None and context.source_version != version
                    ):
                        raise _error("invalid_request", 409)
                    stream = await tos.open_object(uri)
                    try:
                        if self._headers(stream, limit) != metadata:
                            raise _error("invalid_request", 409)
                        count = 0
                        with destination.open("xb") as output:
                            destination.chmod(0o600)
                            async for chunk in stream.aiter_bytes():
                                count += len(chunk)
                                if count > limit or count > size:
                                    raise _error()
                                output.write(chunk)
                        if count != size:
                            raise _error("invalid_response", 502)
                    finally:
                        await stream.aclose()
                    return etag, version
        except TimeoutError:
            raise _error("timeout", 504) from None

    @staticmethod
    def _headers(stream, limit):
        if stream.status_code != 200:
            status = stream.status_code if stream.status_code in {403, 404} else 502
            raise _error("not_found" if status == 404 else "invalid_response", status)
        headers = {key.lower(): value for key, value in stream.headers.items()}
        try:
            size = int(headers["content-length"])
            if not 0 < size <= limit or headers.get("content-encoding", "identity") != "identity":
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise _error() from None
        return size, headers.get("etag"), headers.get("x-tos-version-id")

    def _dimensions(self, width, height, *, video=None):
        # Retain the internal keyword for compatibility; limits are media-agnostic.
        del video
        if (
            type(width) is not int or type(height) is not int
            or min(width, height) < 1 or width * height > self.max_pixels
            or max(width, height) > self.max_frame_long_edge
            or min(width, height) > self.max_frame_short_edge
        ):
            raise _error()

    def _upright_image(self, source):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    self._dimensions(*image.size)
                    upright = ImageOps.exif_transpose(image)
                    return upright.convert("RGB")
        except (Image.DecompressionBombError, Image.DecompressionBombWarning,
                UnidentifiedImageError, OSError, ValueError):
            raise _error() from None

    async def _run_process(self, arguments, *, disk_dir=None):
        """Bound both captured output and runtime; reap the entire process group."""
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except (FileNotFoundError, PermissionError, OSError):
            raise _error("unavailable", 503) from None

        async def read(stream, limit):
            chunks, count = [], 0
            while chunk := await stream.read(65536):
                count += len(chunk)
                if count > limit:
                    raise _error()
                chunks.append(chunk)
            return b"".join(chunks)

        async def disk_guard():
            while True:
                if disk_dir is not None:
                    size = sum(path.stat().st_size for path in disk_dir.glob("*.png"))
                    if size > self.max_decode_bytes:
                        raise _error()
                await asyncio.sleep(0.05)

        readers = [
            asyncio.create_task(read(process.stdout, 64 * 1024**2)),
            asyncio.create_task(read(process.stderr, 2 * 1024**2)),
        ]
        waiter = asyncio.create_task(process.wait())
        guard = asyncio.create_task(disk_guard())
        succeeded = False
        try:
            async with asyncio.timeout(self.subprocess_timeout):
                combined = asyncio.gather(*readers, waiter)
                done, _ = await asyncio.wait({combined, guard}, return_when=asyncio.FIRST_COMPLETED)
                if guard in done:
                    await guard
                stdout, _, code = await combined
                if code != 0:
                    raise _error()
                succeeded = True
                return stdout
        except TimeoutError:
            raise _error("timeout", 504) from None
        finally:
            if not succeeded or process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await asyncio.shield(process.wait())
            for task in (*readers, waiter, guard):
                task.cancel()
            await asyncio.gather(*readers, waiter, guard, return_exceptions=True)
            if "combined" in locals():
                # Retrieve gather failures even on cancellation/disk quota errors.
                await asyncio.gather(combined, return_exceptions=True)

    async def _video_frames(self, source, work, interval_seconds, max_frames, on_progress=None):
        await _progress(on_progress, "probing")
        options = ["-v", "error", "-protocol_whitelist", "file",
                   "-format_whitelist", _FORMATS, "-threads", "1"]
        raw = await self._run_process([
            self.ffprobe, *options, "-select_streams", "v:0", "-show_streams",
            "-show_format", "-of", "json", str(source),
        ])
        try:
            metadata = strict_json_loads(raw)
            stream = metadata["streams"][0]
            width, height = stream["width"], stream["height"]
            self._dimensions(width, height)
            origin = Decimal(metadata["format"].get("start_time", stream.get("start_time", "0")))
            if not origin.is_finite():
                raise ValueError
            # MP4 format.duration may include an absolute timestamp offset.
            # Stream duration is elapsed time; preserve any video delay vs audio.
            if stream.get("duration") is not None:
                start = Decimal(stream.get("start_time", str(origin)))
                if not start.is_finite():
                    raise ValueError
                duration = float(stream["duration"]) + max(0, float(start - origin))
            else:
                duration = float(metadata["format"]["duration"])
            if not math.isfinite(duration) or not 0 < duration <= self.max_duration_seconds:
                raise ValueError
        except (KeyError, IndexError, ValueError, TypeError, InvalidOperation):
            raise _error() from None
        await _progress(on_progress, "decoding")
        raw = await self._run_process([
            self.ffprobe, *options, "-select_streams", "v:0", "-show_frames",
            "-show_entries", "frame=best_effort_timestamp_time,pkt_duration_time,duration_time,width,height",
            "-of", "json", str(source),
        ])
        try:
            decoded = strict_json_loads(raw)["frames"]
            times = []
            for frame in decoded:
                self._dimensions(frame["width"], frame["height"])
                pts = Decimal(frame["best_effort_timestamp_time"]) - origin
                if not pts.is_finite() or pts < 0 or times and pts < times[-1]:
                    raise ValueError
                times.append(pts)
            if not times or times[-1] > Decimal(str(self.max_duration_seconds)):
                raise ValueError
            # B-frame/VFR stream durations may end before the last displayed PTS.
            # Use actual decoded presentation end, not avg_frame_rate or targets.
            last_duration = Decimal(decoded[-1].get(
                "duration_time", decoded[-1].get("pkt_duration_time", "0"),
            ))
            if not last_duration.is_finite() or last_duration < 0:
                raise ValueError
            if last_duration > 0:
                duration = float(times[-1] + last_duration)
            if not 0 < duration <= self.max_duration_seconds or Decimal(str(duration)) <= times[-1]:
                raise ValueError
            targets = self.sample_targets(duration, interval_seconds, max_frames)
        except (KeyError, ValueError, TypeError, InvalidOperation):
            raise _error() from None
        await _progress(on_progress, "decoding", len(targets))
        indices, seen = [], set()
        for target in targets:
            index = max(0, bisect_right(times, Decimal(str(target))) - 1)
            if times[index] not in seen:
                seen.add(times[index])
                indices.append(index)
        selection = "+".join(f"eq(n\\,{index})" for index in indices)
        output = _mkdir(work / "decoded")
        await self._run_process([
            self.ffmpeg, "-nostdin", *options, "-i", str(source),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", f"select={selection}",
            "-vsync", "0", "-frames:v", str(len(indices)), "-threads", "1",
            str(output / "%06d.png"),
        ], disk_dir=output)
        files = sorted(output.glob("*.png"))
        if len(files) != len(indices) or sum(p.stat().st_size for p in files) > self.max_decode_bytes:
            raise _error()
        result = [(path, float(times[index] * 1000)) for index, path in zip(indices, files)]
        return result, len(targets), round(duration * 1000)

    async def prepare_frames(
        self, media, user_config: dict, *, context: FrameStorageContext,
        interval_seconds=1, max_frames=60, on_progress: ProgressCallback | None = None,
    ) -> PreparedFrames:
        """Download an owned TOS object and return private, full-resolution frames.

        No model request occurs here. Source version conflicts are explicit 409s.
        T4 persists returned metadata before beginning paid frame annotation.
        on_progress receives stage/planned_frames/prepared_frames; it must be async.
        Cancel the awaiting asyncio Task to abort downloading/decoding safely.
        """
        storage, temporary = context.validate()
        self.sample_targets(1, interval_seconds, max_frames)
        async with _decode_lock():
            _mkdir(temporary)
            work = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=temporary))
            created = []
            try:
                await _progress(on_progress, "downloading")
                etag, version = await self._download(media, user_config, context, work / "source")
                if _field(media, "file_type") == "video":
                    sources, planned, duration = await self._video_frames(
                        work / "source", work, interval_seconds, max_frames, on_progress,
                    )
                else:
                    sources = [(work / "source", None)]
                    planned, duration = 1, None
                parent = _mkdir(storage)
                for part in (context.user_id, context.media_id, context.revision):
                    parent = _mkdir(parent / part)
                frames = []
                for index, (source, timestamp) in enumerate(sources):
                    await asyncio.sleep(0)
                    identity = uuid4().hex
                    destination = parent / f"{identity}.png"
                    created.append(destination)
                    # Decode one frame at a time, not 120 full 8K images in RAM.
                    with self._upright_image(source) as image:
                        self._dimensions(*image.size)
                        with destination.open("xb") as output:
                            destination.chmod(0o600)
                            image.save(output, format="PNG")
                        frames.append(PreparedFrame(
                            id=identity, frame_index=index, timestamp_ms=timestamp,
                            width=image.width, height=image.height,
                            storage_key=destination.relative_to(storage).as_posix(), path=destination,
                        ))
                    await _progress(on_progress, "persisting", planned, len(frames))
                await _progress(on_progress, "prepared", planned, len(frames))
                return PreparedFrames(frames, planned, etag, version, duration)
            except BaseException:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
            finally:
                shutil.rmtree(work)


annotation_frame_service = AnnotationFrameService()
