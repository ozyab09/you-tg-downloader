FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg нужен yt-dlp для мерджа видео+аудио и конвертации в MP3.
# deno — JS-рантайм для yt-dlp (EJS): без него YouTube отдаёт не все форматы.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    && unzip -o /tmp/deno.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/deno \
    && rm -f /tmp/deno.zip \
    && deno --version

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Код копируется в образ, чтобы он был самодостаточным (можно запустить
# без volume, например на сервере без репозитория). В docker-compose этот
# слой перекрывается монтированием ./app:/app/app:ro для dev-перезагрузки.
COPY app ./app

# Непривилегированный пользователь.
RUN useradd --create-home --shell /usr/sbin/nologin botuser \
    && chown -R botuser:botuser /app
USER botuser

# /dev/shm используется для временных файлов (tmpfs в docker compose).
RUN mkdir -p /tmp/ytdl

CMD ["python", "-m", "app.main"]
