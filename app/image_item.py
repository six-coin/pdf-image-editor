from PySide6.QtCore import (
    Qt, QPointF, QRectF
)
from PySide6.QtGui import (
    QPen, QBrush, QColor, QTransform
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsItem
)

HANDLE_HIT_SIZE = 20
HANDLE_VISUAL_SIZE = 8
HANDLE_COLOR = QColor(0, 120, 255)
HANDLE_BRUSH = QBrush(QColor(255, 255, 255, 200))


class ImageItem(QGraphicsPixmapItem):
    def __init__(self, page_index=0, parent=None):
        super().__init__(parent)
        self._page_index = page_index
        self._resizing = False
        self._resize_handle = None
        self._resize_params = None

        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)

    @property
    def page_index(self):
        return self._page_index

    @page_index.setter
    def page_index(self, value):
        self._page_index = value

    def display_rect(self):
        pm = self.pixmap()
        if pm is None:
            return QRectF(self.pos(), self.pos())
        t = self.transform()
        w = pm.width() * t.m11()
        h = pm.height() * t.m22()
        return QRectF(self.pos().x(), self.pos().y(), w, h)

    def scale_x(self):
        return self.transform().m11()

    def scale_y(self):
        return self.transform().m22()

    def get_state(self):
        return {
            "pos": QPointF(self.pos()),
            "transform": QTransform(self.transform()),
            "parent": self.parentItem(),
            "page_index": self._page_index,
            "pixmap": self.pixmap() if self.pixmap() else None,
            "zValue": self.zValue(),
        }

    def apply_state(self, state):
        if state["parent"] and self.parentItem() != state["parent"]:
            old_p = self.parentItem()
            if old_p and hasattr(old_p, "remove_image"):
                old_p.remove_image(self)
            self.setParentItem(state["parent"])
            if hasattr(state["parent"], "add_image"):
                state["parent"].add_image(self)
        elif not state["parent"] and self.parentItem():
            old_p = self.parentItem()
            if old_p and hasattr(old_p, "remove_image"):
                old_p.remove_image(self)
            self.setParentItem(None)
        self.setPos(state["pos"])
        self.setTransform(state["transform"])
        self._page_index = state["page_index"]
        if state["pixmap"] and state["pixmap"] != self.pixmap():
            self.setPixmap(state["pixmap"])
        self.setZValue(state["zValue"] if state["zValue"] else 10)

    @staticmethod
    def state_changed(old, new):
        return (
            old["pos"] != new["pos"]
            or old["transform"].m11() != new["transform"].m11()
            or old["transform"].m22() != new["transform"].m22()
            or old["parent"] != new["parent"]
            or old["page_index"] != new["page_index"]
        )

    def _hit_rect(self, corner):
        r = self.boundingRect()
        hs = HANDLE_HIT_SIZE
        mapping = {
            "tl": QRectF(r.left() - hs / 2, r.top() - hs / 2, hs, hs),
            "tr": QRectF(r.right() - hs / 2, r.top() - hs / 2, hs, hs),
            "bl": QRectF(r.left() - hs / 2, r.bottom() - hs / 2, hs, hs),
            "br": QRectF(r.right() - hs / 2, r.bottom() - hs / 2, hs, hs),
        }
        return mapping.get(corner, QRectF())

    def _visual_rect(self, corner):
        r = self.boundingRect()
        hs = HANDLE_VISUAL_SIZE
        mapping = {
            "tl": QRectF(r.left() - hs / 2, r.top() - hs / 2, hs, hs),
            "tr": QRectF(r.right() - hs / 2, r.top() - hs / 2, hs, hs),
            "bl": QRectF(r.left() - hs / 2, r.bottom() - hs / 2, hs, hs),
            "br": QRectF(r.right() - hs / 2, r.bottom() - hs / 2, hs, hs),
        }
        return mapping.get(corner, QRectF())

    def _corner_at(self, pos):
        for c in ("tl", "tr", "bl", "br"):
            if self._hit_rect(c).contains(pos):
                return c
        return None

    @staticmethod
    def _opposite(corner):
        return {"tl": "br", "tr": "bl", "bl": "tr", "br": "tl"}.get(corner, corner)

    def _fixed_point_parent(self, corner):
        r = self.display_rect()
        return {
            "tl": r.bottomRight(),
            "tr": r.bottomLeft(),
            "bl": r.topRight(),
            "br": r.topLeft(),
        }.get(corner, r.topLeft())

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        if self.isSelected() and self.pixmap() is not None:
            painter.save()
            painter.setPen(QPen(HANDLE_COLOR, 0))
            painter.setBrush(HANDLE_BRUSH)
            for c in ("tl", "tr", "bl", "br"):
                painter.drawRect(self._visual_rect(c))
            painter.restore()

    def hoverMoveEvent(self, event):
        if self.isSelected():
            corner = self._corner_at(event.pos())
            if corner in ("tl", "br"):
                self.setCursor(Qt.SizeFDiagCursor)
            elif corner in ("tr", "bl"):
                self.setCursor(Qt.SizeBDiagCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSelected():
            corner = self._corner_at(event.pos())
            if corner:
                self._begin_resize(corner)
                event.accept()
                return
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            keep_aspect = bool(event.modifiers() & Qt.ShiftModifier)
            mouse_parent = self.mapToParent(event.pos())
            self._do_resize(mouse_parent, keep_aspect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._resize_params = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def _begin_resize(self, corner):
        self._resizing = True
        self._resize_handle = corner
        t = self.transform()
        pm = self.pixmap()
        self._resize_params = {
            "start_pos": self.pos(),
            "start_sx": t.m11(),
            "start_sy": t.m22(),
            "pw": pm.width(),
            "ph": pm.height(),
            "fixed_pt": self._fixed_point_parent(corner),
        }

    def _do_resize(self, mouse_parent, keep_aspect):
        p = self._resize_params
        handle = self._resize_handle
        old_sx, old_sy = p["start_sx"], p["start_sy"]
        pw, ph = p["pw"], p["ph"]
        fixed = p["fixed_pt"]

        if handle == "br":
            new_sx = (mouse_parent.x() - fixed.x()) / pw if pw else old_sx
            new_sy = (mouse_parent.y() - fixed.y()) / ph if ph else old_sy
            dx, dy = 0, 0
        elif handle == "tl":
            new_w = fixed.x() - mouse_parent.x()
            new_h = fixed.y() - mouse_parent.y()
            new_sx = max(new_w / pw, 0.01) if pw else old_sx
            new_sy = max(new_h / ph, 0.01) if ph else old_sy
            dx = pw * (old_sx - new_sx)
            dy = ph * (old_sy - new_sy)
        elif handle == "tr":
            new_w = mouse_parent.x() - fixed.x()
            new_h = fixed.y() - mouse_parent.y()
            new_sx = max(new_w / pw, 0.01) if pw else old_sx
            new_sy = max(new_h / ph, 0.01) if ph else old_sy
            dx = 0
            dy = ph * (old_sy - new_sy)
        elif handle == "bl":
            new_w = fixed.x() - mouse_parent.x()
            new_h = mouse_parent.y() - fixed.y()
            new_sx = max(new_w / pw, 0.01) if pw else old_sx
            new_sy = max(new_h / ph, 0.01) if ph else old_sy
            dx = pw * (old_sx - new_sx)
            dy = 0
        else:
            return

        if keep_aspect and pw > 0 and ph > 0:
            ratio = pw / ph
            sxd = abs(new_sx / old_sx - 1) if old_sx else 0
            syd = abs(new_sy / old_sy - 1) if old_sy else 0
            if sxd >= syd:
                new_sy = new_sx / ratio
            else:
                new_sx = new_sy * ratio

            if handle in ("tl", "tr", "bl"):
                dx = pw * (old_sx - new_sx)
                dy = ph * (old_sy - new_sy)
                if handle == "tr":
                    dx = 0
                elif handle == "bl":
                    dy = 0

        self.setTransform(QTransform.fromScale(max(new_sx, 0.01), max(new_sy, 0.01)))
        self.setPos(p["start_pos"] + QPointF(dx, dy))
