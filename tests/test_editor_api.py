"""编辑接口：选择、移动、删除、层级、撤销、切分、保存。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pymupdf
import pytest


def _objects(instance):
    return instance.get_state()["objects"]


def test_select_filters_unknown(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    snapshot = instance.select([obj["id"], "nope"])
    assert snapshot["selection"] == [obj["id"]]


def test_commit_transform_moves(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    snapshot = instance.commit_transform(
        [{"id": obj["id"], "page": 0, "x": 300, "y": 400, "w": 120, "h": 90}]
    )
    moved = [o for o in snapshot["objects"] if o["id"] == obj["id"]][0]
    assert moved["x"] == pytest.approx(300)
    assert snapshot["doc"]["dirty"] is True
    assert snapshot["history"]["can_undo"] is True


def test_commit_transform_clamps_out_of_page(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    snapshot = instance.commit_transform(
        [{"id": obj["id"], "page": 0, "x": 5000, "y": 5000, "w": 120, "h": 90}]
    )
    moved = [o for o in snapshot["objects"] if o["id"] == obj["id"]][0]
    assert moved["x"] + moved["w"] <= 595.5
    assert moved["y"] + moved["h"] <= 842.5


def test_commit_transform_rejects_garbage(editor, opened):
    instance, _server = editor
    opened()
    before = _objects(instance)
    bad_payloads = [
        [],
        [{"id": "nope"}],
        [{"id": before[0]["id"], "x": "a", "y": 0, "w": 1, "h": 1}],
        [{"id": before[0]["id"], "x": 0, "y": 0, "w": 0, "h": 0}],
        [None],
        None,
    ]
    for payload in bad_payloads:
        assert instance.commit_transform(payload)["ok"] is True

    after = _objects(instance)
    assert [o["id"] for o in after] == [o["id"] for o in before]
    assert instance.get_state()["history"]["can_undo"] is False


def test_cross_page_move(editor, opened):
    instance, _server = editor
    opened(pages=2)
    obj = _objects(instance)[0]
    snapshot = instance.commit_transform(
        [{"id": obj["id"], "page": 1, "x": 100, "y": 100, "w": 100, "h": 80}]
    )
    moved = [o for o in snapshot["objects"] if o["id"] == obj["id"]][0]
    assert moved["page"] == 1


def test_delete_then_undo(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    assert instance.delete_objects([obj["id"]])["objects"] == []
    assert [o["id"] for o in instance.undo()["objects"]] == [obj["id"]]


def test_reorder_front_and_back(editor, opened):
    instance, _server = editor
    opened(images=2)
    first, second = _objects(instance)[:2]

    snapshot = instance.reorder_objects([first["id"]], "front")
    z = {o["id"]: o["z"] for o in snapshot["objects"]}
    assert z[first["id"]] > z[second["id"]]

    snapshot = instance.reorder_objects([first["id"]], "back")
    z = {o["id"]: o["z"] for o in snapshot["objects"]}
    assert z[first["id"]] < z[second["id"]]


def test_split_produces_four_cells(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    snapshot = instance.split_object(obj["id"], [0.5], [0.5])
    assert len(snapshot["objects"]) == 4
    assert all(o["id"] != obj["id"] for o in snapshot["objects"])


def test_keep_cell_is_explicit(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    snapshot = instance.keep_cell(obj["id"], [0.5], [0.5], 1, 1)
    assert len(snapshot["objects"]) == 1
    kept = snapshot["objects"][0]
    assert kept["x"] == pytest.approx(obj["x"] + obj["w"] / 2)
    assert kept["y"] == pytest.approx(obj["y"] + obj["h"] / 2)


def test_keep_cell_out_of_range_is_noop(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    before = _objects(instance)
    snapshot = instance.keep_cell(obj["id"], [0.5], [0.5], 9, 9)
    assert [o["id"] for o in snapshot["objects"]] == [o["id"] for o in before]


def test_punch_keeps_original(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    snapshot = instance.punch_cell(obj["id"], [0.5], [0.5], 0, 0)
    ids = [o["id"] for o in snapshot["objects"]]
    assert obj["id"] in ids
    assert len(ids) == 3


def test_undo_redo_after_split(editor, opened):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    instance.split_object(obj["id"], [0.5], [0.5])
    assert [o["id"] for o in instance.undo()["objects"]] == [obj["id"]]
    assert len(instance.redo()["objects"]) == 4


def test_save_writes_file_and_resets_history(editor, opened):
    instance, _server = editor
    path = opened()
    obj = _objects(instance)[0]
    instance.commit_transform([{"id": obj["id"], "page": 0, "x": 400, "y": 500, "w": 120, "h": 90}])

    result = instance.save_document()
    assert result["ok"] is True
    assert result["replaced"] == 1

    snapshot = instance.get_state()
    assert snapshot["doc"]["dirty"] is False
    assert snapshot["history"]["can_undo"] is False
    assert snapshot["doc"]["page_count"] == 1

    out = pymupdf.open(path)
    assert "Hello text layer" in out[0].get_text()
    bbox = out[0].get_image_info(xrefs=True)[0]["bbox"]
    assert bbox[0] == pytest.approx(400, abs=1)
    assert bbox[1] == pytest.approx(500, abs=1)
    out.close()


def test_save_refuses_read_only_file(editor, opened):
    instance, _server = editor
    path = opened()
    obj = _objects(instance)[0]
    instance.commit_transform([{"id": obj["id"], "page": 0, "x": 400, "y": 500, "w": 120, "h": 90}])

    os.chmod(path, stat.S_IREAD)
    try:
        result = instance.save_document()
        assert result["ok"] is False
        assert "只读" in result["message"]
        # 拒绝保存不能把文档弄丢
        assert instance.get_state()["doc"]["dirty"] is True
        assert len(instance.get_state()["objects"]) == 1
    finally:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_save_failure_keeps_edits_and_handle(editor, opened, monkeypatch):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    instance.commit_transform([{"id": obj["id"], "page": 0, "x": 400, "y": 500, "w": 120, "h": 90}])

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    result = instance.save_document()

    assert result["ok"] is False
    snapshot = instance.get_state()
    # 文件没动，编辑必须还在，句柄也必须接回来
    assert snapshot["doc"]["page_count"] == 1
    moved = [o for o in snapshot["objects"] if o["id"] == obj["id"]][0]
    assert moved["x"] == pytest.approx(400)
    assert snapshot["doc"]["dirty"] is True


def test_save_as_switches_baseline(editor, opened, tmp_path):
    instance, _server = editor
    opened()
    target = tmp_path / "copy.pdf"

    result = instance.save_document(None, str(target))

    assert result["ok"] is True
    assert target.is_file()
    assert instance.get_state()["doc"]["path"] == str(target)
    assert instance.get_state()["doc"]["dirty"] is False


def test_export_pages_writes_subset(editor, opened, tmp_path):
    instance, _server = editor
    opened(pages=3, images=0, text="page")

    target = tmp_path / "two.pdf"
    result = instance.export_pages("1,3", str(target))

    assert result["ok"] is True
    assert result["pages"] == 2
    out = pymupdf.open(target)
    assert out.page_count == 2
    out.close()


def test_export_pages_requires_clean_document(editor, opened, tmp_path):
    instance, _server = editor
    opened()
    obj = _objects(instance)[0]
    instance.commit_transform([{"id": obj["id"], "page": 0, "x": 10, "y": 10, "w": 50, "h": 50}])

    result = instance.export_pages("1", str(tmp_path / "x.pdf"))
    assert result["ok"] is False
    assert "保存" in result["message"]


def test_export_pages_rejects_bad_range(editor, opened, tmp_path):
    instance, _server = editor
    opened()
    result = instance.export_pages("99-120", str(tmp_path / "x.pdf"))
    assert result["ok"] is False


def test_paste_image_uses_clipboard(editor, opened, monkeypatch):
    instance, _server = editor
    opened()
    png = pymupdf.Pixmap(pymupdf.csRGB, 20, 10, b"\x00\xff\x00" * 200, False).tobytes("png")
    monkeypatch.setattr("app.ui.web.api.clipboard.read_image", lambda: png)

    snapshot = instance.paste_image(0)

    assert snapshot["ok"] is True
    assert len(snapshot["objects"]) == 2
    assert len(snapshot["selection"]) == 1
    assert snapshot["doc"]["dirty"] is True


def test_paste_image_without_clipboard(editor, opened, monkeypatch):
    instance, _server = editor
    opened()
    monkeypatch.setattr("app.ui.web.api.clipboard.read_image", lambda: None)

    snapshot = instance.paste_image(0)

    assert snapshot["ok"] is False
    assert len(snapshot["objects"]) == 1


def test_external_edit_roundtrip(editor, opened, monkeypatch):
    instance, _server = editor
    opened()
    monkeypatch.setattr("app.ui.web.api.opener.open_external", lambda path: True)

    obj = _objects(instance)[0]
    opened_result = instance.edit_external(obj["id"])
    assert opened_result["ok"] is True
    temp = Path(opened_result["path"])
    assert temp.is_file()

    # 换成另一张图（尺寸也变了），显示矩形应保持不变
    new_png = pymupdf.Pixmap(pymupdf.csRGB, 60, 40, b"\xff\x00\xff" * 2400, False).tobytes("png")
    temp.write_bytes(new_png)

    snapshot = instance.replace_image(obj["id"], str(temp))
    changed = [o for o in snapshot["objects"] if o["id"] == obj["id"]][0]
    assert changed["image"] != obj["image"]
    assert changed["w"] == pytest.approx(obj["w"])
    assert not temp.exists()  # 临时目录已清理


def test_external_edit_rejects_garbage(editor, opened, monkeypatch, tmp_path):
    instance, _server = editor
    opened()
    monkeypatch.setattr("app.ui.web.api.opener.open_external", lambda path: True)
    obj = _objects(instance)[0]
    opened_result = instance.edit_external(obj["id"])

    bad = Path(opened_result["path"])
    bad.write_bytes(b"not an image")
    result = instance.replace_image(obj["id"], str(bad))

    assert result["ok"] is False


def test_reference_settings_persist(editor, opened):
    instance, _server = editor
    opened()
    snapshot = instance.update_reference({"left_mm": 20, "right_mm": 15})
    assert snapshot["reference"]["left_mm"] == pytest.approx(20)
    assert snapshot["reference"]["right_mm"] == pytest.approx(15)


def test_show_guides_toggle(editor, opened):
    instance, _server = editor
    opened()
    assert instance.get_state()["show_guides"] is True
    snapshot = instance.update_settings({"show_guides": False})
    assert snapshot["show_guides"] is False


def test_closing_handler_blocks_when_dirty(editor, opened):
    from app.ui.web.app import _make_closing_handler

    instance, _server = editor
    opened()
    handler = _make_closing_handler(instance)
    assert handler() is True  # 干净，直接放行

    obj = _objects(instance)[0]
    instance.commit_transform([{"id": obj["id"], "page": 0, "x": 10, "y": 10, "w": 60, "h": 40}])
    assert handler() is False  # 脏，拦下来

    instance.confirm_close()
    assert handler() is True


def test_answer_close_cancel_resets(editor):
    instance, _server = editor
    instance.confirm_close()
    assert instance.close_confirmed is True
    instance.answer_close("cancel")
    assert instance.close_confirmed is False


def test_preprocess_worker_finishes_task(editor, pdf_factory, tmp_path):
    instance, _server = editor
    source = pdf_factory("scan.pdf")
    target = tmp_path / "bw.pdf"

    task_id = instance._new_task("preprocess")  # noqa: SLF001
    instance._preprocess_worker(source, target, task_id)  # noqa: SLF001

    status = instance.poll_task(task_id)
    assert status["state"] == "ready"
    assert status["result"]["count"] == 1
    assert target.is_file()
