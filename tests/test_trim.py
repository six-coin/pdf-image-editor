"""裁白边：灰度 >= 阈值（默认 227）就算白，包围盒之外必须都过阈值。"""

from __future__ import annotations

import numpy as np
import pymupdf

from app.core import trim


def _png(width: int, height: int, content: tuple[int, int, int, int] | None) -> bytes:
    return _png_on(width, height, (255, 255, 255), content)


def _png_on(
    width: int,
    height: int,
    background: tuple[int, int, int],
    content: tuple[int, int, int, int] | None,
) -> bytes:
    arr = np.full((height, width, 3), background, dtype=np.uint8)
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


def test_227_is_treated_as_white():
    """默认阈值 227（预处理丢弃底灰的值）本身包含在内。"""
    result = trim.trim_white(_png_on(20, 20, (227, 227, 227), (5, 5, 10, 10)))
    assert result is not None
    assert result[1] == (5, 5, 5, 5)


def test_226_is_kept_as_content():
    """比阈值低一级就不再算白，整张图都是内容，没有可裁的边。"""
    assert trim.trim_white(_png_on(20, 20, (226, 226, 226), (5, 5, 10, 10))) is None


def test_threshold_can_be_raised():
    """阈值调高后，原本算内容的浅灰也变成白边。"""
    data = _png_on(20, 20, (248, 248, 248), (5, 5, 10, 10))
    assert trim.trim_white(data, 250) is None
    assert trim.trim_white(data, 248) is not None


def test_luminance_not_minimum_channel():
    """(250,250,240) 的灰度约 248.9，虽然蓝通道低于阈值，仍算白。"""
    result = trim.trim_white(_png_on(20, 20, (250, 250, 240), (5, 5, 10, 10)))
    assert result is not None
    assert result[1] == (5, 5, 5, 5)


def test_transparent_border_counts_as_white():
    arr = np.zeros((30, 40, 4), dtype=np.uint8)
    arr[:, :, 3] = 0
    arr[6:18, 8:30] = (10, 20, 30, 255)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 40, 30, np.ascontiguousarray(arr).tobytes(), True)

    result = trim.trim_white(pix.tobytes("png"))
    assert result is not None
    assert result[1] == (8, 6, 22, 12)


def test_semi_transparent_pixel_is_composited_over_white():
    """半透明白压在纸上还是白；半透明黑不是。"""
    arr = np.full((20, 20, 4), 255, dtype=np.uint8)
    arr[:, :, 3] = 128
    arr[5:10, 5:10] = (0, 0, 0, 128)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 20, 20, np.ascontiguousarray(arr).tobytes(), True)

    result = trim.trim_white(pix.tobytes("png"))
    assert result is not None
    assert result[1] == (5, 5, 5, 5)
