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
    image = _canvas(640, 420)
    for index, y in enumerate((60, 180, 300)):
        _draw_h(image, y, 60, 580, phase=index * 1.1)
    for index, x in enumerate((60, 580)):
        _draw_v(image, x, 60, 300, phase=index * 0.9)
    _draw_v(image, 320, 180, 300, phase=2.0, wobble=0.0)
    # 一个远离框线的字块：处理前后必须一模一样
    for offset in range(4):
        _draw_h(image, 100 + offset * 8, 100, 136, thickness=2, wobble=0.0)
    return image


def test_grid_is_straightened_with_uniform_black_core():
    image = _grid_image()
    png, report = tablelines.straighten(_encode(image))

    assert report.applied is True
    assert (report.horizontal, report.vertical) == (3, 3)
    assert report.thickness == 3

    fixed = _decode(png)
    gray = _gray(fixed)
    for y in (60, 180, 300):
        center = _line_center(gray, "h", 400, y - 6, y + 7)
        assert center == pytest.approx(y, abs=0.8)
        # 线芯必须是纯黑，不是扫描出来的深灰
        assert int(gray[round(center), 400]) == 0
    for x in (60, 320, 580):
        center = _line_center(gray, "v", 120 if x == 60 else 240, x - 6, x + 7)
        assert center == pytest.approx(x, abs=0.8)
        assert int(gray[240, round(center)]) == 0


def test_junctions_and_corners_are_solid():
    image = _grid_image()
    fixed = _decode(tablelines.straighten(_encode(image))[0])
    gray = _gray(fixed)
    for x, y in ((60, 180), (320, 180), (320, 300), (580, 60), (60, 300)):
        block = gray[y - 1 : y + 2, x - 1 : x + 2]
        assert int(block.max()) <= 64, (x, y, block)


def test_short_divider_is_straightened():
    image = _grid_image()
    fixed = _decode(tablelines.straighten(_encode(image))[0])
    gray = _gray(fixed)
    for y in (200, 240, 280):
        center = _line_center(gray, "v", y, 314, 327)
        assert center == pytest.approx(320, abs=0.8)


def test_three_line_table_keeps_its_endpoints():
    image = _canvas(640, 300)
    for index, y in enumerate((80, 150, 220)):
        _draw_h(image, y, 20, 620, phase=index * 1.2)

    png, report = tablelines.straighten(_encode(image))
    assert report.applied is True
    assert (report.horizontal, report.vertical) == (3, 0)

    gray = _gray(_decode(png))
    row = np.flatnonzero(gray[150] < 128)
    assert row.size
    assert row[0] >= 18
    assert row[-1] <= 622


def test_handwriting_stroke_is_left_alone():
    image = _grid_image()
    _draw_h(image, 120, 380, 530, thickness=3, wobble=1.5, phase=0.7)
    before = image[108:134, 376:534].copy()

    png, report = tablelines.straighten(_encode(image))
    assert report.applied is True
    assert report.horizontal == 3  # 那条 150px 的手写横线没有被算成表格线

    after = _decode(png)[108:134, 376:534]
    assert np.array_equal(before, after)


def test_text_away_from_lines_is_untouched():
    image = _grid_image()
    before = image[90:120, 96:140].copy()
    png, _report = tablelines.straighten(_encode(image))
    after = _decode(png)[90:120, 96:140]
    assert np.array_equal(before, after)


def test_thickness_is_forced_to_three_pixels():
    """即使有一条 5px 的线，输出也统一 3px。"""
    image = _grid_image()
    _draw_h(image, 180, 60, 580, thickness=5, phase=0.4)

    png, report = tablelines.straighten(_encode(image))
    assert report.thickness == 3

    gray = _gray(_decode(png))
    for y in (60, 180, 300):
        profile = gray[y - 4 : y + 5, 400]
        dark = int((profile < 200).sum())
        assert 3 <= dark <= 5, (y, profile)


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
