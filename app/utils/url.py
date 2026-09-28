"""Нормализация и валидация YouTube-ссылок (защита от SSRF / чужих доменов)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
    }
)

_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTU_BE_PATH_RE = re.compile(r"^/([A-Za-z0-9_-]{11})(?:[/?&#]|$)")


class InvalidUrlError(ValueError):
    """URL не распознан как валидная ссылка на YouTube-видео."""


class NormalizedUrl:
    """Результат нормализации: id видео и/или id плейлиста."""

    __slots__ = ("video_id", "playlist_id", "url")

    def __init__(self, video_id: str | None, playlist_id: str | None, url: str) -> None:
        self.video_id = video_id
        self.playlist_id = playlist_id
        self.url = url

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"NormalizedUrl(video_id={self.video_id!r}, "
            f"playlist_id={self.playlist_id!r})"
        )


def _match_video_id(candidate: str | None) -> str | None:
    if candidate and _YOUTUBE_ID_RE.match(candidate):
        return candidate
    return None


def is_youtube_url(raw: str | None) -> bool:
    """Быстрая проверка: строка похожа на ссылку YouTube на видео."""
    if not raw:
        return False
    try:
        normalized = normalize_youtube_url(raw)
    except (InvalidUrlError, ValueError):
        return False
    return normalized.video_id is not None


def normalize_youtube_url(raw: str | None) -> NormalizedUrl:
    """Разбирает сырую строку и возвращает NormalizedUrl.

    Бросает InvalidUrlError, если это не YouTube-ссылка на видео или плейлист.
    """
    if not raw or not raw.strip():
        raise InvalidUrlError("Пустая ссылка")

    text = raw.strip()
    if "://" not in text:
        text = "https://" + text.lstrip("/")

    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()

    if scheme not in ("http", "https"):
        raise InvalidUrlError("Неверная схема URL")

    if host not in ALLOWED_HOSTS:
        raise InvalidUrlError(f"Домен '{host or '?'}' не входит в белый список YouTube")

    # Whitelist по имени хоста защищает от обхода через credentials.
    if parsed.username or parsed.password:
        raise InvalidUrlError("URL содержит user-info, такие ссылки не принимаются")

    if parsed.port is not None and parsed.port not in (80, 443):
        raise InvalidUrlError(f"Нестандартный порт {parsed.port} не разрешён")

    query = parse_qs(parsed.query)
    playlist_id = (query.get("list") or [None])[0]
    video_id: str | None = None

    if host == "youtu.be":
        match = _YOUTU_BE_PATH_RE.match(parsed.path)
        video_id = _match_video_id(match.group(1)) if match else None
        if video_id is None and playlist_id:
            return NormalizedUrl(video_id=None, playlist_id=playlist_id, url=text)
        if video_id is None:
            raise InvalidUrlError("Ссылка youtu.be без идентификатора видео")
    else:
        if re.match(r"^/watch$", parsed.path, re.IGNORECASE):
            video_id = _match_video_id((query.get("v") or [None])[0])
        if video_id is None:
            match_shorts = re.match(
                r"^/(shorts|live|embed|v)/([A-Za-z0-9_-]{11})", parsed.path
            )
            if match_shorts:
                video_id = _match_video_id(match_shorts.group(2))
        if video_id is None and playlist_id:
            return NormalizedUrl(video_id=None, playlist_id=playlist_id, url=text)
        if video_id is None:
            raise InvalidUrlError("В ссылке нет идентификатора видео")

    if video_id is not None and not _YOUTUBE_ID_RE.match(video_id):
        raise InvalidUrlError("Неверный идентификатор видео")

    return NormalizedUrl(video_id=video_id, playlist_id=playlist_id, url=text)


__all__ = [
    "ALLOWED_HOSTS",
    "InvalidUrlError",
    "NormalizedUrl",
    "is_youtube_url",
    "normalize_youtube_url",
]
