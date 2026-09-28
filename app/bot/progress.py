"""Анимация прогресса: фазы скачивание → конвертация → отправка.

Анимация строится как текст и отправляется через edit_text с троттлингом
(лимиты Telegram: ~1 редактирование/сек на сообщение, flood control).
"""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import Message

logger = logging.getLogger(__name__)

# Спиннер Брайля — плавная анимация.
SPINNER_FRAMES: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

PHASE_TITLES: dict[str, str] = {
    "download": "⬇️ Скачивание",
    "convert": "🔄 Конвертация",
    "upload": "📤 Отправка в Telegram",
}

# Интервал между редактированиями (флуд-контроль Telegram).
MIN_EDIT_INTERVAL_SEC = 3.0


def percent_bar(percent: int, width: int = 14) -> str:
    """Текстовый прогресс-бар: ▰▰▰▱▱▱."""
    clamped = max(0, min(100, percent))
    filled = round(clamped * width / 100)
    return "▰" * filled + "▱" * (width - filled)


def _phase_line(phase: str, percent: int | None, active: bool, done: bool) -> str:
    title = PHASE_TITLES[phase]
    if done:
        marker = "✅"
    elif active:
        marker = "🔹"
    else:
        marker = "▫️"
    if percent is None:
        return f"{marker} {title}"
    return f"{marker} {title}: {percent_bar(percent)} {max(0, min(100, percent))}%"


class ProgressAnimator:
    """Редактирует одно сообщение, показывая фазы с процентами и спиннером.

    Использование:
        anim = ProgressAnimator(status_message)
        await anim.set_phase("download", 0)
        await anim.update(percent=42)          # внутри download-фазы
        await anim.set_phase("convert")        # индикация без процентов
        await anim.set_phase("upload", 0)
        await anim.update(percent=80)
        await anim.finish("✅ Готово!")
    """

    def __init__(
        self,
        message: Message | None,
        *,
        min_interval: float = MIN_EDIT_INTERVAL_SEC,
        max_edits: int = 30,
        clock: object | None = None,  # зарезервировано для тестов
    ) -> None:
        self._message = message
        self._min_interval = min_interval
        self._max_edits = max_edits
        self._edits = 0
        self._last_edit_at = 0.0
        self._phase = "download"
        self._percent: int | None = 0
        self._done_phases: set[str] = set()
        self._pending: int | None = None  # процент, отложенный из-за троттлинга
        self._frame = 0
        self._closed = False

    # ---------- публичный API ----------

    async def set_phase(self, phase: str, percent: int | None = None) -> None:
        """Переключает фазу; предыдущая помечается выполненной."""
        if self._phase in PHASE_TITLES:
            self._done_phases.add(self._phase)
        self._phase = phase
        self._percent = percent
        await self._render(force=True)

    async def update(self, percent: int) -> None:
        """Обновляет процент текущей фазы (с троттлингом)."""
        self._percent = percent
        await self._render(force=False)

    async def finish(self, text: str) -> None:
        """Финальное состояние (без анимации)."""
        self._closed = True
        if self._message is None:
            return
        await self._edit(text, force=True)

    @property
    def edits_made(self) -> int:
        return self._edits

    # ---------- внутреннее ----------

    def _build_text(self) -> str:
        order = ["download", "convert", "upload"]
        lines = []
        spinner = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        for idx, phase in enumerate(order):
            is_active = phase == self._phase
            is_done = phase in self._done_phases
            if is_active and not is_done:
                lines.append(_phase_line(phase, self._percent, True, False))
            elif is_done:
                lines.append(_phase_line(phase, 100, False, True))
            else:
                lines.append(_phase_line(phase, None, False, False))
            if is_active and idx < len(order) - 1:
                pass
        text = "\n".join(lines)
        # Спиннер на отдельной строке заголовка активной фазы не нужен:
        # добавляем общий заголовок со спиннером.
        header = f"{spinner} <b>Обработка видео…</b>"
        return f"{header}\n\n{text}"

    async def _render(self, *, force: bool) -> None:
        if self._closed or self._message is None:
            return
        now = time.monotonic()
        if not force and now - self._last_edit_at < self._min_interval:
            self._pending = self._percent
            return
        if self._edits >= self._max_edits:
            return
        self._frame += 1
        await self._edit(self._build_text(), force=force)

    async def _edit(self, text: str, *, force: bool) -> None:
        assert self._message is not None
        try:
            await self._message.edit_text(text)
        except TelegramRetryAfter as exc:
            # Telegram сам сказал подождать — ждём ровно сколько нужно.
            logger.debug("Flood control: пауза %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 0.5)
            try:
                await self._message.edit_text(text)
            except TelegramAPIError:
                return
        except TelegramBadRequest:
            # "message is not modified" и т.п. — безопасно игнорируем.
            return
        except TelegramAPIError as exc:
            logger.debug("Не удалось обновить прогресс: %s", exc)
            return
        self._edits += 1
        self._last_edit_at = time.monotonic()
        self._pending = None if force else self._pending


def estimate_percent(
    done_bytes: int,
    total_bytes: int | None,
    *,
    fallback_span: tuple[int, int] = (10, 95),
) -> int:
    """Процент по байтам; если total неизвестен — ползёт от fallback_span[0] к [1]."""
    if total_bytes and total_bytes > 0:
        return int(max(0, min(100, done_bytes * 100 // total_bytes)))
    # Неизвестный общий размер: линейно насыщающийся прогресс.
    span = fallback_span[1] - fallback_span[0]
    fraction = 1 - 1 / (1 + done_bytes / (5 * 1024 * 1024))  # насыщение к 1
    return int(fallback_span[0] + span * min(1.0, fraction))


__all__ = [
    "PHASE_TITLES",
    "ProgressAnimator",
    "SPINNER_FRAMES",
    "estimate_percent",
    "percent_bar",
]
