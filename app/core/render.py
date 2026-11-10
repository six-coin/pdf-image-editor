"""页面光栅化与缓存。

背景图永远是"原文档去掉可编辑图片"的样子，与用户后来怎么拖、怎么删无关，
所以缓存键只需要 ``(页号, dpi)``。原图位置 ``src_rect`` 在打开时就固定了。
"""

from __future__ import annotations

import math
from collections import OrderedDict

import pymupdf

from app.core.document import PdfDocument
from app.models import ImageObject, Rect

DEFAULT_DPI = 150
MAX_DPI = 300
DEFAULT_CACHE_BYTES = 256 * 1024 * 1024


def _whiteout(pix: pymupdf.Pixmap, rects: list[Rect], scale: float) -> pymupdf.Pixmap:
    if not rects or pix.colorspace is None:
        return pix
    components = pix.n
    stride = pix.stride
    buffer = bytearray(pix.samples)
    touched = False
    for rect in rects:
        # 向外扩一个设备像素。光栅化时图片边缘是抗锯齿的半覆盖像素，只按
        # 四舍五入取整会漏掉最外一圈——图被挪走之后，原位就留下一条边。
        x0 = max(0, math.floor(rect.x * scale) - 1)
        y0 = max(0, math.floor(rect.y * scale) - 1)
        x1 = min(pix.width, math.ceil(rect.right * scale) + 1)
        y1 = min(pix.height, math.ceil(rect.bottom * scale) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        run = b"\xff" * ((x1 - x0) * components)
        for y in range(y0, y1):
            start = y * stride + x0 * components
            buffer[start : start + len(run)] = run
        touched = True
    if not touched:
        return pix
    return pymupdf.Pixmap(pix.colorspace, pix.width, pix.height, bytes(buffer), pix.alpha)


def page_png(page: pymupdf.Page, editable: list[ImageObject], dpi: int = DEFAULT_DPI) -> bytes:
    """渲染一页为 PNG，并把可编辑图片原来的位置涂白。"""
    scale = max(1, int(dpi)) / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    rects = [o.src_rect for o in editable if o.src_rect is not None]
    pix = _whiteout(pix, rects, scale)
    return pix.tobytes("png")


class RenderCache:
    def __init__(self, document: PdfDocument, max_bytes: int = DEFAULT_CACHE_BYTES) -> None:
        self._document = document
        self._max_bytes = max_bytes
        self._entries: OrderedDict[tuple[int, int], bytes] = OrderedDict()
        self._bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes

    def page_png(self, index: int, dpi: int = DEFAULT_DPI) -> bytes:
        dpi = max(36, min(int(dpi), MAX_DPI))
        key = (index, dpi)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached

        page = self._document.page(index)
        editable = self._document.editable_images(index)
        data = page_png(page, editable, dpi)
        self._entries[key] = data
        self._bytes += len(data)
        self._evict()
        return data

    def prefetch(self, indices: list[int], dpi: int = DEFAULT_DPI) -> None:
        for index in indices:
            if 0 <= index < self._document.page_count:
                self.page_png(index, dpi)

    def invalidate(self, index: int | None = None) -> None:
        if index is None:
            self._entries.clear()
            self._bytes = 0
            return
        for key in [k for k in self._entries if k[0] == index]:
            self._bytes -= len(self._entries.pop(key))

    def _evict(self) -> None:
        while self._bytes > self._max_bytes and len(self._entries) > 1:
            _, data = self._entries.popitem(last=False)
            self._bytes -= len(data)
