"""Хендлеры бота: приём ссылок, меню форматов, скачивание, отмена."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramRetryAfter,
)
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, texts
from app.bot.progress import ProgressAnimator
from app.config.settings import Settings
from app.downloader.cache import MetadataCache
from app.downloader.errors import DownloadError, TooLargeError, UnavailableError
from app.downloader.formats import FormatChoice, build_format_menu
from app.downloader.pipeline import DeliveryPipeline
from app.utils.formatting import format_duration, human_size
from app.utils.url import InvalidUrlError, is_youtube_url, normalize_youtube_url

logger = logging.getLogger(__name__)

# URL/метаданные последнего запроса на каждый chat (для callback'ов).
_last_payload: dict[int, dict[str, Any]] = {}


def _caption(info: dict) -> str:
    title = info.get("title") or "Без названия"
    duration = format_duration(info.get("duration"))
    uploader = info.get("uploader") or info.get("channel")
    lines = [f"🎬 <b>{title}</b>", f"⏱ Длительность: {duration}"]
    if uploader:
        lines.append(f"📺 {uploader}")
    return "\n".join(lines)


def _user_friendly_error(exc: DownloadError) -> str:
    if isinstance(exc, UnavailableError):
        return "🚫 Видео недоступно: приватное, удалено или ограничено по региону/возрасту."
    if isinstance(exc, TooLargeError):
        return texts.TOO_LARGE
    if "отменена" in str(exc).lower():
        return texts.CANCELLED
    if "таймаут" in str(exc).lower():
        return "⚠️ Превышено время ожидания. Попробуйте ещё раз."
    return f"⚠️ Не удалось выполнить: {exc}"


def setup_router(settings: Settings, pipeline: DeliveryPipeline) -> Router:
    """Собирает роутер с хендлерами, привязанными к настройкам и пайплайну."""
    r = Router(name="main")
    cache = MetadataCache(settings.metadata_cache_ttl_sec)
    busy: set[int] = set()

    # ---------- текстовые сообщения ----------

    @r.message(F.text)
    async def on_message(message: Message) -> None:
        text = message.text or ""
        chat_id = message.chat.id

        if not is_youtube_url(text) and "youtu" not in text.lower():
            await message.answer(texts.NOT_A_YOUTUBE_URL)
            return

        if chat_id in busy:
            await message.answer("⏳ Дождитесь завершения текущей загрузки.")
            return

        note = await message.answer(texts.FETCHING_INFO)

        try:
            normalized = normalize_youtube_url(text)
        except InvalidUrlError as exc:
            logger.info("Некорректный URL: %s (%s)", text[:100], exc)
            with contextlib.suppress(TelegramAPIError):
                await note.edit_text(texts.NOT_A_YOUTUBE_URL)
            return

        if normalized.video_id is None:
            with contextlib.suppress(TelegramAPIError):
                await note.edit_text(
                    "📋 Это ссылка на плейлист. Пришлите, пожалуйста, ссылку "
                    "на конкретное видео."
                )
            return

        logger.info("Запрос метаданных: chat_id=%s url=%s", chat_id, normalized.url)

        try:
            info = await _get_info(normalized.url, normalized.video_id)
        except UnavailableError:
            with contextlib.suppress(TelegramAPIError):
                await note.edit_text(
                    "🚫 Видео недоступно: приватное, удалено или ограничено "
                    "по региону/возрасту."
                )
            return
        except DownloadError as exc:
            logger.warning("Ошибка extract_info: %s", exc)
            with contextlib.suppress(TelegramAPIError):
                await note.edit_text(_user_friendly_error(exc))
            return

        duration = info.get("duration")
        max_duration = settings.max_video_duration_min * 60
        if isinstance(duration, (int, float)) and duration > max_duration:
            with contextlib.suppress(TelegramAPIError):
                await note.edit_text(
                    texts.DURATION_LIMIT.format(max_min=settings.max_video_duration_min)
                )
            return

        options = build_format_menu(
            info,
            audio_options=[(b, label) for b, _aac, label in settings.audio_options],
        )
        if not options:
            with contextlib.suppress(TelegramAPIError):
                await note.edit_text("⚠️ Доступные форматы не найдены.")
            return

        _last_payload[chat_id] = {
            "url": normalized.url,
            "video_id": normalized.video_id,
            "title": info.get("title"),
            "duration": info.get("duration"),
        }

        with contextlib.suppress(TelegramAPIError):
            await note.edit_text(
                _caption(info) + "\n\n<b>Выберите формат:</b>",
                reply_markup=keyboards.format_keyboard(options),
            )

    async def _get_info(url: str, video_id: str) -> dict:
        cached = await cache.get(video_id)
        if cached is not None:
            logger.debug("Кэш-попадание для %s", video_id)
            return cached
        info = await pipeline.ytdlp_client.extract_info(url)
        await cache.put(video_id, info)
        return info

    # ---------- callback-запросы ----------

    @r.callback_query()
    async def on_callback(callback: CallbackQuery) -> None:
        cb_type, payload = keyboards.parse_callback(callback.data)
        assert callback.message is not None
        chat_id = callback.message.chat.id

        if cb_type == keyboards.CB_CANCEL:
            cancelled = await pipeline.cancel_registry.cancel(chat_id)
            in_progress = chat_id in busy
            if in_progress:
                busy.discard(chat_id)
            await callback.answer()
            with contextlib.suppress(TelegramAPIError):
                await callback.message.edit_text(
                    texts.CANCELLED if (cancelled or in_progress) else texts.MENU_CLOSED
                )
            return

        if cb_type != keyboards.CB_DL:
            await callback.answer()
            return

        choice = keyboards.choice_from_payload(payload)
        if choice is None:
            await callback.answer("Неизвестный формат", show_alert=True)
            return

        stored = _last_payload.get(chat_id) or {}
        url = stored.get("url")
        if not url:
            await callback.answer("Ссылка устарела, пришлите её заново", show_alert=True)
            return

        if chat_id in busy:
            await callback.answer("Уже выполняется другая загрузка", show_alert=True)
            return

        busy.add(chat_id)
        status_msg = callback.message
        animator = ProgressAnimator(
            status_msg,
            max_edits=settings.max_progress_edits,
        )

        logger.info(
            "Старт загрузки: chat_id=%s kind=%s label=%s",
            chat_id,
            choice.kind,
            choice.label or choice.audio_bitrate_kbps,
        )

        def on_phase(phase: str) -> None:
            asyncio.ensure_future(
                animator.set_phase(phase, 0 if phase != "convert" else None)
            )

        def on_progress(percent: int) -> None:
            asyncio.ensure_future(animator.update(percent))

        try:
            await animator.set_phase("download", 0)
            result = await pipeline.deliver(
                url=url,
                chat_id=chat_id,
                choice=choice,
                caption=_caption_short(choice),
                duration=stored.get("duration"),
                title=(stored.get("title") if choice.kind == "audio" else None),
                performer=None,
                on_progress=on_progress,
                on_phase=on_phase,
            )
            logger.info(
                "Файл отправлен: chat_id=%s mode=%s bytes=%d",
                chat_id,
                result.mode,
                result.bytes_sent,
            )
            size_note = f" ({human_size(result.bytes_sent)})" if result.bytes_sent else ""
            await animator.finish(f"✅ Готово! Файл отправлен{size_note}.")
        except TelegramRetryAfter as exc:
            logger.warning("Flood control: retry after %ss", exc.retry_after)
            await animator.finish("⚠️ Слишком часто. Попробуйте позже.")
        except TooLargeError:
            await animator.finish(texts.TOO_LARGE)
        except DownloadError as exc:
            logger.warning("Ошибка загрузки: %s", exc)
            await animator.finish(_user_friendly_error(exc))
        except Exception:
            logger.exception("Неожиданная ошибка (chat_id=%s)", chat_id)
            await animator.finish(texts.SEND_FAILED)
        finally:
            busy.discard(chat_id)

    return r


def _caption_short(choice: FormatChoice) -> str:
    return f"Формат: {choice.label}" if choice.label else ""


__all__ = ["setup_router"]
