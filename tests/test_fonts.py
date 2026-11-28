"""换字体：只换目标字体真正有字形的字符。"""

from __future__ import annotations

from app.core import fonts


class _FakeFont:
    def __init__(self, chars: str) -> None:
        self._chars = set(chars)

    def has_glyph(self, code: int) -> bool:
        return chr(code) in self._chars


def test_retarget_keeps_characters_without_glyphs(monkeypatch):
    monkeypatch.setattr(fonts, "font", lambda _key: _FakeFont("abc "))
    assert fonts.retarget_runs([("中文 abc", "simsun")], "times") == [
        ("中文", "simsun"),
        (" abc", "times"),
    ]


def test_retarget_keeps_whole_run_when_nothing_is_supported(monkeypatch):
    monkeypatch.setattr(fonts, "font", lambda _key: _FakeFont(""))
    assert fonts.retarget_runs([("中文", "simsun")], "times") == [("中文", "simsun")]


def test_retarget_merges_adjacent_same_font_segments(monkeypatch):
    monkeypatch.setattr(fonts, "font", lambda _key: _FakeFont("ab"))
    assert fonts.retarget_runs([("a", "simsun"), ("b", "simsun")], "times") == [("ab", "times")]
