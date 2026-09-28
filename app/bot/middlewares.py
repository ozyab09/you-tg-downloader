"""Middleware ограничения доступа (белый список Telegram user_id)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    """Пропускает апдейты только от разрешённых user_id.

    Если белый список пуст — бот отвечает всем (is_public). В противном случае
    апдейт игнорируется молча (без ответа пользователю) и логируется WARNING.
    """

    def __init__(self, allowed_ids: frozenset[int]) -> None:
        self._allowed_ids = allowed_ids
        self._public = not allowed_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            user = getattr(event, "from_user", None)

        if self._public:
            return await handler(event, data)

        if user is not None and user.id in self._allowed_ids:
            return await handler(event, data)

        user_id = user.id if user is not None else "unknown"
        logger.warning(
            "Отклонён доступ: user_id=%s не в белом списке (тип: %s)",
            user_id,
            type(event).__name__,
        )
        # Ничего не отвечаем — согласно ТЗ п. 2.5.
        return None


def _extract_chat_id(event: TelegramObject) -> int | None:
    if isinstance(event, Message):
        return event.chat.id
    if isinstance(event, CallbackQuery) and event.message:
        return event.message.chat.id
    return None


__all__ = ["WhitelistMiddleware"]
