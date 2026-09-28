<div align="center">

# 🎬 YouTube Downloader Bot

**Telegram-бот для скачивания видео и аудио с YouTube**

Скачивает видео до 4K и MP3, показывает живой анимированный прогресс,
работает через Docker в одну команду.

[![CI](https://github.com/ozyab09/you-tg-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/ozyab09/you-tg-downloader/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red)](https://github.com/yt-dlp/yt-dlp)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Tests](https://img.shields.io/badge/tests-46%20passed-brightgreen)](#-тесты)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Возможности](#-возможности) ·
[Быстрый старт](#-быстрый-старт) ·
[Конфигурация](#️-переменные-окружения) ·
[Архитектура](#-архитектура) ·
[Разработка](#-разработка)

</div>

---

## ✨ Возможности

| | |
|---|---|
| 🎬 **Видео** | MP4 (видео+аудио): 360p / 480p / 720p / 1080p / 1440p / 4K — только реально доступные варианты |
| 🎵 **Аудио** | MP3 128 / 192 / 320 kbps |
| ⭐ **Best** | «Лучшее доступное качество» одним нажатием |
| 📊 **Живой прогресс** | Анимированные фазы: `⬇️ Скачивание → 🔄 Конвертация → 📤 Отправка` со спиннером и процентами |
| ⛔ **Отмена** | Кнопка «Отмена» в любой момент загрузки |
| 🚀 **Гибридная доставка** | Стрим `yt-dlp → ffmpeg → Telegram` без записи на диск; fallback на tmpfs с очисткой в `finally` |
| 🔐 **Белый список** | Доступ только для разрешённых `user_id` (чужие — молча игнорируются + лог `WARNING`) |
| 💾 **Кэш метаданных** | TTL 5 минут — повторные запросы мгновенны |
| 🚦 **Лимиты** | Макс. размер файла и длительность видео через ENV, семафор параллельности |
| 🔁 **Dev-режим** | Код через volume + watchfiles: правки применяются без пересборки образа |

### Как это выглядит

```
⠹ Обработка видео…

✅ ⬇️ Скачивание: ▰▰▰▰▰▰▰▰▰▰▰▰▰▰ 100%
🔹 🔄 Конвертация
▫️ 📤 Отправка в Telegram
```

Три фазы обновляются в реальном времени (троттлинг ~3 сек соблюдает
флуд-лимиты Telegram), спиннер Брайля крутится на активной фазе.

## 🚀 Быстрый старт

```bash
git clone https://github.com/ozyab09/you-tg-downloader.git
cd you-tg-downloader

cp .env.example .env
# заполните TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ALLOW_IDS

docker compose up -d --build
docker compose logs -f bot
```

Где взять данные:
- **Токен бота** — [@BotFather](https://t.me/BotFather) → `/newbot`
- **Свой user_id** — [@userinfobot](https://t.me/userinfobot)

Затем просто пришлите боту ссылку на YouTube.

<details>
<summary><b>Запуск без Docker (для разработки)</b></summary>

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
sudo apt install ffmpeg        # или brew install ffmpeg

set -a; source .env; set +a
python3 -m app.main

# тесты и линтер
pytest
ruff check app tests
```

</details>

## ⚙️ Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|:---:|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Токен бота от @BotFather |
| `TELEGRAM_USER_ALLOW_IDS` | ⚠️ | пусто | Белый список user_id через запятую. Пусто = отвечать всем (не рекомендуется). Алиас: `ALLOWED_USER_IDS` |
| `MAX_FILE_SIZE_MB` | — | `50` | Максимальный размер отправляемого файла, МБ |
| `MAX_VIDEO_DURATION_MIN` | — | `30` | Максимальная длительность видео, минут |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `MAX_CONCURRENT_DOWNLOADS` | — | `2` | Сколько загрузок может идти одновременно |
| `METADATA_CACHE_TTL_SEC` | — | `300` | TTL кэша метаданных, секунд |
| `MAX_PROGRESS_EDITS` | — | `30` | Бюджет редактирований сообщения прогресса на одну загрузку |

## 📏 Лимиты Telegram Bot API

| Режим | Лимит на файл |
|---|---|
| Обычный Bot API (по умолчанию) | **50 МБ** |
| [Локальный Bot API Server](https://github.com/tdlib/telegram-bot-api) | **2 ГБ** |

Бот проверяет размер заранее (по метаданным) и по ходу загрузки; при превышении
предлагает выбрать качество ниже или аудио.

## 🏗️ Архитектура

```
app/
├── bot/
│   ├── handlers.py          # хендлеры: ссылки, меню, загрузка
│   ├── keyboards.py         # inline-клавиатуры, callback_data
│   ├── middlewares.py       # белый список user_id
│   ├── progress.py          # анимация фаз с процентами
│   └── texts.py             # тексты сообщений (RU)
├── downloader/
│   ├── ytdlp.py             # обёртка yt-dlp (метаданные, tmpfs-скачивание)
│   ├── streaming.py         # pipe yt-dlp → ffmpeg без диска
│   ├── telegram_upload.py   # multipart-стриминг в Bot API
│   ├── pipeline.py          # гибридная доставка, отмена, семафор
│   ├── formats.py           # фильтрация/выбор форматов
│   ├── cache.py             # TTL-кэш метаданных
│   └── errors.py            # типизированные ошибки
├── config/settings.py       # ENV-конфигурация
├── utils/                   # логирование, форматирование, валидация URL
└── main.py                  # точка входа (long polling)
```

**Поток данных (режим по умолчанию):**

```
yt-dlp -o - ──▶ ffmpeg (mp4 frag) ──▶ httpx multipart ──▶ Telegram Bot API
                    stream                  stream              50 MB limit
```

Аудио и fallback: yt-dlp рендерит файл в `/dev/shm` (tmpfs, только память ОС),
файл стримится в Bot API и **гарантированно удаляется в `finally`**.

## 🛠️ Разработка

Код монтируется в контейнер через volume (`./app:/app/app:ro`), процесс
запускается под [watchfiles](https://github.com/samuelcolvin/watchfiles):
правки в `app/` **автоматически перезапускают бота** — пересборка образа
не нужна:

```bash
docker compose up -d --build   # единственная сборка
# ... правьте файлы в app/ — бот перезапустится сам ...
docker compose logs -f bot     # смотрите перезапуски в логах
```

Пересборка нужна только при изменении `requirements.txt` или `Dockerfile`.

Правила вклада и PR-workflow — в [CONTRIBUTING.md](CONTRIBUTING.md),
правила для ИИ-агентов — в [AGENT.md](AGENT.md).

## 🔒 Безопасность

- Токен и user_id — только через ENV (`.env` в `.gitignore`)
- Валидация URL: whitelist доменов YouTube, запрет user-info и нестандартных
  портов (анти-SSRF) + повторная валидация yt-dlp
- Контейнер работает от непривилегированного пользователя `botuser`
- Логи только в stdout/stderr — ничего не пишется на диск

## 🧪 Тесты

```bash
pytest -v          # 46 тестов: URL-парсинг, форматы, клавиатуры, прогресс
ruff check app tests
```

Покрытие: валидация YouTube-ссылок (включая анти-SSRF кейсы), построение
меню форматов, roundtrip callback_data, аниматор прогресса (троттлинг,
бюджет правок, границы).

## 📄 Лицензия

[MIT](LICENSE)
