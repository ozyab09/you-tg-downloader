"""Построение меню форматов и логика выбора/фильтрации форматов yt-dlp."""

from __future__ import annotations

from dataclasses import dataclass

YOUTUBE_HEIGHTS: tuple[int, ...] = (360, 480, 720, 1080, 1440, 2160)

# Строчная метка высоты, как её видит пользователь.
_HEIGHT_LABELS: dict[int, str] = {
    360: "360p",
    480: "480p",
    720: "720p (HD)",
    1080: "1080p (Full HD)",
    1440: "1440p",
    2160: "4K (2160p)",
}


@dataclass(frozen=True)
class VideoOption:
    """Доступный вариант видео с аудиодорожкой."""

    format_id: str
    height: int
    label: str
    ext: str = "mp4"
    approx_size_bytes: int | None = None


@dataclass(frozen=True)
class AudioOption:
    """Доступный вариант аудио."""

    bitrate_kbps: int
    label: str
    approx_size_bytes: int | None = None


@dataclass(frozen=True)
class FormatChoice:
    """Выбор пользователя: видео или аудио."""

    kind: str  # "video" | "audio" | "best"
    format_id: str | None  # None для "best" и для аудио (рендерится через ffmpeg)
    label: str
    height: int | None = None  # для видео
    audio_bitrate_kbps: int | None = None  # для аудио


def label_for_height(height: int) -> str:
    return _HEIGHT_LABELS.get(height, f"{height}p")


def video_selector_for_height(height: int) -> str:
    """Единый селектор yt-dlp для видео с аудио заданной высоты.

    Используется и при построении меню, и при восстановлении выбора из
    callback_data (чтобы не превышать лимит 64 байта).
    """
    return (
        f"bestvideo[height<={height}][vcodec!*=av01][vcodec!*=vp9.2]+bestaudio"
    )


def _video_size_bytes(fmt: dict) -> int | None:
    """Оценка размера видео-потока: filesize или filesize*duration/аналог tbr."""
    filesize = fmt.get("filesize") or fmt.get("filesize_approx")
    if isinstance(filesize, (int, float)) and filesize > 0:
        return int(filesize)

    tbr = fmt.get("tbr")
    duration = fmt.get("duration")
    if isinstance(tbr, (int, float)) and tbr > 0 and isinstance(duration, (int, float)):
        return int(tbr * 1000 / 8 * duration)

    return None


def build_format_menu(
    info: dict,
    audio_options: list[tuple[int, str]],
) -> list[VideoOption | AudioOption]:
    """Возвращает список доступных вариантов для меню.

    - video: варианты, для которых существует ffmpeg-мердж с высотой <= requested
      (yt-dlp сам берёт ближайший доступный ниже, если точная высота отсутствует).
    - audio: перечисленные битрейты (рендерятся через ffmpeg, всегда доступны).
    """
    formats: list[dict] = info.get("formats") or []

    available_heights: set[int] = set()
    for fmt in formats:
        vcodec = fmt.get("vcodec") or "none"
        if vcodec == "none":
            continue
        height = fmt.get("height")
        if not isinstance(height, int) or height <= 0:
            continue
        protocol = (fmt.get("protocol") or "").lower()
        if protocol in ("m3u8", "m3u8_native"):
            # HLS-потоки не совместимы с --merge-output-format mp4 при pipe-мердже.
            continue
        available_heights.add(height)

    options: list[VideoOption | AudioOption] = []

    for requested in YOUTUBE_HEIGHTS:
        # Берём ближайшую доступную высоту >= запрошенной... нет: <= запрошенной.
        candidates = [h for h in available_heights if h <= requested]
        if not candidates:
            continue
        best = max(candidates)
        if any(opt.height == best for opt in options if isinstance(opt, VideoOption)):
            continue
        options.append(
            VideoOption(
                format_id=video_selector_for_height(best),
                height=best,
                label=label_for_height(best),
            )
        )

    options.sort(key=lambda opt: opt.height if isinstance(opt, VideoOption) else 0)

    for bitrate_kbps, label in audio_options:
        options.append(
            AudioOption(
                bitrate_kbps=bitrate_kbps,
                label=label,
            )
        )

    return options


def pick_quality_height(height: int | None, available: list[int]) -> int | None:
    """Возвращает ближайшую доступную высоту <= запрошенной (или None)."""
    if height is None:
        return None
    candidates = [h for h in available if h <= height]
    return max(candidates) if candidates else None


__all__ = [
    "AudioOption",
    "FormatChoice",
    "VideoOption",
    "YOUTUBE_HEIGHTS",
    "build_format_menu",
    "label_for_height",
    "pick_quality_height",
    "video_selector_for_height",
]
