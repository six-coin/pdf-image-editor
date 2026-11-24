"""图片合并：分辨率、层级、白底与插值。"""

from __future__ import annotations

import numpy as np
import pymupdf
import pytest

from app.core.merge import merge
from app.models import ImageObject, Rect


def _object(store, object_id, rect, z, width, height, color, alpha=255):
    """造一张纯色图。带 alpha 时按预乘写样本——PyMuPDF 的带 alpha 位图就是预乘的。"""
    if alpha >= 255:
        pix = pymupdf.Pixmap(pymupdf.csRGB, width, height, bytes(color) * (width * height), False)
    else:
        samples = np.empty((height, width, 4), np.uint8)
        samples[..., :3] = [int(channel * alpha / 255) for channel in color]
        samples[..., 3] = alpha
        pix = pymupdf.Pixmap(pymupdf.csRGB, width, height, samples.tobytes(), True)
    return ImageObject(
        id=object_id,
        page=0,
        rect=rect,
        image_id=store.put(pix.tobytes("png")),
        z=z,
    )


def _pixels(store, image_id):
    pix = pymupdf.Pixmap(store.get(image_id))
    rows = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)
    rows = rows[:, : pix.width * pix.n].reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return rows
    rgba = np.empty((pix.height, pix.width, 4), np.uint8)
    rgba[..., :3] = rows
    rgba[..., 3] = 255
    return rgba


def test_merge_needs_at_least_two_images(store):
    obj = _object(store, "a", Rect(10, 10, 50, 50), 10, 50, 50, (255, 0, 0))
    assert merge([obj], store) is None


def test_merge_rejects_different_pages(store):
    first = _object(store, "a", Rect(10, 10, 50, 50), 10, 50, 50, (255, 0, 0))
    second = _object(store, "b", Rect(10, 10, 50, 50), 11, 50, 50, (0, 0, 255))
    second.page = 1
    assert merge([first, second], store) is None


def test_canvas_follows_the_highest_density(store):
    """低密度图放大到高密度图的像素密度，并集按该密度取像素。"""
    low = _object(store, "low", Rect(100, 100, 100, 100), 10, 100, 100, (255, 0, 0))
    high = _object(store, "high", Rect(150, 150, 100, 100), 11, 200, 200, (0, 0, 255))

    image_id, rect, report = merge([low, high], store)

    assert rect == Rect(100, 100, 150, 150)
    assert (report.width, report.height) == (300, 300)
    assert report.density == pytest.approx(2.0)
    assert report.scaled is False

    pixels = _pixels(store, image_id)
    assert tuple(pixels[10, 10]) == (255, 0, 0, 255)
    assert tuple(pixels[299, 299]) == (0, 0, 255, 255)


def test_layers_follow_z_order(store):
    """下层先画、上层后画：重叠区域取 z 更大的那张。"""
    bottom = _object(store, "bottom", Rect(0, 0, 100, 100), 10, 100, 100, (255, 0, 0))
    top = _object(store, "top", Rect(50, 50, 100, 100), 20, 100, 100, (0, 0, 255))

    image_id, _rect, _report = merge([top, bottom], store)
    pixels = _pixels(store, image_id)

    assert tuple(pixels[25, 25]) == (255, 0, 0, 255)
    assert tuple(pixels[75, 75]) == (0, 0, 255, 255)


def test_union_gap_is_white(store):
    """并集空隙没有图，露出纯白实心底，不是透明。"""
    left = _object(store, "left", Rect(0, 0, 10, 10), 10, 10, 10, (0, 0, 255))
    right = _object(store, "right", Rect(20, 0, 10, 10), 11, 10, 10, (0, 255, 0))

    image_id, _rect, _report = merge([left, right], store)
    pixels = _pixels(store, image_id)

    assert tuple(pixels[5, 15]) == (255, 255, 255, 255)


