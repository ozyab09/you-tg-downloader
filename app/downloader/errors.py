"""Типы ошибок скачивания и сопоставление ошибок yt-dlp понятным категориям."""

from __future__ import annotations

import re


class DownloadError(Exception):
    """Базовая ошибка скачивания (покажем пользователю общий текст)."""


class UnavailableError(DownloadError):
    """Видео недоступно: приватное, удалено, регион, возрастное ограничение."""


class AccessDeniedError(DownloadError):
    """Видео требует авторизации (members-only, покупка и т.п.)."""


class LiveStreamError(DownloadError):
    """Прямой эфир нельзя скачать."""


class TooLargeError(DownloadError):
    """Файл больше лимита (ENV / Telegram Bot API)."""


class FormatNotFoundError(DownloadError):
    """Выбранный формат недоступен для этого видео."""


class UpstreamTimeoutError(DownloadError):
    """Таймаут при скачивании или отправке."""


_PATTERNS: tuple[tuple[re.Pattern[str], type[DownloadError]], ...] = (
    (
        re.compile(
            r"(private video|video unavailable|has been removed|removed by the uploader"
            r"|terminated|geo-?restrict|not available in your country|region"
            r"|age.?restrict|confirm your age|inappropriate|login required"
            r"|sign in to confirm|Members-only|premieres? in|is not a live stream)",
            re.IGNORECASE,
        ),
        UnavailableError,
    ),
    (
        re.compile(r"(join this channel|members-?only content|purchase|rent)", re.IGNORECASE),
        AccessDeniedError,
    ),
    (re.compile(r"(is live|live event|livestream)", re.IGNORECASE), LiveStreamError),
    (
        re.compile(r"(larger than|file is larger|max.?file.?size|too large|exceeds)", re.IGNORECASE),
        TooLargeError,
    ),
    (
        re.compile(r"(timed?\s?out|timeout)", re.IGNORECASE),
        UpstreamTimeoutError,
    ),
)


def map_ytdlp_error(message: str) -> DownloadError:
    """Сопоставляет текст ошибки yt-dlp с типизированной ошибкой."""
    if isinstance(message, Exception):
        message = str(message)
    for pattern, exc_class in _PATTERNS:
        if pattern.search(message):
            return exc_class(message)
    return DownloadError(message)


__all__ = [
    "AccessDeniedError",
    "DownloadError",
    "FormatNotFoundError",
    "LiveStreamError",
    "TooLargeError",
    "UnavailableError",
    "UpstreamTimeoutError",
    "map_ytdlp_error",
]
