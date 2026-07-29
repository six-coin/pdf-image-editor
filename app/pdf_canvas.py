from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QTransform, QPainter, QColor, QBrush, QMouseEvent
from PySide6.QtWidgets import QGraphicsView

from app.image_item import ImageItem
from app.undo_commands import TransformCommand


class PdfCanvas(QGraphicsView):
    zoom_changed = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self._split_tool = None
        self._undo_snapshots = {}

        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setBackgroundBrush(QBrush(QColor(60, 60, 60)))

        self.setScene(scene)
        self._apply_zoom()

    @property
    def zoom_level(self):
        return self._zoom

    @zoom_level.setter
    def zoom_level(self, value):
        self._zoom = max(0.1, min(10.0, value))
        self._apply_zoom()
        self.zoom_changed.emit(self._zoom)

    def set_split_tool(self, tool):
        self._split_tool = tool

    def _apply_zoom(self):
        self.setTransform(QTransform.fromScale(self._zoom, self._zoom))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y() / 120.0
            step = 0.1 if abs(delta) < 2 else 0.2
            self.zoom_level = self._zoom + delta * step
            return

        sb = self.verticalScrollBar()
        delta = event.angleDelta().y()
        new_val = sb.value() - delta
        new_val = max(sb.minimum(), min(sb.maximum(), new_val))
        sb.setValue(new_val)

    def mousePressEvent(self, event):
        if self._split_tool and self._split_tool.is_active:
            if event.button() == Qt.LeftButton:
                pt = event.position().toPoint()
                scene_pos = self.mapToScene(pt)
                target = self._split_tool._target_image
                if target and target.sceneBoundingRect().contains(scene_pos):
                    self._split_tool.place_guide(scene_pos)
                return
            elif event.button() == Qt.MiddleButton:
                self.setDragMode(QGraphicsView.ScrollHandDrag)
                fake_event = QMouseEvent(
                    event.type(), event.position(), Qt.LeftButton,
                    Qt.LeftButton, event.modifiers()
                )
                super().mousePressEvent(fake_event)
                return
            else:
                return

        if event.button() == Qt.LeftButton:
            self._undo_snapshots = self._capture_selected_states()

        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            fake_event = QMouseEvent(
                event.type(), event.position(), Qt.LeftButton,
                Qt.LeftButton, event.modifiers()
            )
            super().mousePressEvent(fake_event)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._split_tool and self._split_tool.is_active:
            pt = event.position().toPoint()
            scene_pos = self.mapToScene(pt)
            self._split_tool.mouse_moved(scene_pos)
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._split_tool and self._split_tool.is_active:
            if self.dragMode() == QGraphicsView.ScrollHandDrag:
                self.setDragMode(QGraphicsView.NoDrag)
            return

        if self.dragMode() == QGraphicsView.ScrollHandDrag:
            self.setDragMode(QGraphicsView.NoDrag)

        super().mouseReleaseEvent(event)

        scene = self.scene()
        if hasattr(scene, "check_cross_page_moves"):
            scene.check_cross_page_moves()

        self._commit_undo()

    def _capture_selected_states(self):
        scene = self.scene()
        if not hasattr(scene, "selectedItems"):
            return {}
        snapshots = {}
        for item in scene.selectedItems():
            if isinstance(item, ImageItem):
                snapshots[item] = item.get_state()
        return snapshots

    def _commit_undo(self):
        if not self._undo_snapshots:
            return
        scene = self.scene()
        changes = []
        for item, old_state in self._undo_snapshots.items():
            try:
                if item.scene() != scene:
                    continue
            except RuntimeError:
                continue
            new_state = item.get_state()
            if ImageItem.state_changed(old_state, new_state):
                changes.append((item, old_state, new_state))
        if changes and hasattr(scene, "_undo_stack") and scene._undo_stack:
            scene._undo_stack.push(TransformCommand(changes))
        self._undo_snapshots = {}

    def fit_to_width(self):
        sr = self.scene().sceneRect()
        if sr.width() > 0:
            self._zoom = (self.viewport().width() - 40) / sr.width()
            self._apply_zoom()
            self.zoom_changed.emit(self._zoom)

    def zoom_in(self):
        self.zoom_level = self._zoom * 1.2

    def zoom_out(self):
        self.zoom_level = self._zoom / 1.2
