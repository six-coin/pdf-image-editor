"""文本排版。

纯函数：给定若干文字段（每段一个字体）、文本框宽度、字号、行高倍数，算出
每一行从哪儿开始、每个字段落在哪个 x、基线在哪儿。

坐标一律是 pt，原点在文本框左上角。字号用 px 表示（与 Edge 的批注一致，
1px = 0.75pt），行高是字号的倍数。

换行规则与浏览器在 ``white-space: pre-wrap`` + ``font-kerning: none`` 下的行为
同构：中文逐字断、西文按词断、超长词硬断、空格不吃到行尾；中文禁则也一致——
收尾标点不单独起行，开头标点不留在行尾。两边都用同一份字体的 advance 宽度，
所以断行点一致。
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

# 不能出现在行首的收尾标点。浏览器按中文禁则把它们留在上一行：如果放不下，
# 会把前一个字一起带下来，而不是让标点单独起一行。后端必须同构，否则编辑时
# 看到的是「，」在行首、保存后却跑到上一行末尾。
_NO_START = frozenset("，。、；：！？）》」』】〕.,!?;:%)]}»”’")

# 不能出现在行尾的开头标点：断行时把它们推到下一行，别让「（」孤零零挂在行尾。
_NO_END = frozenset("（《「『【〔([{«“‘")


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


def _can_break(previous: str, following: str) -> bool:
    """两个 token 之间能不能断行（中文禁则的简化版）。"""
    if following and following[0] in _NO_START:
        return False
    if previous and previous[-1] in _NO_END:
        return False
    return True


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

    skip_spaces = False
    for text, key in _tokens(runs):
        if text == "\n":
            flush()
            skip_spaces = False
            continue
        # 自动换行后的前导空格不占位：浏览器把空格留在上一行行尾（悬挂），
        # 下一行直接从第一个非空字符开始。显式回车后的空格是用户敲的，要保留。
        if skip_spaces and text == " " and not lines[-1]:
            continue
        skip_spaces = False
        width = _width(text, key, size_pt)
        if current + width > limit and lines[-1]:
            # 浏览器不是「放不下就立刻换行」，而是退回到本行最后一个允许的
            # 断点：收尾标点不能起行、开头标点不能收尾，所以「号”」这种
            # 小簇会整体挪到下一行。后端要按同一套断点回退，否则保存后的
            # 换行和编辑时看到的不是一回事。
            line = lines[-1]
            cut = len(line)
            # 先看「当前这个 token 直接换到下一行」行不行；不行才往回找断点。
            if line and not _can_break(line[-1][0], text):
                for index in range(len(line) - 1, 0, -1):
                    if _can_break(line[index - 1][0], line[index][0]):
                        cut = index
                        break
            carry = line[cut:]
            if carry:
                del line[cut:]
                current -= sum(_width(item[0], item[1], size_pt) for item in carry)
            flush()
            # 断点落在空格上时，空格属于上一行行尾，不带到下一行。
            while carry and carry[0][0] == " ":
                carry.pop(0)
            for moved in carry:
                lines[-1].append(moved)
                current += _width(moved[0], moved[1], size_pt)
            skip_spaces = True
            if text == " ":
                continue
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
