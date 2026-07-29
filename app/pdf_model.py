import fitz
from PySide6.QtCore import QRectF, QBuffer, QIODevice, Qt
from PySide6.QtGui import QPixmap, QPainter


RENDER_DPI = 150
SCALE = RENDER_DPI / 72.0


class ImageData:
    __slots__ = ("xref", "pixmap", "original_bytes", "bbox_pt", "page_idx")

    def __init__(self, xref, pixmap, original_bytes, bbox_pt, page_idx):
        self.xref = xref
        self.pixmap = pixmap
        self.original_bytes = original_bytes
        self.bbox_pt = bbox_pt
        self.page_idx = page_idx


class PdfModel:
    def __init__(self):
        self._doc = None
        self._path = None
        self._pages_data = []
        self._page_count = 0

    @property
    def path(self):
        return self._path

    @property
    def page_count(self):
        return self._page_count

    @property
    def pages_data(self):
        return self._pages_data

    def load(self, path):
        self._doc = fitz.open(path)
        self._path = path
        self._page_count = len(self._doc)
        self._pages_data = []
        for page_idx in range(self._page_count):
            page = self._doc[page_idx]
            bg_pixmap = self._render_background(page_idx)
            images = self._extract_images(page_idx)
            page_size = QRectF(0, 0, page.rect.width, page.rect.height)
            self._pages_data.append({
                "background": bg_pixmap,
                "images": images,
                "page_size": page_size,
            })
        return self._pages_data

    def _render_background(self, page_idx):
        page = self._doc[page_idx]
        mat = fitz.Matrix(SCALE, SCALE)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        bg = QPixmap()
        bg.loadFromData(png_bytes)

        painter = QPainter(bg)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.setBrush(Qt.white)
        painter.setPen(Qt.NoPen)
        pad = 2
        for info in page.get_image_info(xrefs=True):
            bbox = info["bbox"]
            x = bbox[0] * SCALE - pad
            y = bbox[1] * SCALE - pad
            w = (bbox[2] - bbox[0]) * SCALE + pad * 2
            h = (bbox[3] - bbox[1]) * SCALE + pad * 2
            painter.drawRect(QRectF(x, y, w, h))
        painter.end()
        return bg

    def _extract_images(self, page_idx):
        page = self._doc[page_idx]
        images = []
        for info in page.get_image_info(xrefs=True):
            xref = info["xref"]
            bbox = info["bbox"]
            try:
                extracted = self._doc.extract_image(xref)
                img_bytes = extracted["image"]
            except Exception:
                continue

            pixmap = QPixmap()
            ok = pixmap.loadFromData(img_bytes)
            if not ok or pixmap.isNull():
                continue

            images.append(ImageData(
                xref=xref,
                pixmap=pixmap,
                original_bytes=img_bytes,
                bbox_pt=QRectF(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]),
                page_idx=page_idx,
            ))
        return images

    def save(self, path, scene_images):
        if self._doc:
            self._doc.close()
            self._doc = None

        doc = fitz.open()
        page_rects = [pd["page_size"] for pd in self._pages_data]
        for page_idx, images in enumerate(scene_images):
            if page_idx < len(page_rects):
                pr = page_rects[page_idx]
            else:
                pr = QRectF(0, 0, 595, 842)
            w = pr.width()
            h = pr.height()
            if w <= 0 or h <= 0:
                w, h = 595, 842
            page = doc.new_page(width=w, height=h)

            for img_info in images:
                pixmap = img_info["pixmap"]
                rect = img_info["rect"]
                orig = img_info.get("original_bytes")
                if orig:
                    stream_bytes = orig
                else:
                    buffer = QBuffer()
                    buffer.open(QIODevice.ReadWrite)
                    pixmap.save(buffer, "JPG", 85)
                    stream_bytes = bytes(buffer.data())
                frect = fitz.Rect(rect.x(), rect.y(), rect.right(), rect.bottom())
                try:
                    page.insert_image(frect, stream=stream_bytes)
                except Exception:
                    pass

        doc.save(path, deflate=True, garbage=4)
        doc.close()

        self._path = path
        self._doc = fitz.open(path)

    def save_split(self, path, page_indices):
        if self._doc is None:
            return
        new_doc = fitz.open()
        for idx in page_indices:
            if 0 <= idx < self._page_count:
                new_doc.insert_pdf(self._doc, from_page=idx, to_page=idx)
        new_doc.save(path)
        new_doc.close()

    def close(self):
        if self._doc:
            self._doc.close()
            self._doc = None
