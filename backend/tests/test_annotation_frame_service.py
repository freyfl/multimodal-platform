import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image, ImageChops, ImageOps
import pytest

from app.errors import ServiceError
from app.services.annotation_frame_service import AnnotationFrameService, FrameStorageContext


@pytest.fixture
def storage(tmp_path):
    return FrameStorageContext("owner", "media", "revision", tmp_path / "private", tmp_path / "temp")


@pytest.fixture
def media():
    return {"id": "media", "user_id": "owner", "tos_url": "tos://bucket/image.jpg", "file_type": "image"}


@pytest.fixture
def user_config():
    return {"tos_bucket_name": "bucket"}


class ObjectStream:
    def __init__(self, data, *, headers=None, chunks=None):
        self.data = data
        self.status_code = 200
        self.headers = headers or {"content-length": str(len(data)), "etag": '"v1"', "x-tos-version-id": "1"}
        self.chunks = chunks
        self.closed = False

    async def aiter_bytes(self):
        for chunk in self.chunks if self.chunks is not None else [self.data]:
            yield chunk

    async def aclose(self):
        self.closed = True


def service_for(data, **kwargs):
    streams = []
    calls = []

    class TOS:
        async def open_object(self, uri, *, method="GET"):
            calls.append((uri, method))
            stream = ObjectStream(data)
            streams.append(stream)
            return stream

    @asynccontextmanager
    async def borrow(config):
        yield TOS()

    service = AnnotationFrameService(tos_borrower=borrow, **kwargs)
    service.streams = streams
    service.calls = calls
    return service


