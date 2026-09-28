"""Тесты модуля анимации прогресса."""

from __future__ import annotations

from app.bot.progress import (
    PHASE_TITLES,
    ProgressAnimator,
    estimate_percent,
    percent_bar,
)


class TestPercentBar:
    def test_bounds(self) -> None:
        assert percent_bar(0) == "▱" * 14
        assert percent_bar(100) == "▰" * 14

    def test_half(self) -> None:
        bar = percent_bar(50, width=10)
        assert bar == "▰" * 5 + "▱" * 5

    def test_clamping(self) -> None:
        assert len(percent_bar(-5)) == 14
        assert len(percent_bar(150)) == 14


class TestEstimatePercent:
    def test_with_total(self) -> None:
        assert estimate_percent(50, 100) == 50
        assert estimate_percent(0, 100) == 0
        assert estimate_percent(200, 100) == 100

    def test_without_total_saturates(self) -> None:
        small = estimate_percent(1024, None)
        big = estimate_percent(500 * 1024 * 1024, None)
        assert 0 <= small < big <= 100


class _FakeMessage:
    """Минимальная заглушка Message для тестов редактирования."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def edit_text(self, text: str, **kwargs: object) -> None:
        self.texts.append(text)


class TestProgressAnimator:
    async def test_finish_edits_message(self) -> None:
        msg = _FakeMessage()
        anim = ProgressAnimator(msg, min_interval=0.0)  # type: ignore[arg-type]
        await anim.finish("✅ Готово!")
        assert msg.texts == ["✅ Готово!"]
        assert anim.edits_made == 1

    async def test_set_phase_renders_all_phases(self) -> None:
        msg = _FakeMessage()
        anim = ProgressAnimator(msg, min_interval=0.0)  # type: ignore[arg-type]
        await anim.set_phase("upload", 40)
        text = msg.texts[-1]
        for phase_title in PHASE_TITLES.values():
            assert phase_title in text
        assert "40%" in text

    async def test_throttling_limits_edits(self) -> None:
        msg = _FakeMessage()
        anim = ProgressAnimator(msg, min_interval=60.0)  # type: ignore[arg-type]
        await anim.set_phase("download", 0)  # force — первое редактирование
        for p in range(1, 10):
            await anim.update(p)  # все попадают в окно троттлинга
        assert anim.edits_made == 1

    async def test_max_edits_budget(self) -> None:
        msg = _FakeMessage()
        anim = ProgressAnimator(msg, min_interval=0.0, max_edits=3)  # type: ignore[arg-type]
        for p in (0, 25, 50, 75, 100):
            await anim.set_phase("download", p)
        assert anim.edits_made <= 3

    async def test_null_message_safe(self) -> None:
        anim = ProgressAnimator(None)
        await anim.set_phase("upload", 10)  # не бросает
        await anim.finish("ok")  # не бросает
