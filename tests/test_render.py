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
