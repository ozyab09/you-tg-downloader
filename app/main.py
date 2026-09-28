"""Точка входа Telegram-бота: long polling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.bot.handlers import setup_router
from app.bot.middlewares import WhitelistMiddleware
from app.config.settings import load_settings
from app.downloader.pipeline import DeliveryPipeline
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)

    logger.info(
        "Старт бота; лимиты: %d МБ / %d мин; Bot API: %s",
        settings.max_file_size_mb,
        settings.max_video_duration_min,
        settings.api_base_url,
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
        session=AiohttpSession(api=settings.api_base_url),
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

    logger.info("Bot запущен: long polling")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        logger.info("Bot остановлен, сессия закрыта")


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    # Убеждаемся, что stdout/stderr не буферизуются (важно для docker logs).
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
