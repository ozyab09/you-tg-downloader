"""Startup cleanup: удаляет tmpfs-хлам от прошлых запусков (после крашей)."""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

_STEM_RE = re.compile(r"^ytdl_[0-9a-f]{12}")


def cleanup_stale_tmp_files(tmp_dir: str) -> int:
    """Удаляет ytdl_* артефакты (.part, mp4, mp3, mkv...) из tmpfs.

    Если процесс был убит (OOM/SIGKILL/перезапуск watchfiles), в finally
    очистка не успевает выполниться — собираем мусор на старте.
    """
    removed = 0
    try:
        names = os.listdir(tmp_dir)
    except OSError as exc:
        logger.warning("Не удалось прочитать %s: %s", tmp_dir, exc)
        return 0

    for name in names:
        if not _STEM_RE.match(name):
            continue
        path = os.path.join(tmp_dir, name)
        try:
            os.unlink(path)
            removed += 1
        except OSError as exc:
            logger.warning("Не удалось удалить %s: %s", path, exc)

    if removed:
        logger.info("Startup cleanup: удалено временных файлов: %d", removed)
    return removed


__all__ = ["cleanup_stale_tmp_files"]
