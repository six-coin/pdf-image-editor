from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtGui import QTransform, QPixmap, QPainter

from app.page_item import PageItem
from app.image_item import ImageItem
from app.guide_overlay import GuideOverlay
from app.undo_commands import DeleteCommand, AddWhiteRectCommand
from app.utils import mm_to_pt


PAGE_GAP = 20


class PdfScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages = []
        self._guide_overlay = GuideOverlay(self)
        self._current_y = 0
        self._undo_stack = None

    @property
    def pages(self):
        return self._pages

    @property
    def guide_overlay(self):
        return self._guide_overlay

    @property
    def undo_stack(self):
        return self._undo_stack

    def set_undo_stack(self, stack):
        self._undo_stack = stack

    def clear_scene(self):
        self._guide_overlay.clear()
        self._pages = []
        self._current_y = 0
        self.clear()

    def build_from_data(self, pages_data, show_guides=True):
        self.clear_scene()
        if not pages_data:
            return

        max_width = max(pd["page_size"].width() for pd in pages_data)

        for page_idx, pd in enumerate(pages_data):
            page_size = pd["page_size"]
            bg = pd["background"]
            page_item = PageItem(page_idx, page_size, bg)
            page_item.setPos(0, self._current_y)
            page_item.setZValue(0)
            self.addItem(page_item)
            self._pages.append(page_item)

            for img_data in pd["images"]:
                img_item = ImageItem(page_idx)
                img_item.setPixmap(img_data.pixmap)
                img_item.original_bytes = img_data.original_bytes
                bbox = img_data.bbox_pt
                sx = bbox.width() / img_data.pixmap.width() if img_data.pixmap.width() else 1
                sy = bbox.height() / img_data.pixmap.height() if img_data.pixmap.height() else 1
                img_item.setTransform(QTransform.fromScale(sx, sy))
                img_item.setPos(bbox.x(), bbox.y())
                img_item.setZValue(10)
                img_item.setParentItem(page_item)
                self.addItem(img_item)

            self._current_y += page_size.height() + PAGE_GAP

        self.setSceneRect(0, 0, max_width + 100, max(self._current_y, 800))
        self._guide_overlay.update_positions(self._pages)

    def add_white_rectangle(self):
        active = self.active_page_index()
        if active < 0 and self._pages:
            active = 0
        if active < 0 or active >= len(self._pages):
            return None

        page = self._pages[active]
        pr = page.pageRect()
        x = mm_to_pt(10)
        y = mm_to_pt(10)

        pm = QPixmap(200, 200)
        pm.fill(Qt.white)
        painter = QPainter(pm)
        painter.setPen(Qt.lightGray)
        painter.drawRect(0, 0, 199, 199)
        painter.end()

        item = ImageItem(active)
        item.setPixmap(pm)
        item.setPos(x, y)
        item.setZValue(10)
        item.setParentItem(page)
        self.addItem(item)
        page.add_image(item)
        self.clearSelection()
        item.setSelected(True)

        if self._undo_stack:
            self._undo_stack.push(AddWhiteRectCommand(self, item, page))

        return item

    def active_page_index(self):
        sel = self.selectedItems()
        for s in sel:
            if isinstance(s, ImageItem):
                return s.page_index
        return -1

    def get_page_at_scene_y(self, scene_y):
        for page in self._pages:
            rect = page.sceneBoundingRect()
            if rect.top() <= scene_y <= rect.bottom():
                return page
        return None

    def get_page_by_index(self, idx):
        if 0 <= idx < len(self._pages):
            return self._pages[idx]
        return None

    def collect_images_for_save(self):
        result = []
        for page in self._pages:
            page_images = []
            for img in page.childItems():
                if isinstance(img, ImageItem):
                    page_images.append({
                        "pixmap": img.pixmap(),
                        "rect": img.display_rect(),
                        "original_bytes": img.original_bytes,
                    })
            result.append(page_images)
        return result

    def check_cross_page_moves(self):
        transfers = []
        for page in self._pages:
            page_scene_rect = page.sceneBoundingRect()
            for img in page.childItems():
                if not isinstance(img, ImageItem):
                    continue
                scene_pos = img.scenePos()
                img_h = img.display_rect().height()
                if img_h <= 0:
                    img_h = 10
                threshold = img_h * 0.4

                if scene_pos.y() + threshold < page_scene_rect.top():
                    new_page = self.get_page_at_scene_y(scene_pos.y() + img_h * 0.5)
                    if new_page and new_page != page:
                        transfers.append((img, page, new_page))
                elif scene_pos.y() + img_h - threshold > page_scene_rect.bottom():
                    new_page = self.get_page_at_scene_y(scene_pos.y() + img_h * 0.5)
                    if new_page and new_page != page:
                        transfers.append((img, page, new_page))

        for img, old_page, new_page in transfers:
            self._transfer_image(img, old_page, new_page)

    def _transfer_image(self, img_item, old_page, new_page):
        scene_pos = img_item.scenePos()
        old_page.remove_image(img_item)
        new_page.add_image(img_item)
        new_pos = new_page.mapFromScene(scene_pos)
        img_item.setPos(new_pos)
        img_item.page_index = new_page.page_index

    def delete_selected(self):
        items_data = []
        for item in self.selectedItems():
            if isinstance(item, ImageItem):
                state = item.get_state()
                parent = item.parentItem()
                items_data.append({
                    "item": item,
                    "parent": parent,
                    "state": state,
                })
                if parent and hasattr(parent, "remove_image"):
                    parent.remove_image(item)
                self.removeItem(item)

        if items_data and self._undo_stack:
            self._undo_stack.push(DeleteCommand(self, items_data))
