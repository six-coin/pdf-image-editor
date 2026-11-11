"""PDF 黑白化预处理。

把页内每张图转成灰度、再把亮于阈值的像素压成纯白——扫描件去底灰的标准做法。

不用 numpy / Pillow：``bytes.translate`` 是 C 实现，逐字节查表比逐像素循环快两个
数量级；灰度转换交给 ``fitz.Pixmap(csGRAY, pix)``。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pymupdf
from loguru import logger

from app.errors import PdfError

Progress = Callable[[int, int], None]


def _table(threshold: int) -> bytes:
    value = min(255, max(0, int(threshold)))
    return bytes(255 if level >= value else level for level in range(256))


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def _to_gray(pix: pymupdf.Pixmap) -> pymupdf.Pixmap | None:
    if pix.colorspace is None:
        return None
    if pix.alpha:
        # 带 alpha 的图（logo、水印）不参与二值化，避免把透明区域压成黑块。
        return None
    if pix.n == 1:
        return pix
    return pymupdf.Pixmap(pymupdf.csGRAY, pix)


def process(
    src: Path,
    dst: Path,
    threshold: int = 235,
    progress: Progress | None = None,
) -> int:
    """逐页处理图片并另存。返回处理的图片张数。"""
    src = Path(src)
    dst = Path(dst)
    if _same_file(src, dst):
        # 源文件正被自己打开着，写回去只会得到半个坏文件。
        raise PdfError(key="error.preprocess_same_file", name=dst.name)

    lookup = _table(threshold)
    done = 0
    handled = 0
    temp_path = dst.with_name(f"{dst.name}.tmp-{os.getpid()}")

    try:
        doc = pymupdf.open(src)
    except Exception as exc:
        raise PdfError(key="error.pdf_open", name=src.name) from exc

    try:
        total = sum(len(doc[i].get_images(full=True)) for i in range(doc.page_count))
        replaced: dict[int, bytes] = {}

        for index in range(doc.page_count):
            page = doc[index]
            for info in page.get_images(full=True):
                xref = int(info[0])
                done += 1
                if progress is not None:
                    progress(done, max(total, 1))

                if xref in replaced:
                    stream = replaced[xref]
                else:
                    try:
                        gray = _to_gray(pymupdf.Pixmap(doc, xref))
                        if gray is None:
                            continue
                        samples = bytearray(gray.samples).translate(lookup)
                        stream = pymupdf.Pixmap(
                            pymupdf.csGRAY, gray.width, gray.height, bytes(samples), 0
                        ).tobytes("png")
                        replaced[xref] = stream
                    except Exception:
                        logger.warning("跳过 xref={} 的图片", xref)
                        continue
                try:
                    page.replace_image(xref, stream=stream)
                    handled += 1
                except Exception:
                    logger.warning("替换 xref={} 失败", xref)

        doc.save(temp_path, garbage=4, deflate=True)
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError(key="error.save_failed", reason=str(exc)) from exc
    finally:
        doc.close()

    try:
        os.replace(temp_path, dst)
    except OSError as exc:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise PdfError(key="error.save_failed", reason=str(exc)) from exc

    return handled
