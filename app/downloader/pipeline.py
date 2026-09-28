"""Пайплайн доставки: гибрид (pipe по умолчанию, откат на tmpfs), отмена, лимиты."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from app.config.settings import Settings
from app.downloader.errors import DownloadError, TooLargeError
from app.downloader.formats import FormatChoice
from app.downloader.streaming import StreamSession
from app.downloader.telegram_upload import upload_stream_to_telegram
from app.downloader.ytdlp import YtDlpClient
from app.utils.formatting import human_size

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int], None]
PhaseCallback = Callable[[str], None]

# Общий таймаут на скачивание+отправку одной задачи.
JOB_TIMEOUT_SEC = 1800


@dataclass
class DeliveryResult:
    ok: bool
    kind: str  # video | audio
    mode: str  # stream | tmpfs
    bytes_sent: int = 0


class CancelRegistry:
    """Реестр активных задач для кнопки «Отмена»."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._events: dict[int, asyncio.Event] = {}

    async def register(self, key: int) -> asyncio.Event:
        async with self._lock:
            event = asyncio.Event()
            self._events[key] = event
            return event

    async def cancel(self, key: int) -> bool:
        async with self._lock:
            event = self._events.get(key)
            if event is None:
                return False
            event.set()
            return True

    async def unregister(self, key: int) -> None:
        async with self._lock:
            self._events.pop(key, None)


