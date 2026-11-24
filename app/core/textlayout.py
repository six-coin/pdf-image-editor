"""文本排版。

纯函数：给定若干文字段（每段一个字体）、文本框宽度、字号、行高倍数，算出
每一行从哪儿开始、每个字段落在哪个 x、基线在哪儿。

坐标一律是 pt，原点在文本框左上角。字号用 px 表示（与 Edge 的批注一致，
1px = 0.75pt），行高是字号的倍数。

换行规则与浏览器在 ``white-space: pre-wrap`` + ``font-kerning: none`` 下的行为
同构：中文逐字断、西文按词断、超长词硬断、空格不吃到行尾。两边都用同一份
字体的 advance 宽度，所以断行点一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core import fonts

PX_TO_PT = 72.0 / 96.0

# 可以逐字断行的字符区间：CJK、假名、谚文、全角标点。其余按「词」处理。
_BREAK_RANGES = (
    (0x1100, 0x11FF),
    (0x2E80, 0x303F),
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xA000, 0xA4CF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0xFE30, 0xFE6F),
    (0xFF00, 0xFF60),
    (0xFFE0, 0xFFE6),
)


@dataclass(frozen=True)
class Run:
    """一段文字 + 一种字体。"""

    text: str
    font: str = fonts.DEFAULT_FAMILY


@dataclass(frozen=True)
class LaidRun:
    text: str
    font: str
    x: float
    width: float


@dataclass(frozen=True)
class Line:
    baseline: float
    runs: tuple[LaidRun, ...] = field(default_factory=tuple)


def is_breakable(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _BREAK_RANGES)


def _tokens(runs: list[Run]):
    """切成换行的最小单位：整段西文词、单个汉字、单个空格、换行符。"""
    for run in runs:
        buffer = ""
        for char in run.text:
            if char == "\n":
                if buffer:
                    yield (buffer, run.font)
                    buffer = ""
                yield ("\n", run.font)
            elif char == " ":
                if buffer:
                    yield (buffer, run.font)
                    buffer = ""
                yield (" ", run.font)
            elif is_breakable(char):
                if buffer:
                    yield (buffer, run.font)
                    buffer = ""
                yield (char, run.font)
            else:
                buffer += char
        if buffer:
            yield (buffer, run.font)


def _width(text: str, key: str, size_pt: float) -> float:
    return fonts.font(key).text_length(text, size_pt)


def _hard_split(text: str, key: str, size_pt: float, limit: float) -> list[str]:
    """一个词比整行还宽时逐字切开。"""
    pieces: list[str] = []
    buffer = ""
    for char in text:
        candidate = buffer + char
        if buffer and _width(candidate, key, size_pt) > limit:
            pieces.append(buffer)
            buffer = char
        else:
            buffer = candidate
    if buffer:
        pieces.append(buffer)
    return pieces


def _merge(tokens: list[tuple[str, str]], size_pt: float) -> tuple[LaidRun, ...]:
    """同一字体的相邻片段并成一个字段，x 按累加宽度算。"""
    laid: list[LaidRun] = []
    x = 0.0
    for text, key in tokens:
        if not text:
            continue
        width = _width(text, key, size_pt)
        if laid and laid[-1].font == key:
            previous = laid[-1]
            laid[-1] = LaidRun(previous.text + text, key, previous.x, previous.width + width)
        else:
            laid.append(LaidRun(text, key, x, width))
        x += width
    return tuple(laid)


def layout(
    runs: list[Run],
    width_pt: float,
    size_px: float,
    line_height: float,
) -> tuple[list[Line], float]:
    """排一页文字。返回 (行列表, 文本框高度)。"""
    size_pt = max(1.0, float(size_px)) * PX_TO_PT
    leading = max(0.5, float(line_height)) * size_pt
    limit = max(1.0, float(width_pt))

    lines: list[list[tuple[str, str]]] = [[]]
    current = 0.0

    def flush() -> None:
        nonlocal current
        # 行尾空格不占位，否则居中/靠右时会莫名多出一截。
        while lines[-1] and lines[-1][-1][0] == " ":
            lines[-1].pop()
        lines.append([])
        current = 0.0

    for text, key in _tokens(runs):
        if text == "\n":
            flush()
            continue
        width = _width(text, key, size_pt)
        if current + width > limit and lines[-1]:
            flush()
        if width > limit:
            for piece in _hard_split(text, key, size_pt, limit):
                piece_width = _width(piece, key, size_pt)
                if current + piece_width > limit and lines[-1]:
                    flush()
                lines[-1].append((piece, key))
                current += piece_width
            continue
        lines[-1].append((text, key))
        current += width

    # 末尾的空行是用户真敲出来的回车，不能吃掉：它决定文本框的高度。
    if not lines:
        lines = [[]]

    laid: list[Line] = []
    for index, tokens in enumerate(lines):
        used = {key for _text, key in tokens} or {fonts.DEFAULT_FAMILY}
        ascent = max(fonts.font(key).ascender for key in used)
        descent = max(-fonts.font(key).descender for key in used)
        # 与 CSS 行盒的规则一致：先按 (行高 - 字体实际高度) 的一半做上半间距。
        baseline = index * leading + (leading - (ascent + descent) * size_pt) / 2 + ascent * size_pt
        laid.append(Line(baseline=baseline, runs=_merge(tokens, size_pt)))

    return laid, len(laid) * leading


def plain_text(runs: list[Run]) -> str:
    return "".join(run.text for run in runs)
