"""文档句柄：打开、关闭、页信息、可编辑图片、旋转页。"""

from __future__ import annotations

import pymupdf
import pytest

from app.core.document import PdfDocument, is_axis_aligned
from app.errors import PdfError


def test_open_reports_pages_and_text(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(pages=2), store)
    assert doc.page_count == 2
    info = doc.page_info(0)
    assert info.has_text is True
    assert (info.width, info.height) == (595.0, 842.0)
    doc.close()


def test_close_is_idempotent(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    doc.close()
    doc.close()
    assert doc.page_count == 0


def test_closed_document_raises(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    doc.close()
    with pytest.raises(PdfError) as info:
        doc.page(0)
    assert info.value.key == "error.no_document"


def test_page_out_of_range_raises(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    with pytest.raises(PdfError) as info:
        doc.page(9)
    assert info.value.key == "error.pdf_page_out_of_range"
    doc.close()


def test_editable_images_keep_source_position(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(images=2), store)
    objects = doc.editable_images(0)
    assert len(objects) == 2
    for obj in objects:
        assert obj.src_rect == obj.rect
        assert obj.src_xref is not None
        assert obj.page == 0
    assert [o.z for o in objects] == [10, 11]
    doc.close()


def test_images_are_stored_once(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(images=2), store)
    doc.editable_images(0)
    assert len(store) == 2
    doc.close()


def test_soft_mask_is_folded_into_the_stored_image(tmp_path, store):
    """软遮罩是独立的 xref；抽取时要并成 alpha，否则透明区域会显示成黑色。"""
    base = pymupdf.Pixmap(pymupdf.csRGB, 20, 20, b"\xff\x00\x00" * 400, False)
    mask = pymupdf.Pixmap(pymupdf.csGRAY, 20, 20, bytes([0] * 200 + [255] * 200), False)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(
        pymupdf.Rect(100, 100, 200, 200),
        stream=base.tobytes("png"),
        mask=mask.tobytes("png"),
    )
    path = tmp_path / "mask.pdf"
    doc.save(str(path))
    doc.close()

    handle = PdfDocument.open(path, store)
    objects = handle.editable_images(0)
    assert len(objects) == 1

    pix = pymupdf.Pixmap(store.get(objects[0].image_id))
    assert pix.alpha == 1
    rows = pix.samples
    stride = pix.stride
    assert rows[5 * stride + 5 * 4 + 3] == 0  # 上半：遮罩 0
    assert rows[15 * stride + 5 * 4 + 3] == 255  # 下半：遮罩 255
    handle.close()


def test_rotated_page_has_no_editable_images(tmp_path, store):
    path = tmp_path / "rotated.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "rotated", fontsize=14)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 20, 20, b"\xff\x00\x00" * 400, False)
    page.insert_image(pymupdf.Rect(100, 100, 200, 200), pixmap=pix)
    page.set_rotation(90)
    doc.save(str(path))
    doc.close()

    handle = PdfDocument.open(path, store)
    assert handle.editable_images(0) == []
    assert handle.page_info(0).locked_images >= 1
    handle.close()


def test_axis_aligned_detection():
    assert is_axis_aligned((200.0, 0.0, 0.0, 150.0, 100.0, 100.0))
    assert not is_axis_aligned((200.0, 0.0, 45.0, 150.0, 100.0, 100.0))
    assert not is_axis_aligned(None)
