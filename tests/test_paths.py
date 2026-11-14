"""路径解析。"""

from __future__ import annotations

from pathlib import Path

from app import paths


def test_resolve_relative_uses_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    assert paths.resolve_user_path("sub/x.pdf") == (tmp_path / "sub" / "x.pdf").resolve()


def test_resolve_strips_quotes_and_spaces(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
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


def test_data_dir_pointer_round_trips(tmp_path, monkeypatch):
    """指针写在本地目录，读回来就是新数据目录。"""
    monkeypatch.delenv("SIXCOIN_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_POINTER", tmp_path / "data-dir.txt")
    target = tmp_path / "custom-data"

    paths.write_data_dir(target)

    assert paths.read_data_dir() == target


def test_migration_moves_config_and_drops_locks(tmp_path, monkeypatch):
    """旧 config 搬进数据目录，旧锁文件直接丢掉。"""
    program = tmp_path / "program"
    (program / "config").mkdir(parents=True)
    (program / "config" / "app.json").write_text("{}", encoding="utf-8")
    (program / "config" / "stale.lock").write_text("", encoding="utf-8")
    data = tmp_path / "data"
    monkeypatch.setattr(paths, "PROGRAM_DIR", program)
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "LOG_DIR", tmp_path / "logs")

    paths.migrate_legacy()

    assert (data / "app.json").is_file()
    assert not (data / "stale.lock").exists()
