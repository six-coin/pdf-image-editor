"""裁掉图片四周的纯白边。

只认「纯白」：RGB 三个分量都是 255，或者像素完全透明（透明区域压在纸上
就是白的）。不做阈值容差——254 的扫描底灰不算白，免得把内容边缘啃掉。

裁法是取所有非白像素的包围盒：包围盒之外的四条边必然全是纯白，而且已经
不能再往里裁，切掉的面积就是最大的。
"""

from __future__ import annotations

import numpy as np
import pymupdf

from app.core.split import crop_pixmap


def _to_rgb(pix: pymupdf.Pixmap) -> pymupdf.Pixmap:
    """CMYK 之类的四通道无 alpha 图先转 RGB，后续只处理 1/2/3/4 通道。"""
    if pix.colorspace is not None and pix.colorspace.n == 4 and not pix.alpha:
        return pymupdf.Pixmap(pymupdf.csRGB, pix)
    return pix


def _white_mask(pix: pymupdf.Pixmap) -> np.ndarray:
    width, height, channels = pix.width, pix.height, pix.n
    raw = np.frombuffer(pix.samples, dtype=np.uint8)
    arr = raw.reshape(height, pix.stride)[:, : width * channels].reshape(height, width, channels)

    if pix.alpha:
        alpha = arr[:, :, channels - 1]
        if channels == 2:
            return (alpha == 0) | (arr[:, :, 0] == 255)
        return (alpha == 0) | np.all(arr[:, :, :3] == 255, axis=2)
    if channels == 1:
        return arr[:, :, 0] == 255
    if channels == 3:
        return np.all(arr == 255, axis=2)
    raise ValueError(f"unsupported image with {channels} channels")


def trim_white(data: bytes) -> tuple[bytes, tuple[int, int, int, int], int, int] | None:
    """裁掉四周纯白边，返回 ``(PNG, (x, y, w, h), 原宽, 原高)``。

    没有可裁的边（已经贴边，或整张全白）时返回 ``None``。像素框用原图像素
    坐标，调用方按比例换算成页面上的新矩形。
    """
    pix = _to_rgb(pymupdf.Pixmap(data))
    white = _white_mask(pix)
    content = ~white

    rows = np.flatnonzero(content.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(content.any(axis=0))
    if cols.size == 0:
        return None

    x0 = int(cols[0])
    x1 = int(cols[-1]) + 1
    y0 = int(rows[0])
    y1 = int(rows[-1]) + 1
    if x0 == 0 and y0 == 0 and x1 == pix.width and y1 == pix.height:
        return None

    cropped = crop_pixmap(pix, x0, y0, x1 - x0, y1 - y0)
    return cropped.tobytes("png"), (x0, y0, x1 - x0, y1 - y0), pix.width, pix.height
