"""Тесты парсинга YouTube-ссылок."""

from __future__ import annotations

import pytest

from app.utils.url import InvalidUrlError, is_youtube_url, normalize_youtube_url


class TestValidUrls:
    @pytest.mark.parametrize(
        ("raw", "vid"),
        [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            (
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s",
                "dQw4w9WgXcQ",
            ),
            (
                "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
                "dQw4w9WgXcQ",
            ),
        ],
    )
    def test_valid(self, raw: str, vid: str) -> None:
        normalized = normalize_youtube_url(raw)
        assert normalized.video_id == vid

    def test_is_youtube(self) -> None:
        assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        assert not is_youtube_url("https://example.com/watch?v=dQw4w9WgXcQ")


class TestInvalidUrls:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            None,
            "просто текст",
            "https://example.com/video",
            "https://vimeo.com/123456",
            "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/shortid",
            "https://www.youtube.com/watch",
            "ftp://youtu.be/dQw4w9WgXcQ",
            "https://user:pass@youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com:8080/watch?v=dQw4w9WgXcQ",
        ],
    )
    def test_invalid(self, raw: str | None) -> None:
        with pytest.raises(InvalidUrlError):
            normalize_youtube_url(raw)

    def test_playlist_link_detected(self) -> None:
        normalized = normalize_youtube_url(
            "https://www.youtube.com/playlist?list=PL1234567890abcdef"
        )
        assert normalized.video_id is None
        assert normalized.playlist_id == "PL1234567890abcdef"

    def test_watch_with_playlist_still_video(self) -> None:
        normalized = normalize_youtube_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxyz"
        )
        assert normalized.video_id == "dQw4w9WgXcQ"
        assert normalized.playlist_id == "PLxyz"
