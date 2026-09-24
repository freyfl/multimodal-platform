"""
日志工具模块
"""
import copy
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from app.config import settings


_LOG_DIR = Path("logs")
_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]+", re.IGNORECASE)
_BEARER = re.compile(r"(?i)\b(authorization\s*[:=]?\s*bearer|bearer)\s+\S+")
_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key(?:[_-]?(?:id|secret))?|"
    r"security[_-]?token|password|signature)\b(\s*[:=]\s*)[^\s,;}\]]+"
)


def redact_log_text(value: object) -> str:
    """Best-effort defense for accidental credential or signed URL logging."""
    text = str(value)
    text = _URL_QUERY.sub(r"\1?<redacted>", text)
    text = _BEARER.sub(r"\1 <redacted>", text)
    return _SECRET_VALUE.sub(r"\1\2<redacted>", text)


class CustomFormatter(logging.Formatter):
    """Format a copied record so handlers cannot leak color or raw secrets."""

    def format(self, record):
        safe_record = copy.copy(record)
        safe_record.exc_info = None
        safe_record.exc_text = None
        return redact_log_text(super().format(safe_record))


class ColorFormatter(CustomFormatter):
    def format(self, record):
        level_color = {
            logging.DEBUG: "\033[36m",
            logging.INFO: "\033[32m",
            logging.WARNING: "\033[33m",
            logging.ERROR: "\033[31m",
            logging.CRITICAL: "\033[35m",
        }.get(record.levelno, "\033[0m")
        safe_record = copy.copy(record)
        safe_record.levelname = f"{level_color}{record.levelname}\033[0m"
        return super().format(safe_record)


class LazyDailyFileHandler(logging.Handler):
    """Avoid filesystem writes merely by importing the application."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self._handler = None

    def emit(self, record):
        if self._handler is None:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            self._handler = logging.FileHandler(
                _LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log",
                encoding="utf-8",
            )
            self._handler.setFormatter(self.formatter)
        self._handler.emit(record)

    def close(self):
        if self._handler is not None:
            self._handler.close()
        super().close()


def setup_logger(name: str = "app") -> logging.Logger:
    """设置并返回日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    console_formatter = ColorFormatter(
        "%(levelname)s | %(asctime)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 文件处理器
    file_handler = LazyDailyFileHandler()
    file_formatter = logging.Formatter(
        "%(levelname)s | %(asctime)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(CustomFormatter(
        file_formatter._fmt, datefmt=file_formatter.datefmt,
    ))
    logger.addHandler(file_handler)
    logger.propagate = False

    return logger


# 全局日志实例
logger = setup_logger("multimodal_platform")
