"""Тексты сообщений пользователю (русский язык, без технических деталей)."""

NOT_A_YOUTUBE_URL = (
    "Похоже, это не ссылка на YouTube 🤔\n"
    "Пришлите, пожалуйста, ссылку вида https://youtube.com/watch?v=... или https://youtu.be/..."
)

FETCHING_INFO = "🔎 Получаю информацию о видео…"

DOWNLOADING = "⬇️ Скачиваю…"

UPLOADING = "📤 Отправляю файл…"

CANCELLED = "❌ Задача отменена."

MENU_CLOSED = "Меню закрыто."

TOO_LARGE = (
    "⚠️ Файл слишком большой для отправки через Telegram Bot API "
    "(лимит 50 МБ). Попробуйте качество пониже или аудио."
)

SEND_FAILED = "⚠️ Не удалось отправить файл. Попробуйте ещё раз позже."

DURATION_LIMIT = (
    "⚠️ Видео длиннее {max_min} мин — не качаю. "
    "Лимит можно изменить через MAX_VIDEO_DURATION_MIN."
)

__all__ = [
    "NOT_A_YOUTUBE_URL",
    "FETCHING_INFO",
    "DOWNLOADING",
    "UPLOADING",
    "CANCELLED",
    "MENU_CLOSED",
    "TOO_LARGE",
    "SEND_FAILED",
    "DURATION_LIMIT",
]
