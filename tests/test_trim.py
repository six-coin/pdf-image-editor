"""裁白边：只裁纯白，包围盒之外必须全是 255。"""

from __future__ import annotations

import numpy as np
import pymupdf

from app.core import trim


def _png(width: int, height: int, content: tuple[int, int, int, int] | None) -> bytes:
    arr = np.full((height, width, 3), 255, dtype=np.uint8)
    if content is not None:
        x0, y0, x1, y1 = content
        arr[y0:y1, x0:x1] = (10, 20, 30)
    pix = pymupdf.Pixmap(pymupdf.csRGB, width, height, np.ascontiguousarray(arr).tobytes(), False)
    return pix.tobytes("png")


def _size(data: bytes) -> tuple[int, int]:
    pix = pymupdf.Pixmap(data)
    return pix.width, pix.height


def test_trims_four_edges_to_the_content_box():
    result = trim.trim_white(_png(80, 60, (10, 12, 50, 40)))
    assert result is not None

    data, (x0, y0, w, h), width, height = result
    assert (x0, y0, w, h) == (10, 12, 40, 28)
    assert (width, height) == (80, 60)
    assert _size(data) == (40, 28)


def test_already_tight_image_is_unchanged():
    assert trim.trim_white(_png(40, 30, (0, 0, 40, 30))) is None


def test_all_white_image_is_skipped():
    assert trim.trim_white(_png(40, 30, None)) is None


def test_single_pixel_content_survives():
    result = trim.trim_white(_png(20, 20, (7, 8, 8, 9)))
    assert result is not None
    _data, box, _w, _h = result
    assert box == (7, 8, 1, 1)


def test_near_white_is_not_treated_as_white():
    """254 的底灰不是纯白，不能被裁掉。"""
    arr = np.full((20, 20, 3), 254, dtype=np.uint8)
    arr[5:10, 5:10] = (0, 0, 0)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 20, 20, np.ascontiguousarray(arr).tobytes(), False)

    assert trim.trim_white(pix.tobytes("png")) is None


def test_transparent_border_counts_as_white():
    arr = np.zeros((30, 40, 4), dtype=np.uint8)
    arr[:, :, 3] = 0
    arr[6:18, 8:30] = (10, 20, 30, 255)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 40, 30, np.ascontiguousarray(arr).tobytes(), True)

    result = trim.trim_white(pix.tobytes("png"))
    assert result is not None
    assert result[1] == (8, 6, 22, 12)
