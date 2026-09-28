"""Тесты фильтрации форматов и клавиатур."""

from __future__ import annotations

from app.bot import keyboards
from app.downloader.formats import (
    FormatChoice,
    build_format_menu,
    video_selector_for_height,
)


def _info_with_heights(heights: list[int]) -> dict:
    formats = []
    for i, h in enumerate(heights):
        formats.append(
            {
                "format_id": str(100 + i),
                "vcodec": "avc1.640028",
                "acodec": "none",
                "height": h,
                "ext": "mp4",
                "protocol": "https",
            }
        )
    formats.append(
        {
            "format_id": "140",
            "vcodec": "none",
            "acodec": "mp4a.40.2",
            "ext": "m4a",
            "protocol": "https",
        }
    )
    return {"formats": formats}


class TestBuildFormatMenu:
    def test_only_available_heights_shown(self) -> None:
        # Доступны только 360 и 720 — не должно быть 480/1080/1440/2160.
        options = build_format_menu(_info_with_heights([360, 720]), [(128, "MP3 128")])
        video_labels = [o.label for o in options if hasattr(o, "height")]
        assert video_labels == ["360p", "720p (HD)"]

    def test_hls_excluded(self) -> None:
        info = _info_with_heights([720])
        info["formats"].append(
            {
                "format_id": "93",
                "vcodec": "avc1.64001f",
                "height": 720,
                "ext": "mp4",
                "protocol": "m3u8_native",
            }
        )
        options = build_format_menu(info, [])
        assert len([o for o in options if hasattr(o, "height")]) == 1

    def test_audio_always_present(self) -> None:
        options = build_format_menu(_info_with_heights([]), [(192, "MP3 192")])
        audio_labels = [o.label for o in options if not hasattr(o, "height")]
        assert audio_labels == ["MP3 192"]

    def test_empty_formats_no_video(self) -> None:
        options = build_format_menu({"formats": []}, [(128, "MP3 128")])
        assert all(not hasattr(o, "height") for o in options)


class TestCallbackData:
    def test_roundtrip_video(self) -> None:
        choice = FormatChoice(
            kind="video",
            format_id=video_selector_for_height(720),
            label="720p (HD)",
            height=720,
        )
        data = keyboards.cb_data_download(choice)
        cb_type, payload = keyboards.parse_callback(data)
        assert cb_type == keyboards.CB_DL
        restored = keyboards.choice_from_payload(payload)
        assert restored is not None
        assert restored.kind == "video"
        assert restored.format_id == video_selector_for_height(720)
        assert restored.height == 720

    def test_roundtrip_audio(self) -> None:
        choice = FormatChoice(
            kind="audio", format_id=None, label="MP3 320", audio_bitrate_kbps=320
        )
        data = keyboards.cb_data_download(choice)
        _cb_type, payload = keyboards.parse_callback(data)
        restored = keyboards.choice_from_payload(payload)
        assert restored is not None
        assert restored.kind == "audio"
        assert restored.audio_bitrate_kbps == 320

    def test_callback_data_length_limit(self) -> None:
        choice = FormatChoice(
            kind="video",
            format_id="bestvideo[height<=1080][vcodec!*=av01][vcodec!*=vp9.2]+bestaudio",
            label="1080p",
            height=1080,
        )
        data = keyboards.cb_data_download(choice)
        assert len(data.encode()) <= 64

    def test_parse_garbage(self) -> None:
        assert keyboards.parse_callback(None) == ("", {})
        assert keyboards.parse_callback("") == ("", {})
        assert keyboards.parse_callback("dl:not-json") == ("", {})
        assert keyboards.parse_callback(keyboards.CB_CANCEL) == (keyboards.CB_CANCEL, {})


class TestKeyboardLayout:
    def test_rows_structure(self) -> None:
        options = build_format_menu(
            _info_with_heights([360, 480, 720, 1080]),
            [(128, "MP3 128"), (320, "MP3 320")],
        )
        kb = keyboards.format_keyboard(options)
        texts_flat = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "⭐ Лучшее в лимите" in texts_flat
        assert "✖️ Закрыть" in texts_flat
        assert "MP3 128" in texts_flat and "MP3 320" in texts_flat


class TestSizeLimitFiltering:
    def test_formats_over_limit_not_shown(self) -> None:
        # Длинное видео: 360p ~60 МБ, 720p ~120 МБ при лимите 50 МБ.
        info = _info_with_heights([360, 720])
        info["duration"] = 1200  # 20 минут
        for f in info["formats"]:
            if f.get("vcodec") != "none":
                f["tbr"] = 350 if f["height"] == 360 else 750
        options = build_format_menu(info, [(128, "MP3 128")], size_limit_bytes=50 * 1024 * 1024)
        heights = [o.height for o in options if hasattr(o, "height")]
        assert heights == []  # оба варианта не влезают

    def test_small_format_within_limit_shown(self) -> None:
        info = _info_with_heights([360, 720])
        info["duration"] = 480  # 8 минут: 720p+аудио ~54 МБ > лимита, 360p ~31 МБ
        for f in info["formats"]:
            if f.get("vcodec") != "none":
                f["tbr"] = 350 if f["height"] == 360 else 750
        options = build_format_menu(info, [(128, "MP3 128")], size_limit_bytes=50 * 1024 * 1024)
        heights = [o.height for o in options if hasattr(o, "height")]
        assert heights == [360]  # 720p не влезает, 360p влезает

    def test_audio_over_limit_filtered(self) -> None:
        info = _info_with_heights([])
        info["duration"] = 3600  # час: даже 128k mp3 ~59 МБ
        options = build_format_menu(info, [(128, "MP3 128")], size_limit_bytes=50 * 1024 * 1024)
        assert options == []

    def test_no_limit_keeps_all(self) -> None:
        info = _info_with_heights([360, 720])
        info["duration"] = 1200
        options = build_format_menu(info, [(128, "MP3 128")], size_limit_bytes=None)
        assert len([o for o in options if hasattr(o, "height")]) == 2
