"""保存：文字保全、z 序、失败不毁源文件、备份、raster 模式。

``test_text_survives_roundtrip`` 是整个项目最贵那个 bug 的回归测试。
"""

from __future__ import annotations

import os

import pymupdf
import pytest

from app.core.document import PdfDocument
from app.core.save import save
from app.errors import SaveError
from app.models import DocumentState, Rect


def _state(doc: PdfDocument) -> DocumentState:
    state = DocumentState(path=doc.path)
    state.pages = [doc.page_info(i) for i in range(doc.page_count)]
    state.objects = [o for i in range(doc.page_count) for o in doc.editable_images(i)]
    return state


def test_text_survives_roundtrip(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    dst = tmp_path / "out.pdf"
    report = save(src, dst, state, store)

    assert report.ok
    assert report.replaced == 1
    out = pymupdf.open(dst)
    assert "Hello text layer" in out[0].get_text()
    assert len(out[0].get_image_info(xrefs=True)) == 1
    assert out[0].rect.width == pytest.approx(595)
    out.close()
    doc.close()


def test_moved_image_lands_at_new_position(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    state.objects[0].rect = Rect(400, 500, 120, 90)

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    infos = out[0].get_image_info(xrefs=True)
    assert len(infos) == 1
    bbox = infos[0]["bbox"]
    assert bbox[0] == pytest.approx(400, abs=1)
    assert bbox[1] == pytest.approx(500, abs=1)
    assert "Hello text layer" in out[0].get_text()
    out.close()
    doc.close()


def test_deleted_image_leaves_text_alone(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    for obj in list(state.objects):
        state.mark_removed(obj.page, obj.src_rect)
    state.objects = []

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    assert out[0].get_image_info(xrefs=True) == []
    assert "Hello text layer" in out[0].get_text()
    out.close()
    doc.close()


def test_z_order_is_preserved(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf", images=2)
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    assert [o.z for o in state.objects] == [10, 11]
    state.objects[0].z = 20

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    widths = [info["width"] for info in out[0].get_image_info(xrefs=True)]
    assert widths == [60, 40]
    out.close()
    doc.close()


def test_source_untouched_when_replace_fails(pdf_factory, store, monkeypatch):
    src = pdf_factory("in.pdf")
    before = src.read_bytes()
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(SaveError):
        save(src, src, state, store)

    assert src.read_bytes() == before
    assert not list(src.parent.glob("*.tmp-*"))
    doc.close()


def test_in_place_save_creates_backup(pdf_factory, store):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    # Windows 上覆盖仍被打开的文件会失败，就地保存前必须先释放句柄。
    doc.close()

    save(src, src, state, store)

    backup = src.with_name("in.bak.pdf")
    assert backup.is_file()
    out = pymupdf.open(src)
    assert "Hello text layer" in out[0].get_text()
    out.close()


def test_raster_mode_drops_text(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    dst = tmp_path / "raster.pdf"
    report = save(src, dst, state, store, mode="raster")
    assert report.mode == "raster"

    out = pymupdf.open(dst)
    assert out[0].get_text().strip() == ""
    assert len(out[0].get_image_info(xrefs=True)) >= 1
    out.close()
    doc.close()


def test_out_of_page_image_is_clamped(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    state.objects[0].rect = Rect(560, 800, 200, 200)

    dst = tmp_path / "out.pdf"
    report = save(src, dst, state, store)

    assert any(w["code"] == "image_clamped" for w in report.warnings)
    out = pymupdf.open(dst)
    bbox = out[0].get_image_info(xrefs=True)[0]["bbox"]
    assert bbox[2] <= 595 + 1
    assert bbox[3] <= 842 + 1
    out.close()
    doc.close()


def test_invalid_mode_raises(store, tmp_path):
    with pytest.raises(SaveError):
        save(tmp_path / "a.pdf", tmp_path / "b.pdf", DocumentState(), store, mode="magic")


def _annotated_pdf(tmp_path):
    """一页里同时有文字、图片、以及压在图上的批注。"""
    path = tmp_path / "annotated.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Hello text layer", fontsize=16)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 40, 30, b"\xff\x00\x00" * 1200, False)
    page.insert_image(pymupdf.Rect(100, 100, 300, 250), pixmap=pix)
    page.add_freetext_annot(pymupdf.Rect(320, 320, 470, 380), "note over nothing")
    page.add_freetext_annot(pymupdf.Rect(120, 120, 280, 180), "note over image")
    page.add_ink_annot([[(150, 400), (200, 430), (250, 400)]])
    doc.save(str(path))
    doc.close()
    return path


def test_annotations_survive_save(tmp_path, store):
    """redaction 会删掉落在矩形里的批注，必须靠摘挂 /Annots 保住。"""
    src = _annotated_pdf(tmp_path)
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    before = pymupdf.open(src)
    after = pymupdf.open(dst)
    assert len(list(before[0].annots())) == 3
    assert len(list(after[0].annots())) == 3
    assert [a.type[1] for a in after[0].annots()] == [a.type[1] for a in before[0].annots()]

    text = after[0].get_text()
    assert "Hello text layer" in text
    assert "note over image" in text
    assert "note over nothing" in text
    assert len(after[0].get_image_info(xrefs=True)) == 1

    before.close()
    after.close()
    doc.close()


def test_split_then_save_roundtrip(pdf_factory, store, tmp_path):
    """不开界面跑通整条链路：打开 → 切分 → 保存 → 重新打开校验。"""
    from app.core.split import build_split

    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    target = state.objects[0]
    pieces = build_split(state.objects, target.id, [0.5], [0.5], store)
    assert pieces is not None and len(pieces) == 4
    state.objects = [o for o in state.objects if o.id != target.id] + pieces

    dst = tmp_path / "split.pdf"
    report = save(src, dst, state, store)

    assert report.replaced == 4
    out = pymupdf.open(dst)
    assert "Hello text layer" in out[0].get_text()
    assert len(out[0].get_image_info(xrefs=True)) == 4
    out.close()
    doc.close()
