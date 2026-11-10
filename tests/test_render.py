"""页面渲染与涂白。"""

from __future__ import annotations

import pymupdf

from app.core.document import PdfDocument
from app.core.render import RenderCache, page_png

PNG_MAGIC = b"\x89PNG"


def test_page_png_is_png(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    data = page_png(doc.page(0), doc.editable_images(0), 72)
    assert data.startswith(PNG_MAGIC)
    doc.close()


def test_whiteout_covers_editable_image(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    objects = doc.editable_images(0)
    data = page_png(doc.page(0), objects, 72)
    pix = pymupdf.Pixmap(data)
    assert pix.pixel(150, 150) == (255, 255, 255)
    doc.close()


def test_without_editable_images_the_picture_stays(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    data = page_png(doc.page(0), [], 72)
    pix = pymupdf.Pixmap(data)
    assert pix.pixel(150, 150) == (255, 0, 0)
    doc.close()


def test_whiteout_leaves_no_fringe(pdf_factory, store, tmp_path):
    """涂白必须盖住抗锯齿的边缘像素。

    只按四舍五入取整会漏掉最外一圈，图片被挪走之后原位会留下一条边。
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 40, 30, b"\xff\x00\x00" * 1200, False)
    # 故意用非整数坐标，让取整误差暴露出来
    page.insert_image(pymupdf.Rect(100.37, 150.61, 253.82, 271.44), pixmap=pix)
    source = tmp_path / "fringe.pdf"
    doc.save(source)
    doc.close()

    handle = PdfDocument.open(source, store)
    data = page_png(handle.page(0), handle.editable_images(0), 150)
    handle.close()

    rendered = pymupdf.Pixmap(data)
    leftovers = [
        (x, y)
        for y in range(rendered.height)
        for x in range(rendered.width)
        if rendered.pixel(x, y) != (255, 255, 255)
    ]
    assert leftovers == []


def test_cache_reuses_and_invalidates(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    cache = RenderCache(doc)
    first = cache.page_png(0, 72)
    second = cache.page_png(0, 72)
    assert first is second
    assert cache.size_bytes > 0

    cache.invalidate()
    assert cache.size_bytes == 0
    doc.close()


def test_dpi_is_capped(pdf_factory, store):
    doc = PdfDocument.open(pdf_factory(), store)
    cache = RenderCache(doc)
    pix = pymupdf.Pixmap(cache.page_png(0, 1000))
    assert pix.width <= 595 * 300 / 72 + 1
    doc.close()
