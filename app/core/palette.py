"""文本框与荧光笔的调色板。

色值取自 Edge 的 PDF 批注——从参考文件里的 ``/C`` 数组逐个读出来的，
不是自己挑的。前端只认这里的键，具体十六进制由快照下发，避免两边各写一份。
"""

from __future__ import annotations

TEXT_COLORS: dict[str, str] = {
    "blue": "#0078D4",
    "red": "#CC0000",
    "green": "#107C10",
}

HIGHLIGHT_COLORS: dict[str, str] = {
    "yellow": "#FFF066",
    "green": "#107C10",
    "blue": "#0078D4",
    "red": "#CC0000",
}

DEFAULT_TEXT_COLOR = "blue"
DEFAULT_HIGHLIGHT_COLOR = "yellow"


def _rgb(value: str) -> tuple[float, float, float]:
    text = value.lstrip("#")
    return (
        int(text[0:2], 16) / 255.0,
        int(text[2:4], 16) / 255.0,
        int(text[4:6], 16) / 255.0,
    )


def text_rgb(key: str) -> tuple[float, float, float]:
    return _rgb(TEXT_COLORS.get(key, TEXT_COLORS[DEFAULT_TEXT_COLOR]))


def highlight_rgb(key: str) -> tuple[float, float, float]:
    return _rgb(HIGHLIGHT_COLORS.get(key, HIGHLIGHT_COLORS[DEFAULT_HIGHLIGHT_COLOR]))


def normalize_text(key: object) -> str:
    text = str(key).strip() if key is not None else ""
    return text if text in TEXT_COLORS else DEFAULT_TEXT_COLOR


def normalize_highlight(key: object) -> str:
    text = str(key).strip() if key is not None else ""
    return text if text in HIGHLIGHT_COLORS else DEFAULT_HIGHLIGHT_COLOR


def palette_payload() -> dict[str, list[dict[str, str]]]:
    return {
        "text": [{"key": key, "hex": value} for key, value in TEXT_COLORS.items()],
        "highlight": [{"key": key, "hex": value} for key, value in HIGHLIGHT_COLORS.items()],
    }
