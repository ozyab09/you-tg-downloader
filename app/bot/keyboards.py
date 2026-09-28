"""Inline-клавиатуры и callback_data (словарь-строка, aiogram 3 без фабрик)."""

from __future__ import annotations

import json
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.downloader.formats import AudioOption, FormatChoice, VideoOption

# Префиксы callback_data
CB_MENU = "menu"
CB_DL = "dl"
CB_CANCEL = "cancel"

cb_data_menu = f"{CB_MENU}"
cb_data_cancel = f"{CB_CANCEL}"


def cb_data_download(choice: FormatChoice) -> str:
    """Сериализует выбор формата в callback_data (<=64 байта, лимит Telegram).

    Для видео сохраняем только высоту: селектор восстанавливается через
    video_selector_for_height (format_id длинный и не влезает в 64 байта).
    """
    payload: dict[str, Any] = {"k": choice.kind}
    if choice.height is not None:
        payload["h"] = choice.height
    if choice.audio_bitrate_kbps is not None:
        payload["b"] = choice.audio_bitrate_kbps
    return f"{CB_DL}:{json.dumps(payload, separators=(',', ':'), ensure_ascii=True)}"


def parse_callback(data: str | None) -> tuple[str, dict[str, Any]]:
    """Разбирает callback_data -> (тип, payload). Не бросает исключений."""
    if not data:
        return "", {}
    if data == CB_CANCEL:
        return CB_CANCEL, {}
    if data == CB_MENU:
        return CB_MENU, {}
    if data.startswith(f"{CB_DL}:"):
        try:
            payload = json.loads(data[len(CB_DL) + 1 :])
            if isinstance(payload, dict):
                return CB_DL, payload
        except json.JSONDecodeError:
            pass
    return "", {}


def choice_from_payload(payload: dict[str, Any]) -> FormatChoice | None:
    """Восстанавливает FormatChoice из payload callback_data."""
    kind = payload.get("k")
    if kind not in ("video", "audio", "best"):
        return None
    height = payload.get("h")
    bitrate = payload.get("b")
    format_id: str | None = None
    if kind == "video" and isinstance(height, int):
        from app.downloader.formats import video_selector_for_height

        format_id = video_selector_for_height(height)
    return FormatChoice(
        kind=kind,
        format_id=format_id,
        height=height if isinstance(height, int) else None,
        audio_bitrate_kbps=bitrate if isinstance(bitrate, int) else None,
        label="",
    )


def format_keyboard(
    options: list[VideoOption | AudioOption],
) -> InlineKeyboardMarkup:
    """Строит клавиатуру выбора формата: видео, «Лучшее», аудио + отмена."""
    video_buttons: list[InlineKeyboardButton] = []
    audio_buttons: list[InlineKeyboardButton] = []

    for opt in options:
        if isinstance(opt, VideoOption):
            size = f" · ~{opt.approx_size_bytes // (1024 * 1024)} МБ" if opt.approx_size_bytes else ""
            video_buttons.append(
                InlineKeyboardButton(
                    text=f"{opt.label}{size}",
                    callback_data=cb_data_download(
                        FormatChoice(
                            kind="video",
                            format_id=opt.format_id,
                            label=opt.label,
                            height=opt.height,
                        )
                    ),
                )
            )
        elif isinstance(opt, AudioOption):
            audio_buttons.append(
                InlineKeyboardButton(
                    text=opt.label,
                    callback_data=cb_data_download(
                        FormatChoice(
                            kind="audio",
                            format_id=None,
                            label=opt.label,
                            audio_bitrate_kbps=opt.bitrate_kbps,
                        )
                    ),
                )
            )

    rows: list[list[InlineKeyboardButton]] = []
    # До 4 видео-кнопок в ряду, «Лучшее» — отдельной кнопкой.
    for i in range(0, len(video_buttons), 4):
        rows.append(video_buttons[i : i + 4])
    rows.append(
        [
            InlineKeyboardButton(
                text="⭐ Лучшее доступное",
                callback_data=cb_data_download(
                    FormatChoice(kind="best", format_id=None, label="Best")
                ),
            )
        ]
    )
    if audio_buttons:
        rows.append(audio_buttons)
    rows.append(
        [
            InlineKeyboardButton(
                text="✖️ Закрыть",
                callback_data=CB_CANCEL,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой «Отмена» на время скачивания."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⛔ Отмена", callback_data=CB_CANCEL)]]
    )


# Псевдонимы для читаемости хендлеров
cb_menu = CB_MENU
cb_cancel = CB_CANCEL

__all__ = [
    "CB_CANCEL",
    "CB_DL",
    "CB_MENU",
    "cancel_keyboard",
    "cb_cancel",
    "cb_data_cancel",
    "cb_data_download",
    "cb_data_menu",
    "cb_menu",
    "choice_from_payload",
    "format_keyboard",
    "parse_callback",
]
