"""
通用工具函数
"""
import uuid
import hashlib
import re
from datetime import datetime
from typing import Optional
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


def generate_uuid() -> str:
    """生成UUID字符串"""
    return str(uuid.uuid4())


def generate_short_id() -> str:
    """生成短ID (8位)"""
    return uuid.uuid4().hex[:8]


def calculate_file_hash(file_content: bytes) -> str:
    """计算文件内容的MD5哈希"""
    return hashlib.md5(file_content).hexdigest()


def get_file_extension(filename: str) -> str:
    """获取文件扩展名"""
    return Path(filename).suffix.lower()


def is_video_file(filename: str) -> bool:
    """判断是否为视频文件"""
    video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}
    return get_file_extension(filename) in video_extensions


def is_image_file(filename: str) -> bool:
    """判断是否为图片文件"""
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    return get_file_extension(filename) in image_extensions


def is_media_file(filename: str) -> bool:
    """判断是否为媒体文件"""
    return is_video_file(filename) or is_image_file(filename)


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小显示"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def format_duration(seconds: float) -> str:
    """格式化持续时间"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


_TOS_BUCKET_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")


def parse_tos_url(tos_url: str) -> Optional[dict]:
    """Decode a TOS URI once; signed HTTP URLs are never storage identifiers."""
    if not isinstance(tos_url, str) or not tos_url.startswith("tos://"):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in tos_url):
        return None
    try:
        parsed = urlsplit(tos_url, allow_fragments=False)
        if not _TOS_BUCKET_RE.fullmatch(parsed.netloc) or parsed.query:
            return None
        key = unquote(parsed.path[1:], encoding="utf-8", errors="strict")
        if any(ord(char) < 32 or ord(char) == 127 for char in key):
            return None
    except (ValueError, UnicodeError):
        return None
    return {"bucket": parsed.netloc, "path": key, "filename": key.rsplit("/", 1)[-1]}


def build_tos_url(bucket: str, path: str) -> str:
    """Encode a raw SDK key once; callers must not pass an already encoded key."""
    if not isinstance(bucket, str) or not _TOS_BUCKET_RE.fullmatch(bucket):
        raise ValueError("Invalid TOS bucket")
    if not isinstance(path, str) or any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError("Invalid TOS object key")
    return f"tos://{bucket}/{quote(path, safe='/')}"


class AsyncIterator:
    """异步迭代器包装器"""

    def __init__(self, iterable):
        self.iterable = iter(iterable)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.iterable)
        except StopIteration:
            raise StopAsyncIteration
