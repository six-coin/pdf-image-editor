"""内容寻址的图片仓库。

同一张图无论出现在多少处、被撤销多少次，内存里只有一份字节。
撤销因此不需要复制像素，只需要把 ``image_id`` 指回去。
"""

from __future__ import annotations

import hashlib

import pymupdf

_PREVIEW_QUALITY = 82


def _downscale(pix: pymupdf.Pixmap, max_px: int) -> pymupdf.Pixmap:
    """最近邻缩小。只用于缩略图，不需要插值质量。"""
    longest = max(pix.width, pix.height)
    if longest <= max_px:
        return pix
    factor = longest / max_px
    new_w = max(1, int(pix.width / factor))
    new_h = max(1, int(pix.height / factor))
    components = pix.n
    stride = pix.stride
    source = pix.samples
    out = bytearray(new_w * new_h * components)
    columns = [min(pix.width - 1, int(i * factor)) * components for i in range(new_w)]
    row_bytes = new_w * components
    for y in range(new_h):
        source_row = min(pix.height - 1, int(y * factor)) * stride
        target = y * row_bytes
        for index, offset in enumerate(columns):
            start = source_row + offset
            slot = target + index * components
            out[slot : slot + components] = source[start : start + components]
    return pymupdf.Pixmap(pix.colorspace, new_w, new_h, bytes(out), pix.alpha)


class ImageStore:
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._previews: dict[tuple[str, int], bytes] = {}

    def put(self, data: bytes) -> str:
        image_id = hashlib.sha1(data).hexdigest()
        self._data.setdefault(image_id, data)
        return image_id

    def get(self, image_id: str) -> bytes:
        return self._data[image_id]

    def has(self, image_id: str) -> bool:
        return image_id in self._data

    def ids(self) -> set[str]:
        return set(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def preview(self, image_id: str, max_px: int = 320) -> bytes:
        """给界面显示的缩略图。有 alpha 用 PNG，没有就用 JPEG 省体积。"""
        key = (image_id, max_px)
        cached = self._previews.get(key)
        if cached is not None:
            return cached
        pix = pymupdf.Pixmap(self.get(image_id))
        pix = _downscale(pix, max_px)
        if pix.colorspace is None or pix.alpha:
            data = pix.tobytes("png")
        else:
            data = pix.tobytes("jpg", jpg_quality=_PREVIEW_QUALITY)
        self._previews[key] = data
        return data

    def gc(self, alive: set[str]) -> int:
        """丢掉不再被引用的图片，返回释放的条目数。"""
        doomed = [k for k in self._data if k not in alive]
        for key in doomed:
            del self._data[key]
        stale = [k for k in self._previews if k[0] not in self._data]
        for key in stale:
            del self._previews[key]
        return len(doomed)
