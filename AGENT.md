# AGENT.md — правила для ИИ-агентов

Инструкции для ИИ-агентов (Codebuff, Copilot, Claude Code и др.), работающих
с этим репозиторием. Люди — см. [README.md](README.md) и [CONTRIBUTING.md](CONTRIBUTING.md).

## Суть проекта

Telegram-бот для скачивания видео/аудио с YouTube: aiogram 3.x (long polling),
yt-dlp + ffmpeg, гибридная доставка (стрим в Bot API без диска, fallback на
tmpfs `/dev/shm`), белый список user_id, конфиг только через ENV, Docker Compose.

## Как запустить и проверить

```bash
# Зависимости (системный Python, venv может отсутствовать)
python3 -m pip install -r requirements.txt -r requirements-dev.txt

# Тесты и линтер — ОБЯЗАТЕЛЬНЫ перед каждым коммитом
python3 -m pytest            # 46 тестов, все должны быть зелёные
python3 -m ruff check app tests

# Локальный запуск (нужен .env с TELEGRAM_BOT_TOKEN)
docker compose up -d --build && docker compose logs -f bot
```

## Структура

```
app/
├── bot/          # handlers.py (хендлеры), keyboards.py, middlewares.py (whitelist),
│                 # progress.py (анимация фаз), texts.py (все тексты RU)
├── downloader/   # ytdlp.py, streaming.py, telegram_upload.py, pipeline.py,
│                 # formats.py, cache.py, errors.py
├── config/       # settings.py — единственная точка чтения ENV
├── utils/        # logging.py, formatting.py, url.py (валидация + анти-SSRF)
└── main.py       # точка входа
```

## Жёсткие правила

1. **Никогда не читайте, не логируйте и не коммитьте `.env`** — там токен бота.
   Он в `.gitignore`; не добавляйте его в индекс и не вставляйте значения в код.
2. **Вся конфигурация — только через ENV** (`app/config/settings.py`).
   Никаких хардкодов токенов, ID, URL-адресов API в коде.
3. **Ветки и PR.** Прямые пуши в `main` запрещены branch protection:
   изменения только через PR; CI (ruff + pytest на 3.12 + docker build) обязателен.
   Имена веток: `feat/…`, `fix/…`, `chore/…`, `docs/…`; коммиты — Conventional Commits.
4. **Пользователь вне белого списка не получает НИКАКОГО ответа** — это требование
   ТЗ (п. 2.5). Не добавляйте «вежливые отказы» в `WhitelistMiddleware`.
5. **Временные файлы — только в tmpfs (`/dev/shm`)** и удаление гарантированно
   в `finally` (`_cleanup_stem`). Не пишите медиа в рабочую директорию контейнера.
6. **Логи — только stdout/stderr**, формат `%(asctime)s | %(levelname)s | %(name)s | %(message)s`
   (`app/utils/logging.py`). Никаких файловых хендлеров.
7. **Тексты пользователю — на русском**, без технических деталей и stacktrace —
   только через `app/bot/texts.py` и `_user_friendly_error()`.
8. **URL валидируется белым списком доменов** (`app/utils/url.py`).
   Новые домены/схемы — только осознанно, это анти-SSRF барьер.

## Конвенции кода

- Python 3.12, типизация обязательна на публичных функциях/методах.
- Асинхронность: блокирующие вызовы (yt-dlp, файлы) — через `asyncio.to_thread`
  / `run_in_executor`; не блокировать event loop.
- `ruff check app tests` должен быть чистым (0 ошибок).
- Новая функциональность — с тестами в `tests/`; тесты не требуют сети и токенов.
- Прогресс в UI редактируется с троттлингом ~3 c (`ProgressAnimator`) — не
  убирайте троттлинг, иначе словите flood control от Telegram.
- callback_data ≤ 64 байта: не кладите туда длинные format_id, только `k`/`h`/`b`.

## Типичные ошибки, которые уже ловили

- **Устаревший yt-dlp** → `The page needs to be reloaded`. Держите
  `yt-dlp>=2026.7.4` свежим; не пинуйте старые версии.
- **Нет JS-рантайма (deno) в образе** → YouTube отдаёт не все форматы.
  deno ставится в Dockerfile — не удаляйте.
- **`ModuleNotFoundError: No module named 'app'` в CI** → решается
  `pythonpath = .` в `pytest.ini`, не полагайтесь на cwd раннера.
- **ENV-имя белого списка**: основное `TELEGRAM_USER_ALLOW_IDS`,
  алиас `ALLOWED_USER_IDS` (см. `load_settings`).

## Что где менять (шпаргалка)

| Задача | Файл |
|---|---|
| Тексты сообщений бота | `app/bot/texts.py` |
| Кнопки/меню форматов | `app/bot/keyboards.py`, `app/downloader/formats.py` |
| Логика скачивания/отправки | `app/downloader/pipeline.py` |
| Стриминг без диска | `app/downloader/streaming.py` |
| Анимация прогресса | `app/bot/progress.py` |
| Новые ENV-переменные | `app/config/settings.py` + `.env.example` + README (таблица) |
| Лимиты по умолчанию | `app/config/settings.py` (`Settings`) |

## Перед завершением задачи

1. `python3 -m pytest` — зелёный.
2. `python3 -m ruff check app tests` — чисто.
3. Если меняли ENV — обновлены `.env.example` и таблица в README.
4. Если меняли Dockerfile/зависимости — `docker compose build` проходит.
5. Коммит через PR в ветку `feat/…`/`fix/…`, не напрямую в `main`.
