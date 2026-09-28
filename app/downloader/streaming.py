"""Потоковая передача: pipe `yt-dlp -> ffmpeg -> Telegram` без записи на диск.

yt-dlp отдаёт мердж video+audio в matroska на stdout (mkv можно стримить),
ffmpeg перепаковывает его в фрагментированный mp4 (streamable, без moov-atom
в конце), который уходит в Telegram Bot API через multipart streaming.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

from app.downloader.errors import DownloadError, TooLargeError, map_ytdlp_error

logger = logging.getLogger(__name__)

BUF_SIZE = 512 * 1024  # 512 KB

# ffmpeg, убитый SIGPIPE (закрытие приёмника), возвращает -13/255 — это не ошибка.
_GRACEFUL_EXIT_CODES = {0, -13, -15, 255}
_STDERR_KEEP = 8


class StreamSession:
    """Управляет парой процессов yt-dlp | ffmpeg и отдаёт mp4-поток чанками."""

    def __init__(self, url: str, format_selector: str, max_bytes: int) -> None:
        self._url = url
        self._format_selector = format_selector
        self._max_bytes = max_bytes
        self._ytdlp_proc: asyncio.subprocess.Process | None = None
        self._ffmpeg_proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_KEEP)
        self._total = 0
        self._closed = False

    @property
    def total_bytes(self) -> int:
        return self._total

    async def start(self) -> None:
        ytdlp_cmd = [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--no-playlist",
            "-o",
            "-",
            "-f",
            self._format_selector,
            "--merge-output-format",
            "matroska",
            "--retries",
            "2",
            "--socket-timeout",
            "30",
            self._url,
        ]
        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov",
            "pipe:1",
        ]

        try:
            self._ytdlp_proc = await asyncio.create_subprocess_exec(
                *ytdlp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._ffmpeg_proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, FileNotFoundError) as exc:
            await self.close()
            raise DownloadError(f"Не удалось запустить процессы скачивания: {exc}") from exc

        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        proc = self._ytdlp_proc
        if proc is None or proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").strip()
            if text:
                self._stderr_tail.append(text)

    def __aiter__(self) -> StreamSession:
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        ffmpeg = self._ffmpeg_proc
        if ffmpeg is None or ffmpeg.stdout is None:
            raise StopAsyncIteration

        chunk = await ffmpeg.stdout.read(BUF_SIZE)
        if not chunk:
            await self._finish_checks()
            raise StopAsyncIteration

        self._total += len(chunk)
        if self._total > self._max_bytes:
            raise TooLargeError(
                "Размер файла превышает лимит Telegram Bot API "
                f"({self._max_bytes // (1024 * 1024)} МБ)"
            )
        return chunk

    async def _finish_checks(self) -> None:
        """После конца stdout ffmpeg проверяет коды возврата процессов."""
        ytdlp = self._ytdlp_proc
        ffmpeg = self._ffmpeg_proc
        if ytdlp is None or ffmpeg is None:
            return

        if self._stderr_task:
            self._stderr_task.cancel()

        ytdlp_rc = ytdlp.returncode
        if ytdlp_rc is None:
            try:
                ytdlp_rc = await asyncio.wait_for(ytdlp.wait(), timeout=10)
            except asyncio.TimeoutError:
                ytdlp_rc = -1

        ffmpeg_rc = ffmpeg.returncode
        if ffmpeg_rc is None:
            try:
                ffmpeg_rc = await asyncio.wait_for(ffmpeg.wait(), timeout=10)
            except asyncio.TimeoutError:
                ffmpeg_rc = -1

        if ytdlp_rc not in (0, None) and self._total == 0:
            tail = " | ".join(self._stderr_tail) or f"код {ytdlp_rc}"
            raise map_ytdlp_error(tail)
        if ffmpeg_rc not in _GRACEFUL_EXIT_CODES and self._total == 0:
            raise DownloadError(f"ffmpeg завершился с кодом {ffmpeg_rc}")
        if self._total == 0:
            raise DownloadError("Пустой поток: данные не получены")

    async def cancel(self) -> None:
        """Прерывает скачивание: TERM, затем KILL, затем чистит ресурсы."""
        logger.info("Отмена потокового скачивания (получено байт: %d)", self._total)
        await self.close()

    async def close(self) -> None:
        """Останавливает процессы и закрывает пайпы (идемпотентно)."""
        if self._closed:
            return
        self._closed = True

        if self._stderr_task:
            self._stderr_task.cancel()

        for proc in (self._ffmpeg_proc, self._ytdlp_proc):
            if proc is None or proc.returncode is not None:
                continue
            try:
                proc.terminate()
            except ProcessLookupError:
                continue
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                with_suppress_kill(proc)

        # Небольшая пауза, чтобы SIGPIPE дошёл до соседнего процесса.
        await asyncio.sleep(0.1)
        for proc in (self._ffmpeg_proc, self._ytdlp_proc):
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()

        for proc in (self._ffmpeg_proc, self._ytdlp_proc):
            if proc is None:
                continue
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()


def with_suppress_kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


__all__ = ["StreamSession"]
