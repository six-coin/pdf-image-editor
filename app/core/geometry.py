"""几何计算。

矩形、夹取、四角缩放、命中、切分矩阵。全部是纯函数，输入输出都是 pt。
"""

from __future__ import annotations

from app.models import Rect

MIN_SIZE = 4.0

_CORNERS = ("tl", "tr", "bl", "br")


def clamp_rect_to_page(rect: Rect, page_w: float, page_h: float) -> Rect:
    """把矩形压回页内：先缩到不超过页尺寸，再把左上角夹进可见范围。"""
    width = min(rect.w, page_w)
    height = min(rect.h, page_h)
    x = min(max(rect.x, 0.0), max(page_w - width, 0.0))
    y = min(max(rect.y, 0.0), max(page_h - height, 0.0))
    return Rect(x, y, width, height)


def fit_rect_into(rect: Rect, page_w: float, page_h: float) -> Rect:
    """等比缩小到能放进页内并居中；本来就放得下就原样返回。"""
    if rect.w <= page_w and rect.h <= page_h:
        return rect
    if not rect.is_valid() or page_w <= 0 or page_h <= 0:
        return rect
    scale = min(page_w / rect.w, page_h / rect.h)
    width = rect.w * scale
    height = rect.h * scale
    return Rect((page_w - width) / 2.0, (page_h - height) / 2.0, width, height)


def _anchor(rect: Rect, corner: str) -> tuple[float, float]:
    """拖动某个角时，对面那个角保持不动。"""
    if corner == "tl":
        return rect.right, rect.bottom
    if corner == "tr":
        return rect.x, rect.bottom
    if corner == "bl":
        return rect.right, rect.y
    return rect.x, rect.y


def scale_from_corner(
    rect: Rect,
    corner: str,
    dx: float,
    dy: float,
    keep_ratio: bool = True,
    min_size: float = MIN_SIZE,
) -> Rect:
    """按指针位移缩放。

    ``keep_ratio=True`` 时保持原宽高比，由变化幅度更大的那个轴决定比例。
    结果小于 ``min_size`` 时原样返回，避免矩形翻面。
    """
    if corner not in _CORNERS:
        return rect
    if not rect.is_valid():
        return rect

    px = rect.x + dx if corner in ("tl", "bl") else rect.right + dx
    py = rect.y + dy if corner in ("tl", "tr") else rect.bottom + dy

    if corner == "tl":
        new = Rect(px, py, rect.right - px, rect.bottom - py)
    elif corner == "tr":
        new = Rect(rect.x, py, px - rect.x, rect.bottom - py)
    elif corner == "bl":
        new = Rect(px, rect.y, rect.right - px, py - rect.y)
    else:
        new = Rect(rect.x, rect.y, px - rect.x, py - rect.y)

    if keep_ratio:
        ratio = rect.w / rect.h
        width_ratio = abs(new.w - rect.w) / rect.w
        height_ratio = abs(new.h - rect.h) / rect.h
        if width_ratio >= height_ratio:
            width = new.w
            height = new.w / ratio
        else:
            width = new.h * ratio
            height = new.h
        anchor_x, anchor_y = _anchor(rect, corner)
        x = anchor_x - width if corner in ("tl", "bl") else anchor_x
        y = anchor_y - height if corner in ("tl", "tr") else anchor_y
        new = Rect(x, y, width, height)

    if new.w < min_size or new.h < min_size:
        return rect
    return new


def hit_test(entries: list[tuple[str, Rect]], x: float, y: float) -> str | None:
    """从后往前找第一个命中的对象——列表末尾就是视觉上最上层。"""
    for object_id, rect in reversed(entries):
        if rect.contains(x, y):
            return object_id
    return None


def _bounds(cuts: list[float]) -> list[float]:
    """去重、排序、夹到 (0,1)，两端补上 0 和 1。

    去重只影响键，不改变取到的值——按 1e-6 四舍五入再乘页宽会带来肉眼可见的
    偏移，300pt 的页面上能差出 0.1pt。
    """
    unique: dict[float, float] = {}
    for cut in cuts:
        value = float(cut)
        if 0.0 < value < 1.0:
            unique.setdefault(round(value, 9), value)
    return [0.0] + [unique[key] for key in sorted(unique)] + [1.0]


def cell_matrix(
    width: float,
    height: float,
    cuts_x: list[float],
    cuts_y: list[float],
    origin: tuple[float, float] = (0.0, 0.0),
) -> list[tuple[int, int, Rect]]:
    """把一块矩形按切分线切成矩阵。

    返回 ``(row, col, rect)`` 列表，已去掉宽或高为 0 的退化格。
    行号列号是**去重之后**的真实网格坐标，调用方据此取格，不存在"第 4 格就是中心"。
    """
    if width <= 0 or height <= 0:
        return []
    xs = _bounds(cuts_x)
    ys = _bounds(cuts_y)
    origin_x, origin_y = origin
    cells: list[tuple[int, int, Rect]] = []
    for row in range(len(ys) - 1):
        for col in range(len(xs) - 1):
            x = origin_x + xs[col] * width
            y = origin_y + ys[row] * height
            w = (xs[col + 1] - xs[col]) * width
            h = (ys[row + 1] - ys[row]) * height
            if w <= 0 or h <= 0:
                continue
            cells.append((row, col, Rect(x, y, w, h)))
    return cells
