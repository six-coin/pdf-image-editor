"""PDF 文档句柄。

只负责打开、关闭、读取页信息与可编辑图片。不负责渲染，也不负责保存。

旋转或非轴对齐的图片不提取为可编辑对象：``insert_image`` 只能按 90 度步进放置，
硬要编辑只会得到错位放大的一张图。这些图留在页面背景里，保存时原样保留。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.core.imagestore import ImageStore
from app.errors import PdfError
from app.models import ImageObject, PageInfo, Rect

_AXIS_EPS = 1e-6


def _matrix_tuple(transform: object) -> tuple[float, ...] | None:
    if transform is None:
        return None
    if isinstance(transform, (tuple, list)):
        return tuple(float(v) for v in transform)
    if isinstance(transform, pymupdf.Matrix):
        return (transform.a, transform.b, transform.c, transform.d, transform.e, transform.f)
    return None


def is_axis_aligned(transform: object) -> bool:
    values = _matrix_tuple(transform)
    if values is None or len(values) < 6:
        return False
    a, b, c, d = values[0], values[1], values[2], values[3]
    return abs(b) < _AXIS_EPS and abs(c) < _AXIS_EPS and a > 0 and d > 0


class PdfDocument:
    def __init__(self, path: Path, doc: pymupdf.Document, store: ImageStore) -> None:
        self._path = path
        self._doc: pymupdf.Document | None = doc
        self._store = store
        self._page_info: dict[int, PageInfo] = {}
        self._raw_images: dict[int, bytes] = {}

    @classmethod
    def open(cls, path: Path, store: ImageStore) -> PdfDocument:
        try:
            doc = pymupdf.open(path)
        except Exception as exc:
            raise PdfError(key="error.pdf_open", name=Path(path).name) from exc
        if doc.page_count <= 0:
            doc.close()
            raise PdfError(key="error.pdf_open", name=Path(path).name)
        return cls(Path(path), doc, store)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def page_count(self) -> int:
        return 0 if self._doc is None else self._doc.page_count

    @property
    def doc(self) -> pymupdf.Document:
        if self._doc is None:
            raise PdfError(key="error.no_document")
        return self._doc

    def close(self) -> None:
        """幂等；重复调用不报错。"""
        if self._doc is not None:
            try:
                self._doc.close()
            finally:
                self._doc = None
        self._page_info.clear()
        self._raw_images.clear()

    def page(self, index: int) -> pymupdf.Page:
        if self._doc is None:
            raise PdfError(key="error.no_document")
        if not 0 <= index < self.page_count:
            raise PdfError(key="error.pdf_page_out_of_range", page=index + 1)
        return self.doc[index]

    def page_pt_size(self, index: int) -> tuple[float, float]:
        rect = self.page(index).rect
        return float(rect.width), float(rect.height)

    def page_info(self, index: int) -> PageInfo:
        cached = self._page_info.get(index)
        if cached is not None:
            return cached
        page = self.page(index)
        rect = page.rect
        info = PageInfo(
            index=index,
            width=float(rect.width),
            height=float(rect.height),
            has_text=bool(page.get_text().strip()),
            locked_images=self._locked_count(page),
        )
        self._page_info[index] = info
        return info

    def invalidate(self, index: int | None = None) -> None:
        if index is None:
            self._page_info.clear()
        else:
            self._page_info.pop(index, None)

    def _image_bytes(self, xref: int) -> bytes | None:
        cached = self._raw_images.get(xref)
        if cached is not None:
            return cached
        try:
            data = self.doc.extract_image(xref)["image"]
        except Exception:
            return None
        self._raw_images[xref] = data
        return data

    def _locked_count(self, page: pymupdf.Page) -> int:
        rotated = page.rotation % 360 != 0
        count = 0
        for info in page.get_image_info(xrefs=True):
            if rotated or not is_axis_aligned(info.get("transform")):
                count += 1
        return count

    def editable_images(self, index: int) -> list[ImageObject]:
        """提取本页可编辑的图片，按内容流顺序编号，z 从 10 起递增。"""
        page = self.page(index)
        if page.rotation % 360 != 0:
            return []
        objects: list[ImageObject] = []
        z = 10
        for seq, info in enumerate(page.get_image_info(xrefs=True)):
            xref = int(info.get("xref") or 0)
            if xref <= 0 or not is_axis_aligned(info.get("transform")):
                continue
            raw = self._image_bytes(xref)
            if raw is None:
                continue
            x0, y0, x1, y1 = info["bbox"]
            rect = Rect(float(x0), float(y0), float(x1) - float(x0), float(y1) - float(y0))
            if not rect.is_valid():
                continue
            objects.append(
                ImageObject(
                    id=f"p{index}-x{xref}-{seq}",
                    page=index,
                    rect=rect,
                    image_id=self._store.put(raw),
                    src_xref=xref,
                    src_rect=rect,
                    z=z,
                )
            )
            z += 1
        return objects
