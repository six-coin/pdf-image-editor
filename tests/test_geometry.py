"""几何：夹取、等比缩放、命中、切分矩阵。"""

from __future__ import annotations

import pytest

from app.core.geometry import (
    cell_matrix,
    clamp_rect_to_page,
    fit_rect_into,
    hit_test,
    scale_from_corner,
)
from app.models import Rect


def test_clamp_leaves_inside_rect_untouched():
    rect = Rect(10, 10, 100, 100)
    assert clamp_rect_to_page(rect, 595, 842) == rect


def test_clamp_moves_back_inside():
    rect = Rect(-20, 800, 100, 100)
    assert clamp_rect_to_page(rect, 595, 842) == Rect(0, 742, 100, 100)


def test_clamp_shrinks_oversized():
    rect = Rect(-10, -10, 900, 1200)
    assert clamp_rect_to_page(rect, 595, 842) == Rect(0, 0, 595, 842)


def test_fit_rect_into_keeps_small_rect():
    rect = Rect(10, 10, 100, 50)
    assert fit_rect_into(rect, 595, 842) == rect


def test_fit_rect_into_centres_oversized():
    rect = Rect(0, 0, 1190, 842)
    fitted = fit_rect_into(rect, 595, 842)
    assert fitted.w == pytest.approx(595)
    assert fitted.x == pytest.approx(0)
    assert fitted.h == pytest.approx(421)


def test_scale_from_br_keeps_ratio():
    rect = Rect(0, 0, 200, 100)
    scaled = scale_from_corner(rect, "br", 100, 0)
    assert scaled.w == pytest.approx(300)
    assert scaled.h == pytest.approx(150)
    assert (scaled.x, scaled.y) == (0, 0)


def test_scale_from_tl_moves_origin():
    rect = Rect(100, 100, 200, 100)
    scaled = scale_from_corner(rect, "tl", -50, 0)
    assert scaled.right == pytest.approx(300)
    assert scaled.bottom == pytest.approx(200)
    assert scaled.w == pytest.approx(250)
    assert scaled.h == pytest.approx(125)


def test_scale_is_driven_by_the_long_side():
    """宽图只看横向位移，竖图只看纵向位移。"""
    wide = Rect(0, 0, 500, 50)
    scaled = scale_from_corner(wide, "br", 10, 10)
    assert scaled.w == pytest.approx(510)
    assert scaled.h == pytest.approx(51)

    # 宽图竖着拖：没有横向位移，尺寸不变
    assert scale_from_corner(wide, "br", 0, 10) == wide

    tall = Rect(0, 0, 50, 500)
    scaled = scale_from_corner(tall, "br", 10, 10)
    assert scaled.h == pytest.approx(510)
    assert scaled.w == pytest.approx(51)

    # 竖图横着拖：同样不变
    assert scale_from_corner(tall, "br", 10, 0) == tall


def test_scale_refuses_to_flip():
    rect = Rect(100, 100, 200, 100)
    assert scale_from_corner(rect, "br", -500, -500) == rect


def test_scale_without_ratio_is_free():
    rect = Rect(0, 0, 200, 100)
    scaled = scale_from_corner(rect, "br", 100, 0, keep_ratio=False)
    assert (scaled.w, scaled.h) == (300, 100)


def test_scale_ignores_unknown_corner():
    rect = Rect(0, 0, 200, 100)
    assert scale_from_corner(rect, "middle", 10, 10) == rect


def test_hit_test_returns_topmost():
    entries = [("a", Rect(0, 0, 100, 100)), ("b", Rect(50, 50, 100, 100))]
    assert hit_test(entries, 60, 60) == "b"
    assert hit_test(entries, 10, 10) == "a"
    assert hit_test(entries, 500, 500) is None


def test_cell_matrix_without_cuts():
    cells = cell_matrix(100, 50, [], [])
    assert len(cells) == 1
    assert cells[0][2] == Rect(0, 0, 100, 50)


def test_cell_matrix_three_by_three():
    cells = cell_matrix(300, 300, [1 / 3, 2 / 3], [1 / 3, 2 / 3])
    assert len(cells) == 9
    middle = [c for c in cells if c[0] == 1 and c[1] == 1][0][2]
    assert middle.x == pytest.approx(100)
    assert middle.w == pytest.approx(100)


def test_cell_matrix_dedupes_identical_cuts():
    cells = cell_matrix(100, 100, [0.5, 0.5], [0.5, 0.5])
    assert len(cells) == 4
    assert sorted({(c[0], c[1]) for c in cells}) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_cell_matrix_ignores_cuts_outside_range():
    cells = cell_matrix(100, 100, [-0.5, 1.5], [])
    assert len(cells) == 1


def test_cell_matrix_respects_origin():
    cells = cell_matrix(100, 100, [], [], origin=(10, 20))
    assert cells[0][2] == Rect(10, 20, 100, 100)
