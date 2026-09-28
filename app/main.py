"""Точка входа Telegram-бота: long polling с авто-перезапуском и graceful shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from app.bot.handlers import setup_router
from app.bot.middlewares import WhitelistMiddleware
from app.config.settings import load_settings
from app.downloader.pipeline import DeliveryPipeline
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)

# Пауза между рестартами polling-цикла (экспоненциально, с потолком).
_RESTART_MIN_DELAY = 3.0
_RESTART_MAX_DELAY = 60.0


async def run() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)

    logger.info(
        "Старт бота; лимиты: %d МБ / %d мин",
        settings.max_file_size_mb,
        settings.max_video_duration_min,
    )
    if settings.is_public:
        logger.warning(
            "Белый список пуст — бот будет отвечать всем пользователям. "
            "Задайте TELEGRAM_USER_ALLOW_IDS (или ALLOWED_USER_IDS) в .env"
        )
    else:
        logger.info("Белый список: %d user_id", len(settings.allowed_user_ids))

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(name="root")

    pipeline = DeliveryPipeline(settings)

    # Белый список: на все апдейты (сообщения и callback-запросы).
    dp.update.middleware(WhitelistMiddleware(settings.allowed_user_ids))

    dp.include_router(setup_router(settings, pipeline))

    # Убираем вебхук, если был установлен ранее, иначе polling не работает.
    with contextlib.suppress(Exception):
        await bot.delete_webhook(drop_pending_updates=False)

    # Устойчивость к сетевым сбоям: обёртка вокруг start_polling с
    # экспоненциальной задержкой. aiogram сам ретраит кратковременные ошибки,
    # а сюда попадаем при фатальных для цикла сбоях (долгая потеря сети и т.п.).
    delay = _RESTART_MIN_DELAY
    while True:
        logger.info("Bot запущен: long polling")
        try:
            await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
            # start_polling вернулся без исключения — штатная остановка.
            logger.info("Polling остановлен штатно")
            break
        except TelegramNetworkError as exc:
            logger.warning("Сетевая ошибка polling: %s — рестарт через %.0f с", exc, delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Не роняем контейнер из-за разового сбоя: логируем и рестартуем.
            logger.exception("Неожиданная ошибка polling — рестарт через %.0f с", delay)

        await asyncio.sleep(delay)
        delay = min(_RESTART_MAX_DELAY, delay * 2)
        # aiogram закрывает сессию сам при выходе из start_polling — пересоздаём.
        bot.session = AiohttpSession()

    logger.info("Bot остановлен, сессия закрыта")


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка по сигналу")


if __name__ == "__main__":
    # Убеждаемся, что stdout/stderr не буферизуются (важно для docker logs).
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
