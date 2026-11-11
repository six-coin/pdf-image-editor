"""系统层：剪贴板 DIB 解析、预处理。"""

from __future__ import annotations

import pymupdf
import pytest

from app.system import preprocess
from app.system.clipboard import _dib_to_png


def _dib(rows_bgr: list[bytes], width: int) -> bytes:
    """拼一个 24 位 BITMAPINFOHEADER + 像素数据。rows_bgr 按 DIB 顺序（自下而上）。"""
    stride = ((width * 24 + 31) // 32) * 4
    header = bytearray(40)
    header[0:4] = (40).to_bytes(4, "little")
    header[4:8] = width.to_bytes(4, "little", signed=True)
    header[8:12] = len(rows_bgr).to_bytes(4, "little", signed=True)
    header[12:14] = (1).to_bytes(2, "little")
    header[14:16] = (24).to_bytes(2, "little")
    body = b"".join(row + b"\x00" * (stride - len(row)) for row in rows_bgr)
    return bytes(header) + body


def test_dib_is_flipped_to_top_down():
    # DIB 自下而上存：文件里第一行是视觉上的最下面一行
    bottom_blue = bytes((255, 0, 0)) * 2  # BGR = 蓝
    top_red = bytes((0, 0, 255)) * 2  # BGR = 红
    png = _dib_to_png(_dib([bottom_blue, top_red], 2))
    assert png is not None

    pix = pymupdf.Pixmap(png)
    assert (pix.width, pix.height) == (2, 2)
    assert pix.pixel(0, 0) == (255, 0, 0)
    assert pix.pixel(0, 1) == (0, 0, 255)


def test_dib_rejects_unsupported_depth():
    data = bytearray(_dib([b"\x00" * 6], 2))
    data[14:16] = (8).to_bytes(2, "little")
    assert _dib_to_png(bytes(data)) is None


def test_dib_rejects_truncated_data():
    assert _dib_to_png(b"\x00" * 10) is None


def test_preprocess_whitens_bright_pixels(tmp_path):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "out.pdf"

    samples = bytes([100, 250, 100, 250])  # 2×2 灰度
    pix = pymupdf.Pixmap(pymupdf.csGRAY, 2, 2, samples, False)
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 20), "keep me", fontsize=10)
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=pix)
    doc.save(str(src))
    doc.close()

    steps: list[tuple[int, int]] = []
    count = preprocess.process(src, dst, threshold=200, progress=lambda d, t: steps.append((d, t)))

    assert count == 1
    assert steps == [(1, 1)]

    out = pymupdf.open(dst)
    info = out[0].get_image_info(xrefs=True)[0]
    gray = pymupdf.Pixmap(out, info["xref"])
    assert gray.n == 1
    assert set(gray.samples) == {100, 255}
    assert "keep me" in out[0].get_text()
    out.close()


def test_preprocess_missing_file_raises(tmp_path):
    from app.errors import PdfError

    with pytest.raises(PdfError):
        preprocess.process(tmp_path / "nope.pdf", tmp_path / "out.pdf")


def test_preprocess_refuses_to_overwrite_source(tmp_path):
    from app.errors import PdfError

    src = tmp_path / "same.pdf"
    doc = pymupdf.open()
    doc.new_page(width=200, height=200)
    doc.save(str(src))
    doc.close()

    with pytest.raises(PdfError):
        preprocess.process(src, src)
    # 源文件必须原样还在，没有被写成半个文件
    check = pymupdf.open(src)
    assert check.page_count == 1
    check.close()


def test_preprocess_leaves_no_temp_file(tmp_path):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "out.pdf"
    doc = pymupdf.open()
    doc.new_page(width=200, height=200)
    doc.save(str(src))
    doc.close()

    preprocess.process(src, dst)
    assert dst.is_file()
    assert not list(tmp_path.glob("*.tmp-*"))
