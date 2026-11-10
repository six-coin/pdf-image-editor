"""切分与打孔。

四个纯函数：输入对象列表，输出新对象列表，不碰撤销栈、不碰界面。
格子一律用 ``(row, col)`` 显式指定——这正是旧实现里"第 4 格就是中心"那类
硬编码索引被彻底去掉的地方。
"""

from __future__ import annotations

import pymupdf

from app.core.geometry import cell_matrix
from app.core.imagestore import ImageStore
from app.models import ImageObject, Rect


def crop_pixmap(pix: pymupdf.Pixmap, x: int, y: int, w: int, h: int) -> pymupdf.Pixmap:
    """按像素裁一块。手写行拷贝，不依赖版本相关的裁剪 API。"""
    x = max(0, min(int(x), pix.width - 1))
    y = max(0, min(int(y), pix.height - 1))
    w = max(1, min(int(w), pix.width - x))
    h = max(1, min(int(h), pix.height - y))
    components = pix.n
    stride = pix.stride
    source = pix.samples
    row_bytes = w * components
    out = bytearray(row_bytes * h)
    for row in range(h):
        start = (y + row) * stride + x * components
        out[row * row_bytes : (row + 1) * row_bytes] = source[start : start + row_bytes]
    return pymupdf.Pixmap(pix.colorspace, w, h, bytes(out), pix.alpha)


def _find(objects: list[ImageObject], object_id: str) -> ImageObject | None:
    for obj in objects:
        if obj.id == object_id:
            return obj
    return None


def _pixel_rect(obj: ImageObject, rect: Rect, pix: pymupdf.Pixmap) -> tuple[int, int, int, int]:
    """把页内矩形换算成原图的像素矩形。"""
    image_w, image_h = pix.width, pix.height
    fx0 = (rect.x - obj.rect.x) / obj.rect.w
    fy0 = (rect.y - obj.rect.y) / obj.rect.h
    fx1 = fx0 + rect.w / obj.rect.w
    fy1 = fy0 + rect.h / obj.rect.h

    sx0 = max(0, int(round(fx0 * image_w)))
    sy0 = max(0, int(round(fy0 * image_h)))
    sx1 = min(image_w, max(sx0 + 1, int(round(fx1 * image_w))))
    sy1 = min(image_h, max(sy0 + 1, int(round(fy1 * image_h))))
    return sx0, sy0, max(1, sx1 - sx0), max(1, sy1 - sy0)


def fill_white(pix: pymupdf.Pixmap, x: int, y: int, w: int, h: int) -> pymupdf.Pixmap:
    """把一块区域涂成不透明白色。所有分量都填 255，带 alpha 的图也不会半透明。"""
    components = pix.n
    stride = pix.stride
    buffer = bytearray(pix.samples)
    run = b"\xff" * (w * components)
    for row in range(y, min(y + h, pix.height)):
        start = row * stride + x * components
        end = min(start + len(run), (row + 1) * stride)
        buffer[start:end] = run[: end - start]
    return pymupdf.Pixmap(pix.colorspace, pix.width, pix.height, bytes(buffer), pix.alpha)


def _piece(
    obj: ImageObject,
    cell: tuple[int, int, Rect],
    pix: pymupdf.Pixmap,
    store: ImageStore,
    suffix: str,
    z: int,
) -> ImageObject:
    row, col, rect = cell
    sx0, sy0, sw, sh = _pixel_rect(obj, rect, pix)
    sub = crop_pixmap(pix, sx0, sy0, sw, sh)

    return ImageObject(
        id=f"{obj.id}-{suffix}-{row}{col}",
        page=obj.page,
        rect=rect,
        image_id=store.put(sub.tobytes("png")),
        src_xref=obj.src_xref,
        src_rect=obj.src_rect,
        z=z,
    )


def _matrix_for(obj: ImageObject, cuts_x: list[float], cuts_y: list[float]):
    return cell_matrix(obj.rect.w, obj.rect.h, cuts_x, cuts_y, origin=(obj.rect.x, obj.rect.y))


def build_split(
    objects: list[ImageObject],
    object_id: str,
    cuts_x: list[float],
    cuts_y: list[float],
    store: ImageStore,
) -> list[ImageObject] | None:
    """把一张图切成所有格子，全部保留。对象不存在或切不出格子时返回 None。"""
    obj = _find(objects, object_id)
    if obj is None or not obj.rect.is_valid():
        return None
    matrix = _matrix_for(obj, cuts_x, cuts_y)
    if not matrix:
        return None
    pix = pymupdf.Pixmap(store.get(obj.image_id))
    return [_piece(obj, cell, pix, store, "s", obj.z) for cell in matrix]


def keep_cell(
    objects: list[ImageObject],
    object_id: str,
    cuts_x: list[float],
    cuts_y: list[float],
    row: int,
    col: int,
    store: ImageStore,
) -> list[ImageObject] | None:
    """只保留 (row, col) 这一格。越界返回 None，不猜。"""
    obj = _find(objects, object_id)
    if obj is None or not obj.rect.is_valid():
        return None
    matrix = _matrix_for(obj, cuts_x, cuts_y)
    target = [c for c in matrix if c[0] == row and c[1] == col]
    if not target:
        return None
    pix = pymupdf.Pixmap(store.get(obj.image_id))
    return [_piece(obj, target[0], pix, store, "k", obj.z)]


def punch_cell(
    objects: list[ImageObject],
    object_id: str,
    cuts_x: list[float],
    cuts_y: list[float],
    row: int,
    col: int,
    store: ImageStore,
) -> tuple[str, ImageObject] | None:
    """挖掉 (row, col)：把原图那一格涂白，抠出来的部分独立成一个对象。

    返回 ``(挖洞后的原图 image_id, 抠出来的格子)``，调用方把原图换成新图即可。
    """
    obj = _find(objects, object_id)
    if obj is None or not obj.rect.is_valid():
        return None
    matrix = _matrix_for(obj, cuts_x, cuts_y)
    target = [c for c in matrix if c[0] == row and c[1] == col]
    if not target:
        return None
    pix = pymupdf.Pixmap(store.get(obj.image_id))
    cell = target[0]
    sx0, sy0, sw, sh = _pixel_rect(obj, cell[2], pix)

    piece = _piece(obj, cell, pix, store, "p", obj.z)
    # 洞是直接挖在原图像素上的，不叠白色矩形：叠层在缩放时会被插值成半透明。
    hole = fill_white(pix, sx0, sy0, sw, sh)
    return store.put(hole.tobytes("png")), piece