def jpeg(orientation=1, size=(80, 40)):
    image = Image.new("RGB", size, "red")
    image.paste("blue", (0, 0, size[0] // 2, size[1] // 2))
    exif = Image.Exif()
    exif[274] = orientation
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


@pytest.mark.parametrize("orientation,size", [(1, (80, 40)), (6, (40, 80)), (8, (40, 80)), (3, (80, 40))])
async def test_exact_upright_image_persists_separately(storage, media, user_config, orientation, size):
    data = jpeg(orientation)
    service = service_for(data)
    result = await service.prepare_frames(media, user_config, context=storage)
    frame = result.frames[0]
    assert (frame.width, frame.height) == size
    assert frame.timestamp_ms is None
    assert result.planned_frames == 1
    assert (result.source_etag, result.source_version) == ('"v1"', "1")
    assert service.calls == [(media["tos_url"], "HEAD"), (media["tos_url"], "GET")]
    assert all(stream.closed for stream in service.streams)
    assert not list(storage.temp_dir.iterdir())
    assert stat.S_IMODE(frame.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(frame.path.parent.stat().st_mode) == 0o700
    with Image.open(BytesIO(data)) as original, Image.open(frame.path) as saved:
        assert saved.getexif().get(274) is None
        assert ImageChops.difference(ImageOps.exif_transpose(original).convert("RGB"), saved).getbbox() is None
    assert service.resolve_frame_path(storage, frame.storage_key) == frame.path


@pytest.mark.parametrize("change", [
    {"user_id": "other"}, {"id": "other"}, {"tos_url": "https://host.invalid/image.jpg"},
    {"tos_url": "file:///etc/passwd"}, {"tos_url": "tos://another/image.jpg"},
])
async def test_only_owned_tos_objects(storage, media, user_config, change):
    service = service_for(jpeg())
    with pytest.raises(ServiceError) as error:
        await service.prepare_frames({**media, **change}, user_config, context=storage)
    assert error.value.status_code == 404
    assert service.calls == []
    assert not list(storage.temp_dir.iterdir())


@pytest.mark.parametrize("source_field", ["source_etag", "source_version"])
async def test_source_snapshot_conflict_before_get(storage, media, user_config, source_field):
    service = service_for(jpeg())
    with pytest.raises(ServiceError) as error:
        await service.prepare_frames(media, user_config, context=replace(storage, **{source_field: "stale"}))
    assert error.value.status_code == 409
    assert len(service.calls) == 1
    assert service.streams[0].closed


async def test_source_changes_between_head_and_get(storage, media, user_config):
    head = ObjectStream(jpeg())
    get = ObjectStream(jpeg())
    get.headers["etag"] = '"changed"'

    @asynccontextmanager
    async def borrow(config):
        yield type("TOS", (), {"open_object": AsyncMock(side_effect=[head, get])})()

    with pytest.raises(ServiceError) as error:
        await AnnotationFrameService(tos_borrower=borrow).prepare_frames(media, user_config, context=storage)
    assert error.value.status_code == 409
    assert head.closed and get.closed


async def test_stream_cannot_exceed_declared_or_configured_size(storage, media, user_config):
    data = jpeg()
    stream = ObjectStream(data, chunks=[data, b"overflow"])

    @asynccontextmanager
    async def borrow(config):
        yield type("TOS", (), {"open_object": AsyncMock(return_value=stream)})()

    with pytest.raises(ServiceError):
        await AnnotationFrameService(tos_borrower=borrow).prepare_frames(media, user_config, context=storage)
    assert stream.closed
    assert not list(storage.temp_dir.iterdir())


@pytest.mark.parametrize("kwargs", [{"max_image_bytes": 10}, {"max_pixels": 100}])
async def test_byte_and_pixel_caps(storage, media, user_config, kwargs):
    with pytest.raises(ServiceError):
        await service_for(jpeg(), **kwargs).prepare_frames(media, user_config, context=storage)
    assert not list(storage.temp_dir.iterdir())
    assert not list(storage.storage_dir.rglob("*.png"))


async def test_pillow_bomb_warning_is_failure(storage, media, user_config, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2000)
    with pytest.raises(ServiceError):
        await service_for(jpeg()).prepare_frames(media, user_config, context=storage)


async def test_corrupt_image_cleanup(storage, media, user_config):
    with pytest.raises(ServiceError):
        await service_for(b"not an image").prepare_frames(media, user_config, context=storage)
    assert not list(storage.temp_dir.iterdir())


@pytest.mark.parametrize("duration,expected,last", [(0.1, 1, 0), (60, 60, 59), (120, 60, 118), (1800, 60, 1770)])
def test_whole_video_sampling(duration, expected, last):
    targets = AnnotationFrameService.sample_targets(duration)
    assert len(targets) == expected and targets[0] == 0 and targets[-1] == last
    assert targets[-1] < duration


@pytest.mark.parametrize("interval,maximum", [(0, 60), (61, 60), (True, 60), (float("nan"), 60), (1, 121), (1, True)])
def test_sampling_limits(interval, maximum):
    with pytest.raises(ServiceError):
        AnnotationFrameService.sample_targets(60, interval, maximum)


@pytest.mark.parametrize("size", [(11, 1), (1, 11), (9, 6), (6, 9)])
def test_configured_frame_edges_apply_to_every_orientation(size):
    config = SimpleNamespace(
        ANNOTATION_MAX_FRAME_PIXELS=1000,
        ANNOTATION_MAX_FRAME_LONG_EDGE=10,
        ANNOTATION_MAX_FRAME_SHORT_EDGE=5,
        ANNOTATION_DECODE_CONCURRENCY=1,
    )
    service = AnnotationFrameService(config=config)
    with pytest.raises(ServiceError):
        service._dimensions(*size)


def test_configured_frame_edges_accept_boundary_in_every_orientation():
    service = AnnotationFrameService(
        max_pixels=1000, max_frame_long_edge=10, max_frame_short_edge=5,
    )
    service._dimensions(10, 5)
    service._dimensions(5, 10)


@pytest.mark.parametrize("revision", ["../other", ".", "/absolute", "a/b", "a\\b"])
async def test_context_path_traversal(storage, media, user_config, revision):
    with pytest.raises(ServiceError):
        await service_for(jpeg()).prepare_frames(media, user_config, context=replace(storage, revision=revision))


async def test_private_path_owner_symlink_and_restart_cleanup(storage, media, user_config, tmp_path):
    service = service_for(jpeg())
    frame = (await service.prepare_frames(media, user_config, context=storage)).frames[0]
    with pytest.raises(ServiceError):
        service.resolve_frame_path(replace(storage, user_id="other"), frame.storage_key)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    (storage.temp_dir / "annotation-decode-orphan").mkdir()
    (storage.temp_dir / "annotation-decode-link").symlink_to(outside, target_is_directory=True)
    (storage.temp_dir / "unrelated").mkdir()
    assert await service.cleanup_temporary(storage) == 2
    assert frame.path.exists() and (outside / "keep").exists()
    assert (storage.temp_dir / "unrelated").exists()
    frame.path.unlink()
    frame.path.symlink_to(outside / "keep")
    with pytest.raises(ServiceError):
        service.resolve_frame_path(storage, frame.storage_key)


async def test_overlapping_roots_rejected(storage, media, user_config):
    with pytest.raises(ServiceError):
        await service_for(jpeg()).prepare_frames(
            media, user_config, context=replace(storage, temp_dir=storage.storage_dir / "tmp"),
        )


@pytest.mark.parametrize("cancel", [False, True])
async def test_real_subprocess_timeout_and_cancel_reap_child(monkeypatch, cancel):
    service = AnnotationFrameService(subprocess_timeout=0.1 if not cancel else 30)
    original = asyncio.create_subprocess_exec
    created = asyncio.Event()
    processes = []

    async def launch(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        created.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    task = asyncio.create_task(service._run_process([sys.executable, "-c", "import time; time.sleep(60)"]))
    await created.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ServiceError) as error:
            await task
        assert error.value.category == "timeout"
    assert processes[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


async def test_decode_concurrency_one_across_instances(storage, media, user_config, monkeypatch):
    active = peak = 0
    original = AnnotationFrameService._download

    async def download(self, *args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.02)
            return await original(self, *args)
        finally:
            active -= 1

    monkeypatch.setattr(AnnotationFrameService, "_download", download)
    await asyncio.gather(*[
        service_for(jpeg()).prepare_frames(media, user_config, context=replace(storage, revision=f"r{i}"))
        for i in range(3)
    ])
    assert peak == 1


@pytest.fixture
def video_tools():
    root = Path(__file__).resolve().parents[2] / ".tools" / "ffmpeg"
    ffmpeg = shutil.which("ffmpeg") or str(root / "ffmpeg")
    ffprobe = shutil.which("ffprobe") or str(root / "ffprobe")
    if not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
        pytest.skip("Real FFmpeg and FFprobe are not installed")
    return ffmpeg, ffprobe


def run_video(arguments):
    subprocess.run(arguments, check=True, capture_output=True, timeout=30)


@pytest.mark.parametrize("size,rotate,expected", [("96x64", False, (96, 64)), ("64x96", False, (64, 96)), ("96x64", True, (64, 96))])
async def test_real_landscape_portrait_rotation(storage, media, user_config, video_tools, tmp_path, size, rotate, expected):
    ffmpeg, ffprobe = video_tools
    source = tmp_path / "input.mp4"
    run_video([ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=5:duration=2",
               "-c:v", "libx264", "-threads", "1", str(source)])
    if rotate:
        rotated = tmp_path / "rotated.mp4"
        run_video([ffmpeg, "-v", "error", "-i", str(source), "-c", "copy",
                   "-metadata:s:v:0", "rotate=90", str(rotated)])
        source = rotated
    service = service_for(source.read_bytes(), ffmpeg=ffmpeg, ffprobe=ffprobe)
    result = await service.prepare_frames({**media, "file_type": "video"}, user_config, context=storage)
    assert result.planned_frames == 2
    assert [(frame.width, frame.height) for frame in result.frames] == [expected, expected]
    assert [frame.timestamp_ms for frame in result.frames] == [0, 1000]
    assert not list(storage.temp_dir.iterdir())


async def test_real_vfr_pts_and_duplicate_hits(storage, media, user_config, video_tools, tmp_path):
    ffmpeg, ffprobe = video_tools
    source = tmp_path / "vfr.mp4"
    run_video([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=10:duration=4",
        "-vf", "select='eq(n,0)+eq(n,7)+eq(n,19)+eq(n,39)'",
        "-vsync", "vfr", "-c:v", "libx264", "-threads", "1", str(source),
    ])
    result = await service_for(source.read_bytes(), ffmpeg=ffmpeg, ffprobe=ffprobe).prepare_frames(
        {**media, "file_type": "video"}, user_config, context=storage,
    )
    assert result.planned_frames == 4
    assert [frame.timestamp_ms for frame in result.frames] == [0, 700, 1900]
    assert len(result.frames) < result.planned_frames
    assert result.frames[-1].timestamp_ms != 2000  # Never synthesize timestamps from target/FPS.


async def test_real_long_video_uniform_sampling(storage, media, user_config, video_tools, tmp_path):
    ffmpeg, ffprobe = video_tools
    source = tmp_path / "long.mp4"
    run_video([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=32x32:rate=1:duration=125",
               "-c:v", "libx264", "-threads", "1", str(source)])
    result = await service_for(source.read_bytes(), ffmpeg=ffmpeg, ffprobe=ffprobe).prepare_frames(
        {**media, "file_type": "video"}, user_config, context=storage,
    )
    assert len(result.frames) == result.planned_frames == 60
    assert result.frames[-1].timestamp_ms == 122000


@pytest.mark.parametrize("metadata", [
    {"width": 8000, "height": 10, "duration": "10"},
    {"width": 100, "height": 100, "duration": "1801"},
    {"width": 100, "height": 100, "duration": "NaN"},
])
async def test_probe_limits_before_decode(storage, media, user_config, monkeypatch, metadata):
    service = service_for(b"video")
    probe = AsyncMock(return_value=json.dumps({
        "streams": [metadata], "format": {"duration": metadata["duration"]},
    }).encode())
    monkeypatch.setattr(service, "_run_process", probe)
    with pytest.raises(ServiceError):
        await service.prepare_frames({**media, "file_type": "video"}, user_config, context=storage)
    assert probe.await_count == 1
    args = probe.call_args.args[0]
    assert args[args.index("-protocol_whitelist") + 1] == "file"
    assert args[args.index("-format_whitelist") + 1] == "mov,matroska,avi,mpegts,mpeg,mpegvideo"
    assert not list(storage.temp_dir.iterdir())


def test_all_seven_configuration_names(tmp_path):
    config = SimpleNamespace(
        ANNOTATION_STORAGE_DIR=str(tmp_path / "persistent"),
        ANNOTATION_TEMP_DIR=str(tmp_path / "temporary"),
        ANNOTATION_MAX_VIDEO_BYTES=123,
        ANNOTATION_MAX_VIDEO_SECONDS=124,
        ANNOTATION_MAX_FRAME_PIXELS=125,
        ANNOTATION_DECODE_TIMEOUT=126,
        ANNOTATION_DECODE_CONCURRENCY=1,
    )
    context = FrameStorageContext.from_settings("owner", "media", "v1", config=config)
    service = AnnotationFrameService(config=config)
    assert context.storage_dir == tmp_path / "persistent"
    assert context.temp_dir == tmp_path / "temporary"
    assert (service.max_video_bytes, service.max_duration_seconds, service.max_pixels, service.subprocess_timeout) == (123, 124, 125, 126)
    config.ANNOTATION_DECODE_CONCURRENCY = 2
    with pytest.raises(ValueError):
        AnnotationFrameService(config=config)
    with pytest.raises(ServiceError):
        FrameStorageContext.from_settings("owner", "media", "v1", config=SimpleNamespace())


async def test_download_cancel_closes_stream_and_removes_work(storage, media, user_config):
    entered = asyncio.Event()
    stream = ObjectStream(jpeg())

    async def blocked_bytes():
        entered.set()
        await asyncio.Event().wait()
        yield b"unreachable"

    stream.aiter_bytes = blocked_bytes

    @asynccontextmanager
    async def borrow(config):
        yield type("TOS", (), {"open_object": AsyncMock(return_value=stream)})()

    service = AnnotationFrameService(tos_borrower=borrow)
    task = asyncio.create_task(service.prepare_frames(media, user_config, context=storage))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed and not list(storage.temp_dir.iterdir())
    # A cancelled preparation must release the shared decoder slot.
    await asyncio.wait_for(service_for(jpeg()).prepare_frames(media, user_config, context=storage), 1)


async def test_download_timeout_cleanup(storage, media, user_config):
    @asynccontextmanager
    async def borrow(config):
        await asyncio.Event().wait()
        yield

    with pytest.raises(ServiceError) as error:
        await AnnotationFrameService(tos_borrower=borrow, download_timeout=0.01).prepare_frames(
            media, user_config, context=storage,
        )
    assert error.value.category == "timeout"
    assert not list(storage.temp_dir.iterdir())


async def test_real_subprocess_disk_quota_and_safe_error(tmp_path):
    service = AnnotationFrameService(max_decode_bytes=10, subprocess_timeout=2)
    with pytest.raises(ServiceError):
        await service._run_process([
            sys.executable, "-c",
            "import pathlib,sys,time; pathlib.Path(sys.argv[1]).joinpath('frame.png').write_bytes(b'x'*100); time.sleep(60)",
            str(tmp_path),
        ], disk_dir=tmp_path)
    with pytest.raises(ServiceError) as error:
        await service._run_process([
            sys.executable, "-c", "import sys; sys.stderr.write('SECRET /private/path'); sys.exit(1)",
        ])
    assert "SECRET" not in str(error.value)


async def test_video_two_gib_limit_before_download(storage, media, user_config):
    service = service_for(b"video")
    with pytest.raises(ServiceError):
        await service.prepare_frames(
            {**media, "file_type": "video", "file_size": 2 * 1024**3 + 1}, user_config, context=storage,
        )
    assert service.calls == []


async def test_real_nonzero_start_pts(storage, media, user_config, video_tools, tmp_path):
    ffmpeg, ffprobe = video_tools
    source = tmp_path / "offset.mp4"
    run_video([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=5:duration=2",
        "-vf", "setpts=PTS+5/TB", "-vsync", "vfr", "-c:v", "libx264",
        "-threads", "1", str(source),
    ])
    result = await service_for(source.read_bytes(), ffmpeg=ffmpeg, ffprobe=ffprobe).prepare_frames(
        {**media, "file_type": "video"}, user_config, context=storage,
    )
    assert result.duration_ms == 2000
    assert result.planned_frames == 2
    assert [frame.timestamp_ms for frame in result.frames] == [0, 1000]


async def test_progress_and_persistent_rollback_on_cancel(storage, media, user_config):
    events = []

    async def progress(event):
        events.append(event)

    service = service_for(jpeg())
    result = await service.prepare_frames(media, user_config, context=storage, on_progress=progress)
    assert events == [
        {"stage": "downloading", "planned_frames": None, "prepared_frames": 0},
        {"stage": "persisting", "planned_frames": 1, "prepared_frames": 1},
        {"stage": "prepared", "planned_frames": 1, "prepared_frames": 1},
    ]

    async def cancel(event):
        if event["stage"] == "persisting":
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await service.prepare_frames(
            media, user_config, context=replace(storage, revision="cancelled"), on_progress=cancel,
        )
    assert not list((storage.storage_dir / "owner/media/cancelled").glob("*.png"))
    assert result.frames[0].path.exists()
    assert not list(storage.temp_dir.iterdir())
