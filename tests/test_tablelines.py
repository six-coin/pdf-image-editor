from __future__ import annotations

import math

import numpy as np
import pymupdf
import pytest

from app.core import tablelines


def _canvas(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), 255, dtype=np.uint8)


def _draw_h(
    image: np.ndarray,
    y: float,
    x0: int,
    x1: int,
    thickness: int = 3,
    wobble: float = 2.0,
    phase: float = 0.0,
) -> None:
    for x in range(x0, x1 + 1):
        center = y + wobble * math.sin((x - x0) / 37.0 + phase)
        top = int(round(center - (thickness - 1) / 2.0))
        bottom = top + thickness - 1
        image[max(0, top) : bottom + 1, x] = 0
        if top - 1 >= 0:
            image[top - 1, x] = 170
        if bottom + 1 < image.shape[0]:
            image[bottom + 1, x] = 170


def _draw_v(
    image: np.ndarray,
    x: float,
    y0: int,
    y1: int,
    thickness: int = 3,
    wobble: float = 2.0,
    phase: float = 0.0,
) -> None:
    for y in range(y0, y1 + 1):
        center = x + wobble * math.sin((y - y0) / 37.0 + phase)
        left = int(round(center - (thickness - 1) / 2.0))
        right = left + thickness - 1
        image[y, max(0, left) : right + 1] = 0
        if left - 1 >= 0:
            image[y, left - 1] = 170
        if right + 1 < image.shape[1]:
            image[y, right + 1] = 170


def _encode(image: np.ndarray) -> bytes:
    height, width = image.shape[:2]
    pix = pymupdf.Pixmap(
        pymupdf.csRGB,
        width,
        height,
        np.ascontiguousarray(image).tobytes(),
        False,
    )
    return pix.tobytes("png")


def _decode(data: bytes) -> np.ndarray:
    pix = pymupdf.Pixmap(data)
    raw = np.frombuffer(pix.samples, dtype=np.uint8)
    arr = raw.reshape(pix.height, pix.stride)[:, : pix.width * pix.n]
    return arr.reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()


def _gray(image: np.ndarray) -> np.ndarray:
    return image.astype(np.float32).mean(axis=2)


def _line_center(gray: np.ndarray, axis: str, fixed: int, lo: int, hi: int) -> float:
    if axis == "h":
        values = np.flatnonzero(gray[lo:hi, fixed] < 128)
        assert values.size, "line not found"
        return float(values.mean() + lo)
    values = np.flatnonzero(gray[fixed, lo:hi] < 128)
    assert values.size, "line not found"
    return float(values.mean() + lo)


def _grid_image() -> np.ndarray:
    """一个每边都超过 170px、所有线都接上的网格。

    横线 60 / 300 / 540，竖线 60 / 740，中间一条隔板从 300 到 540。
    所有端点都落在另一条线上，能过「不许孤立线」这一关。
    """
    image = _canvas(800, 600)
    for index, y in enumerate((60, 300, 540)):
        _draw_h(image, y, 60, 740, phase=index * 1.1)
    for index, x in enumerate((60, 740)):
        _draw_v(image, x, 60, 540, phase=index * 0.9)
    _draw_v(image, 400, 300, 540, phase=2.0, wobble=0.0)
    # 一个远离框线的字块：处理前后必须一模一样
    for offset in range(4):
        _draw_h(image, 120 + offset * 8, 120, 156, thickness=2, wobble=0.0)
    return image


def test_grid_is_straightened_with_uniform_black_core():
    image = _grid_image()
    png, report = tablelines.straighten(_encode(image))

    assert report.applied is True
    assert (report.horizontal, report.vertical) == (3, 3)
    assert report.thickness == 3

    fixed = _decode(png)
    gray = _gray(fixed)
    for y in (60, 300, 540):
        center = _line_center(gray, "h", 600, y - 6, y + 7)
        assert center == pytest.approx(y, abs=0.8)
        # 线芯必须是纯黑，不是扫描出来的深灰
        assert int(gray[round(center), 600]) == 0
    for x in (60, 400, 740):
        center = _line_center(gray, "v", 150 if x == 60 else 420, x - 6, x + 7)
        assert center == pytest.approx(x, abs=0.8)
        assert int(gray[420, round(center)]) == 0


def test_junctions_and_corners_are_solid():
    image = _grid_image()
    fixed = _decode(tablelines.straighten(_encode(image))[0])
    gray = _gray(fixed)
    for x, y in ((60, 300), (400, 300), (400, 540), (740, 60), (60, 540)):
        block = gray[y - 1 : y + 2, x - 1 : x + 2]
        assert int(block.max()) <= 64, (x, y, block)


def test_divider_longer_than_the_minimum_is_straightened():
    image = _grid_image()
    fixed = _decode(tablelines.straighten(_encode(image))[0])
    gray = _gray(fixed)
    for y in (320, 400, 520):
        center = _line_center(gray, "v", y, 394, 407)
        assert center == pytest.approx(400, abs=0.8)


