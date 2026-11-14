"""路径解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import paths
from app.errors import DataDirError


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


def test_normalize_appends_the_project_code(tmp_path):
    """选一个普通目录，落点自动补上项目代号。"""
    assert paths.normalize_data_dir(str(tmp_path)) == tmp_path / paths.PROJECT


def test_normalize_keeps_a_path_that_already_ends_with_the_code(tmp_path):
    target = tmp_path / paths.PROJECT
    assert paths.normalize_data_dir(str(target)) == target


def test_normalize_is_case_insensitive(tmp_path):
    """Windows 路径不分大小写，已经补过就别再补一层。"""
    target = tmp_path / paths.PROJECT.upper()
    assert paths.normalize_data_dir(str(target)) == target


def test_normalize_strips_quotes_and_trailing_separator(tmp_path):
    assert paths.normalize_data_dir(f'"{tmp_path}\\"') == tmp_path / paths.PROJECT


def test_normalize_empty_text_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR_DEFAULT", tmp_path / "default" / paths.PROJECT)
    assert paths.normalize_data_dir("  ") == paths.DATA_DIR_DEFAULT


def test_request_data_dir_records_the_pending_target(tmp_path, monkeypatch):
    """更改只写待搬迁标记，指针等真正搬完才改。"""
    monkeypatch.delenv("SIXCOIN_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_POINTER", tmp_path / "data-dir.txt")
    monkeypatch.setattr(paths, "DATA_PENDING", tmp_path / "data-dir.pending")
    monkeypatch.setattr(paths, "DATA_DIR_DEFAULT", tmp_path / "default" / paths.PROJECT)

    target = paths.request_data_dir(str(tmp_path / "new"))

    assert target == tmp_path / "new" / paths.PROJECT
    assert paths.pending_data_dir() == target
    assert paths.read_data_dir() == paths.DATA_DIR_DEFAULT


def test_requesting_the_current_dir_clears_the_pending_marker(tmp_path, monkeypatch):
    """改回来就当没改过，不留一条「下次重启」的假提示。"""
    monkeypatch.delenv("SIXCOIN_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_POINTER", tmp_path / "data-dir.txt")
    monkeypatch.setattr(paths, "DATA_PENDING", tmp_path / "data-dir.pending")
    current = tmp_path / "current" / paths.PROJECT
    paths.write_data_dir(current)

    paths.request_data_dir(str(tmp_path / "new"))
    paths.request_data_dir(str(current))

    assert paths.pending_data_dir() is None


def test_reconcile_moves_files_and_drops_locks(tmp_path, monkeypatch):
    """启动时把旧目录的内容搬进新目录，指针跟着改，旧锁文件丢掉。"""
    monkeypatch.delenv("SIXCOIN_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "LOCAL_DIR", tmp_path / "local")
    monkeypatch.setattr(paths, "DATA_POINTER", tmp_path / "local" / "data-dir.txt")
    monkeypatch.setattr(paths, "DATA_PENDING", tmp_path / "local" / "data-dir.pending")
    monkeypatch.setattr(paths, "DATA_DIR_DEFAULT", tmp_path / "default" / paths.PROJECT)
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.json").write_text("{}", encoding="utf-8")
    (source / "stale.lock").write_text("", encoding="utf-8")
    paths.write_data_dir(source)

    target = tmp_path / "target" / paths.PROJECT
    paths.request_data_dir(str(target))
    paths._reconcile_data_dir()

    assert (target / "app.json").is_file()
    assert not (target / "stale.lock").exists()
    assert not source.exists()
    assert paths.read_data_dir() == target
    assert paths.pending_data_dir() is None


def test_reconcile_never_overwrites_existing_files(tmp_path, monkeypatch):
    """目标里已有同名文件时保留目标的那份，不静默覆盖。"""
    monkeypatch.delenv("SIXCOIN_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "LOCAL_DIR", tmp_path / "local")
    monkeypatch.setattr(paths, "DATA_POINTER", tmp_path / "local" / "data-dir.txt")
    monkeypatch.setattr(paths, "DATA_PENDING", tmp_path / "local" / "data-dir.pending")
    monkeypatch.setattr(paths, "DATA_DIR_DEFAULT", tmp_path / "default" / paths.PROJECT)
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.json").write_text("old", encoding="utf-8")
    paths.write_data_dir(source)
    target = tmp_path / "target" / paths.PROJECT
    target.mkdir(parents=True)
    (target / "app.json").write_text("new", encoding="utf-8")

    paths.request_data_dir(str(target))
    paths._reconcile_data_dir()

    assert (target / "app.json").read_text(encoding="utf-8") == "new"


# ---------- 改目录的收敛性 ----------


def _dirs(tmp_path, monkeypatch) -> Path:
    """把指针、标记、默认目录都指到 tmp_path，返回「本地目录」。"""
    monkeypatch.delenv("SIXCOIN_DATA_DIR", raising=False)
    local = tmp_path / "local"
    monkeypatch.setattr(paths, "LOCAL_DIR", local)
    monkeypatch.setattr(paths, "DATA_POINTER", local / "data-dir.txt")
    monkeypatch.setattr(paths, "DATA_PENDING", local / "data-dir.pending")
    monkeypatch.setattr(paths, "DATA_DIR_DEFAULT", tmp_path / "default" / paths.PROJECT)
    return local


def test_requesting_a_legacy_pointer_path_changes_nothing(tmp_path, monkeypatch):
    """指针少了项目代号时，再输入同一个目录不该被当成「换到它的子目录」。

    旧版本正是在这里算出 ``<当前目录>\\pdf-image-editor``，被嵌套检查拦下又
    不清标记，于是每次启动都卡在同一条警告上。
    """
    _dirs(tmp_path, monkeypatch)
    legacy = tmp_path / "data"
    legacy.mkdir()
    paths.write_data_dir(legacy)

    assert paths.request_data_dir(str(legacy)) == legacy
    assert paths.pending_data_dir() is None


def test_requesting_the_normalized_form_of_a_legacy_pointer_is_a_no_op(tmp_path, monkeypatch):
    _dirs(tmp_path, monkeypatch)
    legacy = tmp_path / "data"
    legacy.mkdir()
    paths.write_data_dir(legacy)

    assert paths.request_data_dir(str(legacy / paths.PROJECT)) == legacy
    assert paths.pending_data_dir() is None


def test_request_refuses_a_folder_inside_the_current_one(tmp_path, monkeypatch):
    """把数据目录塞进它自己里面永远搬不成，当场拒绝而不是留个死标记。"""
    _dirs(tmp_path, monkeypatch)
    current = tmp_path / "current" / paths.PROJECT
    current.mkdir(parents=True)
    paths.write_data_dir(current)

    with pytest.raises(DataDirError):
        paths.request_data_dir(str(current / "sub"))
    assert paths.pending_data_dir() is None


def test_request_refuses_a_folder_it_cannot_write(tmp_path, monkeypatch):
    """盘符不存在、路径被文件占住：点按钮的这一刻就报错。"""
    _dirs(tmp_path, monkeypatch)
    current = tmp_path / "current" / paths.PROJECT
    current.mkdir(parents=True)
    paths.write_data_dir(current)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a folder", encoding="utf-8")

    with pytest.raises(DataDirError):
        paths.request_data_dir(str(blocker))


def test_request_creates_the_target_folder(tmp_path, monkeypatch):
    """落点当场建出来，下次启动只剩「搬」这一件事。"""
    _dirs(tmp_path, monkeypatch)
    current = tmp_path / "current" / paths.PROJECT
    current.mkdir(parents=True)
    paths.write_data_dir(current)

    target = paths.request_data_dir(str(tmp_path / "new"))

    assert target.is_dir()
    assert not (target / ".sixcoin-write-probe").exists()


def test_stale_pending_inside_the_source_is_dropped(tmp_path, monkeypatch):
    """旧版本留下的「搬到自己子目录」标记：保留当前目录、丢掉标记，不再报错循环。"""
    _dirs(tmp_path, monkeypatch)
    source = tmp_path / "data"
    source.mkdir()
    (source / "app.json").write_text("{}", encoding="utf-8")
    paths.write_data_dir(source)
    paths.DATA_PENDING.parent.mkdir(parents=True, exist_ok=True)
    paths.DATA_PENDING.write_text(str(source / "sub" / paths.PROJECT), encoding="utf-8")

    paths._reconcile_data_dir()

    assert paths.MIGRATION["status"] == "nested"
    assert paths.pending_data_dir() is None
    assert paths.read_data_dir() == source
    assert (source / "app.json").is_file()


def test_legacy_pending_equal_to_the_normalized_pointer_is_a_no_op(tmp_path, monkeypatch):
    """标记正好是「当前目录 + 项目代号」：同一处地方，清标记就行。"""
    _dirs(tmp_path, monkeypatch)
    source = tmp_path / "data"
    source.mkdir()
    (source / "app.json").write_text("{}", encoding="utf-8")
    paths.write_data_dir(source)
    paths.DATA_PENDING.parent.mkdir(parents=True, exist_ok=True)
    paths.DATA_PENDING.write_text(str(source / paths.PROJECT), encoding="utf-8")

    paths._reconcile_data_dir()

    assert paths.MIGRATION["status"] == "same"
    assert paths.pending_data_dir() is None
    assert paths.read_data_dir() == source


def test_reconcile_merges_folders_instead_of_skipping_them(tmp_path, monkeypatch):
    """目标里已经有 pdfs/ 时，源里的 PDF 要并进去，不能整目录跳过。"""
    _dirs(tmp_path, monkeypatch)
    source = tmp_path / "source"
    (source / "pdfs").mkdir(parents=True)
    (source / "app.json").write_text("{}", encoding="utf-8")
    (source / "pdfs" / "a.pdf").write_text("a", encoding="utf-8")
    paths.write_data_dir(source)
    target = tmp_path / "target" / paths.PROJECT
    (target / "pdfs").mkdir(parents=True)
    (target / "pdfs" / "b.pdf").write_text("b", encoding="utf-8")

    paths.request_data_dir(str(target))
    paths._reconcile_data_dir()

    assert paths.MIGRATION["status"] == "done"
    assert paths.MIGRATION["moved"] == 2
    assert (target / "pdfs" / "a.pdf").is_file()
    assert (target / "pdfs" / "b.pdf").is_file()
    assert paths.read_data_dir() == target


def test_failed_move_keeps_the_pointer_and_the_marker(tmp_path, monkeypatch):
    """搬不过去就留在原处：指针一改，用户的设置就凭空消失了。"""
    _dirs(tmp_path, monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.json").write_text("{}", encoding="utf-8")
    paths.write_data_dir(source)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a folder", encoding="utf-8")
    paths.DATA_PENDING.parent.mkdir(parents=True, exist_ok=True)
    paths.DATA_PENDING.write_text(str(blocker / paths.PROJECT), encoding="utf-8")

    paths._reconcile_data_dir()

    assert paths.MIGRATION["status"] == "failed"
    assert paths.read_data_dir() == source
    assert paths.pending_data_dir() is not None
    assert (source / "app.json").is_file()
