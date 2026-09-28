"""Загрузка файла в Telegram Bot API потоково (multipart/form-data streaming)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# Telegram может возвращать 200 с ok=false — проверяем поле ok.
# write-таймаут щедрый: загрузка большого файла может «молчать» долго.
_UPLOAD_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=900.0, pool=15.0)

_BOUNDARY = "ytb-boundary-7f3a9c2e5d"


def _build_preamble(fields: dict[str, str], file_field: str, filename: str, mime: str) -> bytes:
    """Начальная часть multipart-тела: текстовые поля + заголовок файловой части."""
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{_BOUNDARY}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    parts.append(
        (
            f"--{_BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
    )
    return b"".join(parts)


async def upload_stream_to_telegram(
    base_url: str,
    token: str,
    chat_id: int,
    kind: str,
    stream: AsyncIterator[bytes],
    caption: str | None = None,
    duration: int | None = None,
    title: str | None = None,
    performer: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """Отправляет поток в Telegram как video/audio.

    kind: 'video' | 'audio'. Файл передаётся потоково: не пишется на диск
    и не буферизуется в памяти целиком.
    """
    if kind == "video":
        method, file_field, filename, mime = "sendVideo", "video", "video.mp4", "video/mp4"
    elif kind == "audio":
        method, file_field, filename, mime = "sendAudio", "audio", "audio.mp3", "audio/mpeg"
    else:
        method, file_field, filename, mime = "sendDocument", "document", "file.bin", "application/octet-stream"

    url = f"{base_url}/bot{token}/{method}"

    fields: dict[str, str] = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption
    if duration:
        fields["duration"] = str(int(duration))
    if kind == "video":
        # Без width/height Telegram не показывает превью и стриминг,
        # supports_streaming включает прямое воспроизведение в клиентах.
        fields["supports_streaming"] = "true"
        if width:
            fields["width"] = str(int(width))
        if height:
            fields["height"] = str(int(height))
    if kind == "audio":
        if performer:
            fields["performer"] = performer
        if title:
            fields["title"] = title

    preamble = _build_preamble(fields, file_field, filename, mime)
    epilogue = f"\r\n--{_BOUNDARY}--\r\n".encode()

    async def body_iter() -> AsyncIterator[bytes]:
        yield preamble
        async for chunk in stream:
            yield chunk
        yield epilogue

    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
        request = client.build_request(
            "POST",
            url,
            content=body_iter(),
            headers={
                "Content-Type": f"multipart/form-data; boundary={_BOUNDARY}",
                "Connection": "close",
            },
        )
        try:
            response = await client.send(request)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ConnectionError(f"Ошибка сети при отправке в Telegram: {exc}") from exc

    body_text = response.text[:500]
    if response.status_code != 200:
        raise ConnectionError(f"Telegram API {response.status_code}: {body_text}")
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        raise ConnectionError(f"Неожиданный ответ Telegram API: {body_text}") from None

    if not payload.get("ok"):
        description = payload.get("description") or "неизвестная ошибка"
        raise ConnectionError(f"Telegram API: {description}")


__all__ = ["upload_stream_to_telegram"]