def test_short_line_is_not_straightened():
    """161px 的隔板即使两端接上了也不收：最短要 170px。"""
    image = _canvas(800, 600)
    for y in (100, 400):
        _draw_h(image, y, 100, 500, wobble=0.0)
    for x in (100, 500):
        _draw_v(image, x, 100, 400, wobble=0.0)
    _draw_h(image, 250, 100, 260, wobble=0.0)  # 161px，左端接竖线，右端悬空
    before = image[240:260, 120:270].copy()

    png, report = tablelines.straighten(_encode(image))
    assert report.applied is True
    assert report.horizontal == 2
    assert report.vertical == 2

    # 没被收下的线一个像素都不动
    after = _decode(png)[240:260, 120:270]
    assert np.array_equal(before, after)


def test_isolated_lines_are_not_converted():
    """三条平行横线彼此不相接，全部按孤立线拒绝，不做任何转换。"""
    image = _canvas(640, 300)
    for index, y in enumerate((80, 150, 220)):
        _draw_h(image, y, 20, 620, phase=index * 1.2)

    data = _encode(image)
    png, report = tablelines.straighten(data)
    assert report.applied is False
    assert report.reason == "no_lines"
    assert png is data


def test_handwriting_stroke_is_left_alone():
    image = _grid_image()
    # 220px 已经超过最短线长，但两端都不接任何线——孤立笔画，不能拉直。
    _draw_h(image, 150, 250, 470, thickness=3, wobble=1.5, phase=0.7)
    before = image[138:164, 246:474].copy()

    png, report = tablelines.straighten(_encode(image))
    assert report.applied is True
    assert report.horizontal == 3

    after = _decode(png)[138:164, 246:474]
    assert np.array_equal(before, after)


def test_crossing_does_not_count_as_a_connection():
    """横线从竖线中间穿过去：两个端点都不在竖线上，仍然是孤立线。"""
    image = _canvas(800, 600)
    for y in (100, 400):
        _draw_h(image, y, 100, 500, wobble=0.0)
    _draw_v(image, 100, 100, 400, wobble=0.0)
    _draw_v(image, 500, 100, 400, wobble=0.0)
    # 一条 300px 的横线横穿中间，两端悬空
    _draw_h(image, 250, 150, 450, wobble=0.0)
    before = image[240:260, 150:451].copy()

    png, report = tablelines.straighten(_encode(image))
    assert report.applied is True
    assert report.horizontal == 2

    after = _decode(png)[240:260, 150:451]
    assert np.array_equal(before, after)


def test_text_away_from_lines_is_untouched():
    image = _grid_image()
    before = image[110:145, 116:160].copy()
    png, _report = tablelines.straighten(_encode(image))
    after = _decode(png)[110:145, 116:160]
    assert np.array_equal(before, after)


def test_thickness_is_forced_to_three_pixels():
    """即使有一条 5px 的线，输出也统一 3px。"""
    image = _grid_image()
    _draw_h(image, 300, 60, 740, thickness=5, phase=0.4)

    png, report = tablelines.straighten(_encode(image))
    assert report.thickness == 3

    gray = _gray(_decode(png))
    for y in (60, 300, 540):
        profile = gray[y - 4 : y + 5, 600]
        dark = int((profile < 200).sum())
        assert 3 <= dark <= 5, (y, profile)


def test_light_gray_line_is_measured_from_ink():
    """浅灰线在「线芯 ≤100」掩膜里一个像素都没有，必须退到整条墨迹去量。"""
    image = _canvas(800, 600)
    for y in (60, 300, 540):
        image[y - 1 : y + 2, 60:741] = 120
    for x in (60, 740):
        image[60:541, x - 1 : x + 2] = 120
    image[300:541, 399:402] = 120

    png, report = tablelines.straighten(_encode(image))
    assert report.applied is True
    assert (report.horizontal, report.vertical) == (3, 3)

    gray = _gray(_decode(png))
    assert int(gray[300, 600]) == 0


def test_plain_image_reports_no_lines():
    image = _canvas(200, 200)
    _draw_h(image, 100, 80, 120, thickness=2, wobble=0.0)
    data = _encode(image)

    png, report = tablelines.straighten(data)
    assert report.applied is False
    assert report.reason == "no_lines"
    assert png is data


def test_straightening_twice_is_stable():
    image = _grid_image()
    first, report = tablelines.straighten(_encode(image))
    second, again = tablelines.straighten(first)

    assert report.applied is True
    assert again.applied is True
    assert again.thickness == report.thickness
    # 第二遍只允许交叉口抗锯齿的灰阶差；黑色形状必须完全一致。
    first_dark = _gray(_decode(first)) < 128
    second_dark = _gray(_decode(second)) < 128
    assert np.array_equal(first_dark, second_dark)


def test_long_stub_at_a_t_junction_is_trimmed():
    """线头多出 6px 也算同一个 T 型口，收回到横线边缘。"""
    image = _grid_image()
    _draw_v(image, 400, 300, 546, phase=2.0, wobble=0.0)
    gray = _gray(_decode(tablelines.straighten(_encode(image))[0]))
    for y in range(543, 547):
        assert int(gray[y, 400]) == 255
