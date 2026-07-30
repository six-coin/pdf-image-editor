from PySide6.QtCore import QLineF
from PySide6.QtGui import QPen, QColor
from PySide6.QtWidgets import QGraphicsLineItem

from app.utils import mm_to_pt
from app.guide_config import load_config

GUIDE_COLOR = QColor(0, 120, 255, 100)


class GuideOverlay:
    def __init__(self, scene):
        self._scene = scene
        self._lines = []
        self._visible = True
        cfg = load_config()
        self._left_mm = cfg["left_cm"] * 10
        self._top_mm = cfg["top_cm"] * 10
        self._right_mm = cfg["right_cm"] * 10
        self._bottom_mm = cfg["bottom_cm"] * 10

    def reload_config(self):
        cfg = load_config()
        self._left_mm = cfg["left_cm"] * 10
        self._top_mm = cfg["top_cm"] * 10
        self._right_mm = cfg["right_cm"] * 10
        self._bottom_mm = cfg["bottom_cm"] * 10

    def create_for_page(self, page_item):
        rect = page_item.pageRect()
        page_origin = page_item.scenePos()
        pw = rect.width()
        ph = rect.height()

        left_x = page_origin.x() + mm_to_pt(self._left_mm)
        right_x = page_origin.x() + pw - mm_to_pt(self._right_mm)
        top_y = page_origin.y() + mm_to_pt(self._top_mm)
        bottom_y = page_origin.y() + ph - mm_to_pt(self._bottom_mm)

        pen = QPen(GUIDE_COLOR, 0)

        v_left = QGraphicsLineItem(QLineF(left_x, page_origin.y(), left_x, page_origin.y() + ph))
        v_left.setPen(pen)
        v_left.setZValue(100)
        v_left.setVisible(self._visible)

        v_right = QGraphicsLineItem(QLineF(right_x, page_origin.y(), right_x, page_origin.y() + ph))
        v_right.setPen(pen)
        v_right.setZValue(100)
        v_right.setVisible(self._visible)

        h_top = QGraphicsLineItem(QLineF(page_origin.x(), top_y, page_origin.x() + pw, top_y))
        h_top.setPen(pen)
        h_top.setZValue(100)
        h_top.setVisible(self._visible)

        h_bottom = QGraphicsLineItem(QLineF(page_origin.x(), bottom_y, page_origin.x() + pw, bottom_y))
        h_bottom.setPen(pen)
        h_bottom.setZValue(100)
        h_bottom.setVisible(self._visible)

        for line in (v_left, v_right, h_top, h_bottom):
            self._scene.addItem(line)
            self._lines.append(line)

    def set_visible(self, visible):
        self._visible = visible
        for line in self._lines:
            line.setVisible(visible)

    def is_visible(self):
        return self._visible

    def clear(self):
        for line in self._lines:
            self._scene.removeItem(line)
        self._lines.clear()

    def update_positions(self, page_items):
        self.clear()
        for pi in page_items:
            self.create_for_page(pi)
        self.set_visible(self._visible)
