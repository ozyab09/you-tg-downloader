"""Форматирование длительности и размеров."""

from __future__ import annotations


def format_duration(seconds: int | float | None) -> str:
    """Секунды -> '1:02:03' / '5:04'. None или <=0 -> '—'."""
    if seconds is None:
        return "—"
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "—"
    if total <= 0:
        return "—"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def human_size(num_bytes: int | float | None) -> str:
    """Байты -> человекочитаемый размер ('12.3 МБ')."""
    if not num_bytes or num_bytes <= 0:
        return "—"
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            if unit == "Б":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


__all__ = ["format_duration", "human_size"]
