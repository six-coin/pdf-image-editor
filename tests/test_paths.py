"""路径解析。"""

from __future__ import annotations

from pathlib import Path

from app import paths


def test_resolve_relative_uses_program_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PROGRAM_DIR", tmp_path)
    assert paths.resolve_user_path("sub/x.pdf") == (tmp_path / "sub" / "x.pdf").resolve()


def test_resolve_strips_quotes_and_spaces(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PROGRAM_DIR", tmp_path)
    assert paths.resolve_user_path('  "a b.pdf"  ') == (tmp_path / "a b.pdf").resolve()


def test_resolve_empty_falls_back_to_program_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PROGRAM_DIR", tmp_path)
    assert paths.resolve_user_path("") == tmp_path
    assert paths.resolve_user_path(None) == tmp_path


def test_resolve_keeps_absolute(tmp_path):
    absolute = tmp_path / "x.pdf"
    assert paths.resolve_user_path(str(absolute)) == absolute


def test_session_temp_dir_is_a_child():
    result = paths.session_temp_dir("s1")
    assert result.parent == paths.TEMP_DIR
    assert isinstance(result, Path)


def test_ensure_pdfs_dir_creates_it(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PDFS_DIR", tmp_path / "pdfs")
    created = paths.ensure_pdfs_dir()
    assert created.is_dir()
    assert paths.ensure_pdfs_dir() == created
