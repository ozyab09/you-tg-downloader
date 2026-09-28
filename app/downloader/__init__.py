"""Модуль downloader: обёртка yt-dlp, форматы, пайплайн загрузки, отправка в Telegram."""

from app.downloader.errors import (
    AccessDeniedError,
    DownloadError,
    FormatNotFoundError,
    LiveStreamError,
    TooLargeError,
    UnavailableError,
    UpstreamTimeoutError,
    map_ytdlp_error,
)
from app.downloader.formats import (
    AudioOption,
    FormatChoice,
    VideoOption,
    build_format_menu,
)

__all__ = [
    "AccessDeniedError",
    "DownloadError",
    "FormatNotFoundError",
    "LiveStreamError",
    "TooLargeError",
    "UnavailableError",
    "UpstreamTimeoutError",
    "map_ytdlp_error",
    "AudioOption",
    "FormatChoice",
    "VideoOption",
    "build_format_menu",
]
