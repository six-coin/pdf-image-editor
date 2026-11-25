"""裁掉图片四周接近纯白的边。

判定用 BT.601 灰度：``0.299R + 0.587G + 0.114B >= 0xF8``（248）就算白，
不再要求三个分量都必须是 255。带 alpha 的像素先压在白底上再算灰度——
透明区域压在纸上就是白的。

裁法是取所有非白像素的包围盒：包围盒之外的四条边必然都够白，而且已经
不能再往里裁，切掉的面积就是最大的。
"""

from __future__ import annotations

import numpy as np
import pymupdf

from app.core.split import crop_pixmap

_WHITE_LEVEL = 248.0
_GRAY_WEIGHTS = np.array([0.299, 0.587, 0.114], dtype=np.float32)


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
        alpha = arr[:, :, channels - 1].astype(np.float32) / 255.0
        if channels == 2:
            gray = arr[:, :, 0].astype(np.float32)
        else:
            gray = arr[:, :, :3].astype(np.float32) @ _GRAY_WEIGHTS
        # PyMuPDF 的带 alpha 样本是预乘的：颜色已经乘过 alpha，
        # 压到白纸上只需补上 ``255 * (1 - alpha)``。
        effective = gray + 255.0 * (1.0 - alpha)
        return effective >= _WHITE_LEVEL
    if channels == 1:
        return arr[:, :, 0].astype(np.float32) >= _WHITE_LEVEL
    if channels == 3:
        gray = arr.astype(np.float32) @ _GRAY_WEIGHTS
        return gray >= _WHITE_LEVEL
    raise ValueError(f"unsupported image with {channels} channels")


def trim_white(data: bytes) -> tuple[bytes, tuple[int, int, int, int], int, int] | None:
    """裁掉四周接近纯白的边，返回 ``(PNG, (x, y, w, h), 原宽, 原高)``。

    没有可裁的边（已经贴边，或整张都够白）时返回 ``None``。像素框用原图像素
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
