"""切分与打孔。纯函数，最容易覆盖全。"""

from __future__ import annotations

import pymupdf
import pytest

from app.core.split import build_split, keep_cell, punch_cell
from app.models import ImageObject, Rect


def _object(store, width=100, height=80, rect=None):
    pix = pymupdf.Pixmap(
        pymupdf.csRGB, width, height, bytes((10, 20, 30)) * (width * height), False
    )
    return ImageObject(
        id="o1",
        page=0,
        rect=rect or Rect(50, 60, 200, 160),
        image_id=store.put(pix.tobytes("png")),
        src_xref=7,
        src_rect=Rect(50, 60, 200, 160),
        z=10,
    )


def test_build_split_without_cuts_returns_one_piece(store):
    obj = _object(store)
    pieces = build_split([obj], "o1", [], [], store)
    assert pieces is not None
    assert len(pieces) == 1
    assert pieces[0].rect == obj.rect


def test_build_split_three_by_three(store):
    obj = _object(store)
    pieces = build_split([obj], "o1", [1 / 3, 2 / 3], [1 / 3, 2 / 3], store)
    assert pieces is not None
    assert len(pieces) == 9
    assert len({p.id for p in pieces}) == 9


def test_pieces_tile_the_original(store):
    obj = _object(store)
    pieces = build_split([obj], "o1", [0.5], [0.5], store)
    total = sum(p.rect.area for p in pieces)
    assert total == pytest.approx(obj.rect.area)


def test_pieces_keep_the_source_position(store):
    obj = _object(store)
    pieces = build_split([obj], "o1", [0.5], [0.5], store)
    for piece in pieces:
        assert piece.src_rect == obj.src_rect
        assert piece.src_xref == obj.src_xref


def test_piece_pixels_are_halved(store):
    obj = _object(store, width=100, height=80)
    pieces = build_split([obj], "o1", [0.5], [0.5], store)
    for piece in pieces:
        pix = pymupdf.Pixmap(store.get(piece.image_id))
        assert (pix.width, pix.height) == (50, 40)


def test_keep_cell_uses_explicit_row_and_col(store):
    obj = _object(store)
    pieces = keep_cell([obj], "o1", [0.5], [0.5], 1, 1, store)
    assert pieces is not None
    assert len(pieces) == 1
    assert pieces[0].rect == Rect(150, 140, 100, 80)


def test_keep_cell_out_of_range_returns_none(store):
    obj = _object(store)
    assert keep_cell([obj], "o1", [0.5], [0.5], 5, 5, store) is None


def test_keep_cell_with_duplicate_cuts_still_picks_the_right_cell(store):
    obj = _object(store)
    pieces = keep_cell([obj], "o1", [0.5, 0.5], [0.5, 0.5], 0, 1, store)
    assert pieces is not None
    assert pieces[0].rect == Rect(150, 60, 100, 80)


def test_missing_object_returns_none(store):
    assert build_split([], "nope", [0.5], [0.5], store) is None


def test_punch_cell_returns_new_image_and_piece(store):
    obj = _object(store)
    before = obj.image_id
    result = punch_cell([obj], "o1", [0.5], [0.5], 0, 0, store)
    assert result is not None
    hole_image, piece = result

    assert hole_image != before
    assert piece.image_id != before
    assert piece.rect == Rect(50, 60, 100, 80)
    # 挖洞不改变原图尺寸，只是把那一格涂白
    assert pymupdf.Pixmap(store.get(hole_image)).width == 100


def test_punch_fills_only_the_cell(store):
    obj = _object(store)
    hole_image, _piece = punch_cell([obj], "o1", [0.5], [0.5], 0, 0, store)
    hole = pymupdf.Pixmap(store.get(hole_image))
    assert hole.pixel(10, 10) == (255, 255, 255)
    assert hole.pixel(80, 70) == (10, 20, 30)


def test_punch_cell_out_of_range_returns_none(store):
    obj = _object(store)
    assert punch_cell([obj], "o1", [0.5], [0.5], 9, 9, store) is None