class DeliveryPipeline:
    """Скачивает выбранный формат и отправляет файл в чат.

    Гибридная стратегия (выбор согласован с заказчиком):
    1) pipe yt-dlp -> ffmpeg -> Bot API (без записи на диск);
    2) при любой ошибке стрима (кроме «файл слишком большой» и отмены) —
       повтор через tmpfs (/dev/shm) с гарантированной очисткой в finally.
    Аудио всегда рендерится в mp3 через yt-dlp (ffmpeg) во временный файл.

    Колбэки:
        on_phase(phase) — смена фазы: "download" | "convert" | "upload";
        on_progress(percent) — процент текущей фазы (0..100).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ytdlp = YtDlpClient(settings)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)
        self._registry = CancelRegistry()
        self._tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()

    @property
    def cancel_registry(self) -> CancelRegistry:
        return self._registry

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    @property
    def ytdlp_client(self) -> YtDlpClient:
        return self._ytdlp

    def selection_for(self, choice: FormatChoice) -> str:
        if choice.kind == "video":
            return choice.format_id or "bestvideo*+bestaudio/best"
        if choice.kind == "best":
            return "bestvideo*+bestaudio/best"
        return "bestaudio/best"

    def _video_selector(self, choice: FormatChoice) -> str:
        if choice.kind == "best":
            return "bestvideo*"
        return choice.format_id or "bestvideo*"

    def _audio_selector(self, choice: FormatChoice) -> str:
        return "bestaudio"

    async def _estimate_size(self, url: str, choice: FormatChoice) -> int | None:
        """Оценка итогового размера (видео + аудио + запас на AAC) по метаданным."""
        try:
            info = await self._ytdlp.extract_info(url)
        except Exception:  # noqa: BLE001 — оценка не критична для работы
            return None
        fmts = info.get("formats") or []
        duration = info.get("duration")

        video_kbps = 0.0
        if choice.kind == "video" and choice.height:
            heights = [
                f for f in fmts
                if (f.get("vcodec") or "none") != "none"
                and isinstance(f.get("height"), int)
                and f["height"] <= choice.height
                and isinstance(f.get("tbr"), (int, float))
                and (f.get("protocol") or "") not in ("m3u8", "m3u8_native")
            ]
            if heights:
                video_kbps = max(f["tbr"] for f in heights)
        elif choice.kind == "best" and fmts:
            vbrs = [
                f["tbr"] for f in fmts
                if (f.get("vcodec") or "none") != "none"
                and isinstance(f.get("tbr"), (int, float))
            ]
            video_kbps = max(vbrs, default=0.0)

        abrs = [
            f["tbr"] for f in fmts
            if (f.get("vcodec") or "none") == "none"
            and (f.get("acodec") or "none") != "none"
            and isinstance(f.get("tbr"), (int, float))
        ]
        audio_kbps = max(abrs, default=128.0)

        if not duration or (video_kbps <= 0 and choice.kind == "video"):
            return None
        # tbr уже включает аудио у прогрессивных, но у DASH это только поток.
        total_kbps = video_kbps + 160  # аудио перекодируется в AAC 160k
        if choice.kind == "audio" or audio_kbps > 0 and video_kbps == 0:
            total_kbps = audio_kbps
        bytes_ = int(total_kbps * 1000 / 8 * duration)
        return max(1, bytes_)

    async def deliver(
        self,
        url: str,
        chat_id: int,
        choice: FormatChoice,
        caption: str,
        duration: int | None,
        title: str | None,
        performer: str | None,
        on_progress: ProgressCallback | None = None,
        on_phase: PhaseCallback | None = None,
    ) -> DeliveryResult:
        """Полный цикл: скачать и отправить. Прогресс и фазы — колбэками."""
        cancel_event = await self._registry.register(chat_id)
        try:
            async with self._semaphore:
                if cancel_event.is_set():
                    raise DownloadError("Задача отменена")

                if choice.kind == "audio":
                    return await self._deliver_via_tmpfs(
                        url, chat_id, choice, caption, duration, title, performer,
                        on_progress, on_phase, cancel_event,
                    )

                try:
                    return await self._deliver_video_stream(
                        url, chat_id, choice, caption, duration,
                        on_progress, on_phase, cancel_event,
                    )
                except TooLargeError:
                    # Больше не имеет смысла на tmpfs — там тот же лимит. Сообщаем сразу.
                    raise
                except DownloadError as exc:
                    if cancel_event.is_set():
                        raise DownloadError("Задача отменена") from None
                    logger.warning(
                        "Стриминг не удался (%s) — откатываюсь на tmpfs", exc
                    )
                    if on_phase:
                        on_phase("download")
                    return await self._deliver_via_tmpfs(
                        url, chat_id, choice, caption, duration, None, None,
                        on_progress, on_phase, cancel_event,
                    )
        finally:
            await self._registry.unregister(chat_id)

    # ---------------- видео (стрим, без диска) ----------------

    async def _deliver_video_stream(
        self,
        url: str,
        chat_id: int,
        choice: FormatChoice,
        caption: str,
        duration: int | None,
        on_progress: ProgressCallback | None,
        on_phase: PhaseCallback | None,
        cancel_event: asyncio.Event,
    ) -> DeliveryResult:
        max_bytes = self._settings.max_file_size_bytes

        # Оценка ожидаемого размера для прогресс-бара (из метаданных форматов).
        expected = await self._estimate_size(url, choice)

        # Если оценка превышает лимит — сообщаем сразу, не тратя трафик.
        if expected is not None and expected > max_bytes:
            raise TooLargeError(
                f"Ожидаемый размер файла ~{human_size(expected)} превышает лимит "
                f"Telegram Bot API ({human_size(max_bytes)}). Выберите качество ниже."
            )

        session = StreamSession(
            url,
            self._video_selector(choice),
            self._audio_selector(choice),
            max_bytes=max_bytes,
            expected_total=expected,
            on_progress=on_progress,
        )
        try:
            if on_phase:
                on_phase("download")
            await session.start()

            async def body() -> AsyncIterator[bytes]:
                async for chunk in session:
                    if cancel_event.is_set():
                        raise DownloadError("Задача отменена")
                    yield chunk

            # Переключаемся на фазу отправки, как только Telegram начал приём.
            if on_phase:
                on_phase("upload")

            try:
                await asyncio.wait_for(
                    upload_stream_to_telegram(
                        base_url=self._settings.api_base_url,
                        token=self._settings.bot_token,
                        chat_id=chat_id,
                        kind="video",
                        stream=body(),
                        caption=caption,
                        duration=duration,
                    ),
                    timeout=JOB_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                raise DownloadError("Таймаут при отправке файла в Telegram") from None

            if cancel_event.is_set():
                raise DownloadError("Задача отменена")

            return DeliveryResult(
                ok=True, kind="video", mode="stream", bytes_sent=session.total_bytes
            )
        finally:
            await session.close()

    # ---------------- tmpfs-реализация (аудио и откат видео) ----------------

    async def _deliver_via_tmpfs(
        self,
        url: str,
        chat_id: int,
        choice: FormatChoice,
        caption: str,
        duration: int | None,
        title: str | None,
        performer: str | None,
        on_progress: ProgressCallback | None,
        on_phase: PhaseCallback | None,
        cancel_event: asyncio.Event,
    ) -> DeliveryResult:
        loop = asyncio.get_running_loop()
        thread_cancel = threading.Event()

        def on_progress_threaded(percent: int) -> None:
            if cancel_event.is_set():
                thread_cancel.set()
            if on_progress:
                loop.call_soon_threadsafe(on_progress, percent)

        stem = f"ytdl_{uuid.uuid4().hex[:12]}"
        outtmpl = os.path.join(self._tmp_dir, f"{stem}.%(ext)s")
        max_bytes = self._settings.max_file_size_bytes
        tmp_path: str | None = None

        try:
            if on_phase:
                on_phase("download")
            try:
                tmp_path = await asyncio.wait_for(
                    self._ytdlp.download_to_file(
                        url=url,
                        choice=choice,
                        outtmpl=outtmpl,
                        max_bytes=max_bytes,
                        on_progress=on_progress_threaded,
                        cancel_event=thread_cancel,
                    ),
                    timeout=JOB_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                raise DownloadError("Таймаут при скачивании файла") from None

            if cancel_event.is_set() or thread_cancel.is_set():
                raise DownloadError("Задача отменена")

            size = os.path.getsize(tmp_path)
            if size > max_bytes:
                raise TooLargeError(
                    f"Файл ({human_size(size)}) больше лимита "
                    f"({human_size(max_bytes)})"
                )

            kind = "audio" if choice.kind == "audio" else "video"

            if on_phase:
                on_phase("upload")
            if on_progress:
                on_progress(0)

            def upload_progress(done: int, total: int) -> None:
                if on_progress:
                    on_progress(done * 100 // max(1, total))

            try:
                await asyncio.wait_for(
                    upload_stream_to_telegram(
                        base_url=self._settings.api_base_url,
                        token=self._settings.bot_token,
                        chat_id=chat_id,
                        kind=kind,
                        stream=file_stream(tmp_path),
                        caption=caption,
                        duration=duration,
                        title=title if kind == "audio" else None,
                        performer=performer if kind == "audio" else None,
                    ),
                    timeout=JOB_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                raise DownloadError("Таймаут при отправке файла в Telegram") from None

            return DeliveryResult(ok=True, kind=kind, mode="tmpfs", bytes_sent=size)
        finally:
            # Гарантированная очистка (DoD: временных файлов не остаётся).
            await loop.run_in_executor(None, _cleanup_stem, self._tmp_dir, stem)


async def file_stream(path: str, chunk_size: int = 512 * 1024) -> AsyncIterator[bytes]:
    """Асинхронный итератор по файлу (файл не грузится в память целиком)."""
    loop = asyncio.get_running_loop()
    f = await loop.run_in_executor(None, open, path, "rb")
    try:
        while True:
            chunk = await loop.run_in_executor(None, f.read, chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        await loop.run_in_executor(None, f.close)


def _cleanup_stem(tmp_dir: str, stem: str) -> None:
    """Удаляет все временные файлы с данным корнем имени (mp4, mp3, mkv, .part...)."""
    try:
        for name in os.listdir(tmp_dir):
            if name.startswith(stem):
                path = os.path.join(tmp_dir, name)
                try:
                    os.unlink(path)
                    logger.debug("Удалён временный файл: %s", path)
                except OSError as exc:
                    logger.warning("Не удалось удалить %s: %s", path, exc)
    except OSError as exc:
        logger.warning("Не удалось прочитать каталог %s: %s", tmp_dir, exc)


__all__ = ["CancelRegistry", "DeliveryPipeline", "DeliveryResult", "file_stream"]
