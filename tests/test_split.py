"""切分与打孔。纯函数，最容易覆盖全。"""

from __future__ import annotations

import pymupdf
import pytest

from app.core.split import build_split, keep_cell, punch_cell, white_png
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


def test_punch_cell_returns_hole_and_piece(store):
    obj = _object(store)
    result = punch_cell([obj], "o1", [0.5], [0.5], 0, 0, store)
    assert result is not None
    hole, piece = result
    assert hole.rect == Rect(50, 60, 100, 80)
    assert hole.z == obj.z + 1
    assert piece.z == obj.z + 2
    assert store.get(hole.image_id) == white_png()


def test_punch_cell_out_of_range_returns_none(store):
    obj = _object(store)
    assert punch_cell([obj], "o1", [0.5], [0.5], 9, 9, store) is None
