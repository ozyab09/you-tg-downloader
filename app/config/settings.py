"""Загрузка конфигурации из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import PurePath


def _parse_allowed_ids(raw: str) -> frozenset[int]:
    """Разбирает строку '111, 222' в frozenset[int]. Пустая строка -> пустое множество."""
    if not raw or not raw.strip():
        return frozenset()
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            # Некорректные элементы молча пропускаем, чтобы одна опечатка не роняла запуск.
            continue
    return frozenset(result)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        value = default
    return max(minimum, value)


@dataclass(frozen=True)
class Settings:
    """Все настройки бота. Единственный источник — переменные окружения."""

    bot_token: str
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)

    # Базовый URL Bot API: обычный облачный или локальный сервер (2 ГБ).
    api_base_url: str = "https://api.telegram.org"

    max_file_size_mb: int = 50          # лимит Telegram Bot API
    max_video_duration_min: int = 30
    log_level: str = "INFO"

    max_concurrent_downloads: int = 2   # общий семафор
    metadata_cache_ttl_sec: int = 300   # 5 минут
    max_progress_edits: int = 20        # бюджет редактирований на загрузку

    # Варианты аудио: (битрейт kbps, aac bitrate для ffmpeg, label для кнопки)
    audio_options: tuple[tuple[int, int, str], ...] = (
        (128, "128k", "MP3 128"),
        (192, "192k", "MP3 192"),
        (320, "320k", "MP3 320"),
    )

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def is_public(self) -> bool:
        """True, если белый список не задан (бот отвечает всем)."""
        return not self.allowed_user_ids


def load_settings() -> Settings:
    """Читает ENV и валидирует обязательные значения. Падает при отсутствии токена."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Переменная окружения TELEGRAM_BOT_TOKEN не задана. "
            "Скопируйте .env.example в .env и заполните её."
        )

    # Основное имя — TELEGRAM_USER_ALLOW_IDS; поддерживается алиас ALLOWED_USER_IDS
    # (приоритет у основного имени).
    allowed_raw = os.environ.get("TELEGRAM_USER_ALLOW_IDS", "") or os.environ.get(
        "ALLOWED_USER_IDS", ""
    )
    allowed = _parse_allowed_ids(allowed_raw)

    # Локальный Bot API Server: включается явно через TELEGRAM_API_BASE_URL
    # (в docker-compose это http://telegram-bot-api:8081). Лимит файла там 2 ГБ,
    # поэтому дефолт MAX_FILE_SIZE_MB повышаем, если пользователь не задал свой.
    api_base_url = os.environ.get("TELEGRAM_API_BASE_URL", "").strip().rstrip("/")
    default_max_mb = 2000 if api_base_url else 50

    return Settings(
        bot_token=token,
        allowed_user_ids=allowed,
        api_base_url=api_base_url or "https://api.telegram.org",
        max_file_size_mb=_env_int("MAX_FILE_SIZE_MB", default_max_mb, minimum=1),
        max_video_duration_min=_env_int("MAX_VIDEO_DURATION_MIN", 30, minimum=1),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        max_concurrent_downloads=_env_int("MAX_CONCURRENT_DOWNLOADS", 2, minimum=1),
        metadata_cache_ttl_sec=_env_int("METADATA_CACHE_TTL_SEC", 300, minimum=5),
        max_progress_edits=_env_int("MAX_PROGRESS_EDITS", 20, minimum=1),
    )


__all__ = ["PurePath", "Settings", "load_settings"]
