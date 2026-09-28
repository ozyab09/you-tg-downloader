"""Потоковая передача: yt-dlp(видео) + yt-dlp(аудио) -> ffmpeg -> Telegram.

Важно: НЕ используем встроенный мердж yt-dlp в stdout (-f "bv+ba" -o -):
в этом режиме yt-dlp делегирует скачивание ffmpeg, чей HTTP-клиент YouTube
троттлит до ~40 КБ/с. Нативный загрузчик yt-dlp (range-запросы) не троттлится
(~1 МБ/с), поэтому качаем оба потока отдельными процессами и мерджим своим
ffmpeg через переданные файловые дескрипторы (pass_fds) — оба скачивания
идут параллельно на полной скорости.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from collections.abc import Callable

from app.downloader.errors import DownloadError, TooLargeError, map_ytdlp_error

logger = logging.getLogger(__name__)

BUF_SIZE = 512 * 1024  # 512 KB
_STDERR_KEEP = 8
_GRACEFUL_EXIT_CODES = {0, -13, -15, 255}


class StreamSession:
    """Видео и аудио качаются параллельно двумя yt-dlp, мердж — наш ffmpeg.

    Пайпы: yt-dlp(video) -> fd W1 -> ffmpeg pipe:R1
           yt-dlp(audio) -> fd W2 -> ffmpeg pipe:R2
           ffmpeg -> stdout -> чанки для загрузки в Telegram.
    """

    def __init__(
        self,
        url: str,
        video_selector: str,
        audio_selector: str,
        max_bytes: int,
        expected_total: int | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        self._url = url
        self._video_selector = video_selector
        self._audio_selector = audio_selector
        self._max_bytes = max_bytes
        self._expected = expected_total
        self._on_progress = on_progress

        self._video_proc: asyncio.subprocess.Process | None = None
        self._audio_proc: asyncio.subprocess.Process | None = None
        self._ffmpeg_proc: asyncio.subprocess.Process | None = None
        self._drain_tasks: list[asyncio.Task[None]] = []
        self._tails: dict[str, deque[str]] = {
            "video": deque(maxlen=_STDERR_KEEP),
            "audio": deque(maxlen=_STDERR_KEEP),
            "ffmpeg": deque(maxlen=_STDERR_KEEP),
        }
        self._total = 0
        self._last_percent = -1
        self._closed = False

    @property
    def total_bytes(self) -> int:
        return self._total

    def _ytdlp_cmd(self, selector: str) -> list[str]:
        return [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--no-playlist",
            "-o",
            "-",
            "-f",
            selector,
            "--retries",
            "3",
            "--socket-timeout",
            "30",
            self._url,
        ]

    async def start(self) -> None:
        r_video, w_video = os.pipe()
        r_audio, w_audio = os.pipe()

        try:
            self._video_proc = await asyncio.create_subprocess_exec(
                *self._ytdlp_cmd(self._video_selector),
                stdout=w_video,
                stderr=asyncio.subprocess.PIPE,
            )
            self._audio_proc = await asyncio.create_subprocess_exec(
                *self._ytdlp_cmd(self._audio_selector),
                stdout=w_audio,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, FileNotFoundError) as exc:
            os.close(w_video)
            os.close(w_audio)
            os.close(r_video)
            os.close(r_audio)
            await self.close()
            raise DownloadError(f"Не удалось запустить yt-dlp: {exc}") from exc

        # Наш копии write-концов больше не нужны: EOF придёт от процессов.
        os.close(w_video)
        os.close(w_audio)

        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            f"pipe:{r_video}",
            "-i",
            f"pipe:{r_audio}",
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
            self._ffmpeg_proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                pass_fds=(r_video, r_audio),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, FileNotFoundError) as exc:
            os.close(r_video)
            os.close(r_audio)
            await self.close()
            raise DownloadError(f"Не удалось запустить ffmpeg: {exc}") from exc

        os.close(r_video)
        os.close(r_audio)

        self._drain_tasks = [
            asyncio.create_task(self._drain(self._video_proc, "video")),
            asyncio.create_task(self._drain(self._audio_proc, "audio")),
            asyncio.create_task(self._drain(self._ffmpeg_proc, "ffmpeg")),
        ]

    async def _drain(self, proc: asyncio.subprocess.Process, key: str) -> None:
        if proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").strip()
            if text:
                self._tails[key].append(text)

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
        if self._on_progress and self._expected:
            percent = min(99, self._total * 100 // self._expected)
            if percent != self._last_percent:
                self._last_percent = percent
                self._on_progress(percent)
        return chunk

    async def _finish_checks(self) -> None:
        video = self._video_proc
        audio = self._audio_proc
        ffmpeg = self._ffmpeg_proc
        if video is None or audio is None or ffmpeg is None:
            return

        for task in self._drain_tasks:
            task.cancel()

        async def _wait(proc: asyncio.subprocess.Process) -> int:
            try:
                return await asyncio.wait_for(proc.wait(), timeout=15)
            except asyncio.TimeoutError:
                return -1

        video_rc = video.returncode if video.returncode is not None else await _wait(video)
        audio_rc = audio.returncode if audio.returncode is not None else await _wait(audio)
        ffmpeg_rc = ffmpeg.returncode if ffmpeg.returncode is not None else await _wait(ffmpeg)

        if self._total == 0:
            if video_rc != 0:
                tail = " | ".join(self._tails["video"]) or f"код {video_rc}"
                raise map_ytdlp_error(tail)
            if audio_rc != 0:
                tail = " | ".join(self._tails["audio"]) or f"код {audio_rc}"
                raise map_ytdlp_error(tail)
            if ffmpeg_rc not in _GRACEFUL_EXIT_CODES:
                tail = " | ".join(self._tails["ffmpeg"]) or f"код {ffmpeg_rc}"
                raise DownloadError(f"ffmpeg: {tail}")
            raise DownloadError("Пустой поток: данные не получены")

    async def cancel(self) -> None:
        logger.info("Отмена потокового скачивания (получено байт: %d)", self._total)
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        for task in self._drain_tasks:
            task.cancel()

        procs = [self._ffmpeg_proc, self._video_proc, self._audio_proc]
        for proc in procs:
            if proc is None or proc.returncode is not None:
                continue
            try:
                proc.terminate()
            except ProcessLookupError:
                continue

        for proc in procs:
            if proc is None or proc.returncode is not None:
                continue
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

        for proc in procs:
            if proc is None:
                continue
            # У асинхронных стримов нет .close(); завершаем через transport.
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None and stream.transport is not None:
                    stream.transport.close()


__all__ = ["StreamSession"]
