from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import QGraphicsObject
from PySide6.QtGui import QPainter, QColor, QBrush


class PageItem(QGraphicsObject):
    def __init__(self, page_index, page_size, background_pixmap, parent=None):
        super().__init__(parent)
        self._page_index = page_index
        self._page_size = page_size
        self._background = background_pixmap
        self._images = []

    @property
    def page_index(self):
        return self._page_index

    def pageRect(self):
        return QRectF(0, 0, self._page_size.width(), self._page_size.height())

    def boundingRect(self):
        return self.pageRect()

    def paint(self, painter, option, widget):
        r = self.pageRect()
        painter.setBrush(QBrush(QColor(240, 240, 240)))
        painter.setPen(Qt.NoPen)
        painter.drawRect(r)
        if self._background and not self._background.isNull():
            src = QRectF(0, 0, self._background.width(), self._background.height())
            painter.drawPixmap(r, self._background, src)

    def add_image(self, image_item):
        image_item.setParentItem(self)
        self._images.append(image_item)

    def remove_image(self, image_item):
        if image_item in self._images:
            self._images.remove(image_item)
        image_item.setParentItem(None)

    def images(self):
        return list(self._images)

    def accept_image(self, image_item):
        page_h = self._page_size.height()
        scene_pos = image_item.scenePos()
        local_pos = self.mapFromScene(scene_pos)
        display_h = image_item.display_rect().height()
        if display_h <= 0:
            display_h = 10

        margin = display_h * 0.5
        return -margin <= local_pos.y() <= page_h + margin
