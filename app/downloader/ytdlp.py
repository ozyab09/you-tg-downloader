"""Обёртка над yt-dlp: метаданные и скачивание во временный файл (tmpfs)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Callable

import yt_dlp

from app.config.settings import Settings
from app.downloader.errors import DownloadError, TooLargeError, map_ytdlp_error
from app.downloader.formats import FormatChoice

logger = logging.getLogger(__name__)

# Колбэк прогресса: получает процент 0..100. Вызывается из потока executor'а.
ProgressCallback = Callable[[int], None]


class _ProgressReporter:
    """Собирает процент из progress_hooks yt-dlp и поддерживает отмену."""

    def __init__(
        self,
        on_progress: ProgressCallback | None,
        cancel_event: threading.Event,
    ) -> None:
        self._on_progress = on_progress
        self._cancel_event = cancel_event
        self.last_percent = 0

    def hook(self, d: dict[str, Any]) -> None:
        if self._cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Загрузка отменена пользователем")
        status = d.get("status")
        if status == "finished":
            if self._on_progress:
                self._on_progress(100)
            self.last_percent = 100
            return
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes")
            if total and downloaded is not None and self._on_progress:
                percent = int(downloaded * 100 / total)
                if percent != self.last_percent:
                    self.last_percent = percent
                    self._on_progress(percent)


class YtDlpClient:
    """Асинхронная обёртка над yt-dlp (вызовы в thread executor'е)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _base_opts(self) -> dict[str, Any]:
        return {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
            # Ошибки вида "The page needs to be reloaded" intermittent —
            # повторные попытки извлечения помогают (yt-dlp issue #17389).
            "extractor_retries": 3,
            "file_access_retries": 3,
            "retry_sleep_functions": {},
            "geo_bypass": True,
        }

    def _selection(self, choice: FormatChoice) -> str:
        if choice.kind == "video":
            return choice.format_id or "best"
        if choice.kind == "best":
            return "bestvideo*+bestaudio/best"
        return "bestaudio/best"

    def _make_opts(
        self,
        choice: FormatChoice,
        outtmpl: str,
        max_bytes: int,
        reporter: _ProgressReporter,
    ) -> dict[str, Any]:
        opts = self._base_opts()
        opts.update(
            {
                "format": self._selection(choice),
                "outtmpl": outtmpl,
                "max_filesize": max_bytes,
                "progress_hooks": [reporter.hook],
            }
        )
        if choice.kind == "audio":
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(choice.audio_bitrate_kbps or 192),
                }
            ]
        else:
            opts["merge_output_format"] = "mp4"
        return opts

    async def extract_info(self, url: str) -> dict:
        """Извлекает метаданные видео (без скачивания)."""

        def _sync() -> dict:
            with yt_dlp.YoutubeDL(self._base_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
                return info or {}

        try:
            return await asyncio.to_thread(_sync)
        except yt_dlp.utils.DownloadError as exc:
            raise map_ytdlp_error(str(exc)) from exc

    def _download_sync(
        self,
        url: str,
        choice: FormatChoice,
        outtmpl: str,
        max_bytes: int,
        reporter: _ProgressReporter,
        cancel_event: threading.Event,
    ) -> str:
        opts = self._make_opts(choice, outtmpl, max_bytes, reporter)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise DownloadError("Не удалось получить информацию о видео")
                if "entries" in info:
                    entries = [e for e in (info.get("entries") or []) if e]
                    if not entries:
                        raise DownloadError("Плейлист пуст")
                    info = entries[0]

                requested = info.get("requested_downloads") or []
                if requested:
                    path = requested[0].get("filepath") or requested[0].get("filename")
                    if path and os.path.exists(path):
                        return str(path)

                path = ydl.prepare_filename(info)
                if choice.kind == "audio" and not path.lower().endswith(".mp3"):
                    candidate = os.path.splitext(path)[0] + ".mp3"
                    if os.path.exists(candidate):
                        return candidate
                if os.path.exists(path):
                    return path
                raise DownloadError(f"Файл не найден после скачивания: {path}")
        except yt_dlp.utils.DownloadCancelled:
            raise
        except yt_dlp.utils.MaxDownloadsReached:
            raise TooLargeError("Размер файла превышает установленный лимит") from None
        except yt_dlp.utils.DownloadError as exc:
            raise map_ytdlp_error(str(exc)) from exc

    async def download_to_file(
        self,
        url: str,
        choice: FormatChoice,
        outtmpl: str,
        max_bytes: int,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Скачивает выбранный формат во временный файл и возвращает путь к нему."""
        cancel_event = cancel_event or threading.Event()
        reporter = _ProgressReporter(on_progress, cancel_event)
        try:
            return await asyncio.to_thread(
                self._download_sync,
                url,
                choice,
                outtmpl,
                max_bytes,
                reporter,
                cancel_event,
            )
        except yt_dlp.utils.DownloadCancelled:
            raise DownloadError("Загрузка отменена") from None


__all__ = ["YtDlpClient", "ProgressCallback"]
