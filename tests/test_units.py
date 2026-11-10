"""单位换算与页码范围解析。"""

from __future__ import annotations

import pytest

from app.core import units


def test_mm_to_pt_roundtrip():
    assert units.mm_to_pt(25.4) == pytest.approx(72.0)
    assert units.pt_to_mm(72.0) == pytest.approx(25.4)


def test_simple_range():
    pages, errors = units.parse_page_range("1-3,5", 10)
    assert pages == [0, 1, 2, 4]
    assert errors == []


def test_spaces_and_fullwidth_comma():
    pages, _ = units.parse_page_range("1 - 2 ， 4", 10)
    assert pages == [0, 1, 3]


def test_reversed_range_reports_error():
    pages, errors = units.parse_page_range("3-1", 10)
    assert pages == []
    assert errors == [("reversed", "3-1")]


def test_out_of_bounds_reports_error():
    pages, errors = units.parse_page_range("9-12", 10)
    assert pages == []
    assert errors == [("out_of_range", "9-12")]

    pages, errors = units.parse_page_range("0", 10)
    assert pages == []
    assert errors == [("out_of_range", "0")]


def test_garbage_token_reports_error():
    pages, errors = units.parse_page_range("abc,2", 10)
    assert pages == [1]
    assert errors == [("bad_token", "abc")]


def test_dangling_dash_is_an_error_not_silence():
    _, errors = units.parse_page_range("-5", 10)
    assert errors and errors[0][0] == "bad_token"


def test_no_pages_means_no_parsing():
    assert units.parse_page_range("1-3", 0) == ([], [])


def test_duplicates_collapse():
    pages, _ = units.parse_page_range("2,2,2-3", 10)
    assert pages == [1, 2]