def test_result_has_no_alpha_channel(store):
    """最终产物一定是不透明 RGB，不能把 alpha 带到页面上。"""
    left = _object(store, "left", Rect(0, 0, 10, 10), 10, 10, 10, (255, 0, 0), alpha=128)
    right = _object(store, "right", Rect(0, 0, 10, 10), 11, 10, 10, (0, 0, 255))

    image_id, _rect, _report = merge([left, right], store)
    pix = pymupdf.Pixmap(store.get(image_id))

    assert not pix.alpha
    assert pix.n == 3


def test_transparent_pixels_show_the_white_base(store):
    """半透明黑压在纯白底上：结果应是中灰，而不是带 alpha 的黑。"""
    half_black = _object(store, "half", Rect(0, 0, 10, 10), 10, 10, 10, (0, 0, 0), alpha=128)
    opaque = _object(store, "opaque", Rect(20, 0, 10, 10), 11, 10, 10, (255, 0, 0))

    image_id, _rect, _report = merge([half_black, opaque], store)
    pixels = _pixels(store, image_id)

    assert tuple(pixels[5, 5]) == pytest.approx((127, 127, 127, 255), abs=2)
    assert tuple(pixels[5, 25]) == (255, 0, 0, 255)
    assert tuple(pixels[5, 15]) == (255, 255, 255, 255)


def test_alpha_is_composited(store):
    """半透明绿压在红上：绿约一半、红约一半，结果不透明。"""
    red = _object(store, "red", Rect(0, 0, 10, 10), 10, 10, 10, (255, 0, 0))
    green = _object(store, "green", Rect(0, 0, 10, 10), 11, 10, 10, (0, 255, 0), alpha=128)

    image_id, _rect, _report = merge([red, green], store)
    pixels = _pixels(store, image_id)
    red_channel, green_channel, _blue, alpha = (int(v) for v in pixels[5, 5])

    assert alpha == 255
    assert red_channel == pytest.approx(127, abs=3)
    assert green_channel == pytest.approx(128, abs=3)


def test_bicubic_upscale_produces_intermediate_values(store):
    """2px 宽的渐变放大到 80px：双三次会插出中间值，最近邻只会是 0/255。"""
    gradient = np.zeros((1, 2, 3), np.uint8)
    gradient[0, 1] = 255
    gradient_pix = pymupdf.Pixmap(pymupdf.csRGB, 2, 1, gradient.tobytes(), False)
    gradient_obj = ImageObject(
        id="gradient",
        page=0,
        rect=Rect(0, 0, 8, 10),
        image_id=store.put(gradient_pix.tobytes("png")),
        z=11,
    )
    reference = _object(store, "ref", Rect(0, 0, 8, 10), 10, 80, 100, (0, 0, 0))

    image_id, _rect, report = merge([gradient_obj, reference], store)
    assert (report.width, report.height) == (80, 100)

    row = _pixels(store, image_id)[50, :, 0].astype(int)
    assert row[0] == 0
    assert row[-1] == 255
    assert any(10 < value < 245 for value in row)


def test_canvas_is_scaled_down_when_it_exceeds_the_cap(store, monkeypatch):
    """画布上限触发时整体等比缩小，并在报告里标出来。"""
    monkeypatch.setattr("app.core.merge.MAX_PIXELS", 1000)
    monkeypatch.setattr("app.core.merge.MAX_SIDE", 100)
    first = _object(store, "a", Rect(0, 0, 100, 100), 10, 100, 100, (255, 0, 0))
    second = _object(store, "b", Rect(0, 0, 100, 100), 11, 100, 100, (0, 0, 255))

    image_id, _rect, report = merge([first, second], store)

    assert report.scaled is True
    assert report.width <= 100
    assert report.height <= 100
    # 上限是软目标：宽高各自取整后允许几个像素的超出
    assert report.width * report.height <= 1100
    pix = pymupdf.Pixmap(store.get(image_id))
    assert (pix.width, pix.height) == (report.width, report.height)
