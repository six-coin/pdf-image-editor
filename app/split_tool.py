from enum import Enum, auto
from PySide6.QtCore import Qt, QPointF, QRectF, QLineF
from PySide6.QtGui import QPen, QColor, QTransform, QPixmap
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsScene


class SplitMode(Enum):
    IDLE = auto()
    HORIZONTAL = auto()
    VERTICAL = auto()


GUIDE_ACTIVE_COLOR = QColor(0, 200, 100, 100)
GUIDE_PLACED_COLOR = QColor(0, 200, 100, 180)


class SplitTool:
    def __init__(self, scene):
        self._scene = scene
        self._mode = SplitMode.IDLE
        self._target_image = None
        self._target_page = None
        self._h_guides = []
        self._v_guides = []
        self._active_line = None
        self._placed_lines = []
        self._on_guides_changed = None

    def set_guides_changed_callback(self, cb):
        self._on_guides_changed = cb

    def _notify_guides_changed(self):
        if self._on_guides_changed:
            self._on_guides_changed()

    @property
    def mode(self):
        return self._mode

    @property
    def is_active(self):
        return self._mode != SplitMode.IDLE

    def start(self, image_item, mode):
        if self._mode != SplitMode.IDLE:
            self.cancel()

        self._mode = mode
        self._target_image = image_item
        self._target_page = image_item.parentItem()
        self._h_guides = []
        self._v_guides = []
        self._placed_lines = []
        self._create_active_line()

    def _create_active_line(self):
        if self._active_line:
            self._scene.removeItem(self._active_line)
            self._active_line = None

        if self._target_image is None:
            return

        self._active_line = QGraphicsLineItem()
        self._active_line.setPen(QPen(GUIDE_ACTIVE_COLOR, 0))
        self._active_line.setZValue(200)
        self._scene.addItem(self._active_line)

    def mouse_moved(self, scene_pos):
        if not self.is_active or self._target_image is None:
            return
        if self._active_line is None:
            self._create_active_line()
            return

        rect = self._target_image.sceneBoundingRect()

        if self._mode == SplitMode.HORIZONTAL:
            y = max(rect.top(), min(rect.bottom(), scene_pos.y()))
            self._active_line.setLine(QLineF(rect.left(), y, rect.right(), y))
        else:
            x = max(rect.left(), min(rect.right(), scene_pos.x()))
            self._active_line.setLine(QLineF(x, rect.top(), x, rect.bottom()))

    def place_guide(self, scene_pos):
        if not self.is_active or self._target_image is None:
            return

        rect = self._target_image.sceneBoundingRect()
        if not rect.contains(scene_pos):
            return

        if self._mode == SplitMode.HORIZONTAL:
            y = scene_pos.y()
            frac = (y - rect.top()) / rect.height() if rect.height() > 0 else 0
            frac = max(0.0, min(1.0, frac))
            self._h_guides.append(frac)
        else:
            x = scene_pos.x()
            frac = (x - rect.left()) / rect.width() if rect.width() > 0 else 0
            frac = max(0.0, min(1.0, frac))
            self._v_guides.append(frac)

        self._redraw_placed()
        self._notify_guides_changed()

    def undo_last(self):
        if not self.is_active:
            return
        if self._mode == SplitMode.HORIZONTAL and self._h_guides:
            self._h_guides.pop()
        elif self._mode == SplitMode.VERTICAL and self._v_guides:
            self._v_guides.pop()
        else:
            return
        self._redraw_placed()
        self._notify_guides_changed()

    def switch_mode(self, new_mode):
        if self._mode == new_mode or self._mode == SplitMode.IDLE:
            return
        self._mode = new_mode
        self._redraw_placed()

    def _redraw_placed(self):
        for line in self._placed_lines:
            self._scene.removeItem(line)
        self._placed_lines.clear()

        if self._target_image is None:
            return

        rect = self._target_image.sceneBoundingRect()
        pen = QPen(GUIDE_PLACED_COLOR, 0)

        for frac in self._h_guides:
            y = rect.top() + frac * rect.height()
            line = QGraphicsLineItem(QLineF(rect.left(), y, rect.right(), y))
            line.setPen(pen)
            line.setZValue(200)
            self._scene.addItem(line)
            self._placed_lines.append(line)

        for frac in self._v_guides:
            x = rect.left() + frac * rect.width()
            line = QGraphicsLineItem(QLineF(x, rect.top(), x, rect.bottom()))
            line.setPen(pen)
            line.setZValue(200)
            self._scene.addItem(line)
            self._placed_lines.append(line)

    @property
    def has_cross_hairs(self):
        return len(self._h_guides) == 2 and len(self._v_guides) == 2

    def confirm_keep_middle(self, scene):
        if not self.has_cross_hairs or self._target_image is None or not self.is_active:
            return []

        rect = self._target_image.sceneBoundingRect()
        pixmap = self._target_image.pixmap()
        if pixmap is None:
            return []

        h_sorted = sorted(set(self._h_guides))
        v_sorted = sorted(set(self._v_guides))
        h_cuts = [0.0] + h_sorted + [1.0]
        v_cuts = [0.0] + v_sorted + [1.0]

        page_index = self._target_image.page_index
        parent = self._target_image.parentItem()
        old_pos = self._target_image.pos()
        old_t = self._target_image.transform()
        old_sx = old_t.m11()
        old_sy = old_t.m22()
        pw = pixmap.width()
        ph = pixmap.height()

        target = self._target_image
        original_state = target.get_state()

        self._cleanup()

        new_items = []
        for hi in range(len(h_cuts) - 1):
            for vi in range(len(v_cuts) - 1):
                h0, h1 = h_cuts[hi], h_cuts[hi + 1]
                v0, v1 = v_cuts[vi], v_cuts[vi + 1]
                src_x = int(v0 * pw)
                src_y = int(h0 * ph)
                src_w = int((v1 - v0) * pw)
                src_h = int((h1 - h0) * ph)
                if src_w <= 0 or src_h <= 0:
                    continue
                sub_pixmap = pixmap.copy(src_x, src_y, src_w, src_h)
                if sub_pixmap.isNull():
                    continue
                from app.image_item import ImageItem
                item = ImageItem(page_index, parent)
                item.setPixmap(sub_pixmap)
                new_x = old_pos.x() + v0 * pw * old_sx
                new_y = old_pos.y() + h0 * ph * old_sy
                item.setPos(new_x, new_y)
                item.setTransform(QTransform.fromScale(old_sx, old_sy))
                new_items.append(item)

        scene.removeItem(target)

        undo_stack = scene._undo_stack if hasattr(scene, "_undo_stack") and scene._undo_stack else None
        if undo_stack:
            from app.undo_commands import SplitCommand, DeleteCommand
            undo_stack.beginMacro("仅保留中间部分")
            all_states = []
            for item in new_items:
                scene.addItem(item)
                if parent and hasattr(parent, "add_image"):
                    parent.add_image(item)
                all_states.append(item.get_state())
            undo_stack.push(SplitCommand(scene, target, original_state, new_items, all_states))

            middle_idx = 4
            outer_data = []
            for i, item in enumerate(new_items):
                if i != middle_idx:
                    state = item.get_state()
                    p = item.parentItem()
                    outer_data.append({"item": item, "parent": p, "state": state})
                    if p and hasattr(p, "remove_image"):
                        p.remove_image(item)
                    scene.removeItem(item)
            if outer_data:
                undo_stack.push(DeleteCommand(scene, outer_data))
            undo_stack.endMacro()
            return [new_items[middle_idx]] if middle_idx < len(new_items) else []
        else:
            for item in new_items:
                scene.addItem(item)
                if parent and hasattr(parent, "add_image"):
                    parent.add_image(item)
            middle_idx = 4
            for i, item in enumerate(new_items):
                if i != middle_idx:
                    if item.parentItem() and hasattr(item.parentItem(), "remove_image"):
                        item.parentItem().remove_image(item)
                    scene.removeItem(item)
            return [new_items[middle_idx]] if middle_idx < len(new_items) else []

    def confirm(self, scene):
        """Split the image and return the new ImageItems."""
        if self._target_image is None or not self.is_active:
            self._cleanup()
            return []

        rect = self._target_image.sceneBoundingRect()
        pixmap = self._target_image.pixmap()
        if pixmap is None:
            self._cleanup()
            return []

        h_sorted = sorted(set(self._h_guides))
        v_sorted = sorted(set(self._v_guides))

        h_cuts = [0.0] + h_sorted + [1.0]
        v_cuts = [0.0] + v_sorted + [1.0]

        page_index = self._target_image.page_index
        parent = self._target_image.parentItem()
        old_pos = self._target_image.pos()
        old_t = self._target_image.transform()
        old_sx = old_t.m11()
        old_sy = old_t.m22()
        pw = pixmap.width()
        ph = pixmap.height()

        target = self._target_image
        original_state = target.get_state()

        self._cleanup()

        new_items = []

        for hi in range(len(h_cuts) - 1):
            for vi in range(len(v_cuts) - 1):
                h0, h1 = h_cuts[hi], h_cuts[hi + 1]
                v0, v1 = v_cuts[vi], v_cuts[vi + 1]

                src_x = int(v0 * pw)
                src_y = int(h0 * ph)
                src_w = int((v1 - v0) * pw)
                src_h = int((h1 - h0) * ph)

                if src_w <= 0 or src_h <= 0:
                    continue

                sub_pixmap = pixmap.copy(src_x, src_y, src_w, src_h)
                if sub_pixmap.isNull():
                    continue

                from app.image_item import ImageItem
                item = ImageItem(page_index, parent)
                item.setPixmap(sub_pixmap)

                new_x = old_pos.x() + v0 * pw * old_sx
                new_y = old_pos.y() + h0 * ph * old_sy
                item.setPos(new_x, new_y)
                item.setTransform(QTransform.fromScale(old_sx, old_sy))

                new_items.append(item)

        scene.removeItem(target)

        new_states = []
        for item in new_items:
            scene.addItem(item)
            if parent and hasattr(parent, "add_image"):
                parent.add_image(item)
            new_states.append(item.get_state())

        if scene and hasattr(scene, "_undo_stack") and scene._undo_stack:
            from app.undo_commands import SplitCommand
            scene._undo_stack.push(SplitCommand(scene, target, original_state, new_items, new_states))

        return new_items

    def confirm_punch_middle(self, scene):
        if not self.has_cross_hairs or self._target_image is None or not self.is_active:
            return []

        pixmap = self._target_image.pixmap()
        if pixmap is None:
            return []

        h_sorted = sorted(set(self._h_guides))
        v_sorted = sorted(set(self._v_guides))
        h0, h1 = h_sorted[0], h_sorted[1]
        v0, v1 = v_sorted[0], v_sorted[1]

        page_index = self._target_image.page_index
        parent = self._target_image.parentItem()
        old_pos = self._target_image.pos()
        old_t = self._target_image.transform()
        old_sx = old_t.m11()
        old_sy = old_t.m22()
        pw = pixmap.width()
        ph = pixmap.height()

        target = self._target_image
        original_state = target.get_state()

        self._cleanup()

        src_x = int(v0 * pw)
        src_y = int(h0 * ph)
        src_w = int((v1 - v0) * pw)
        src_h = int((h1 - h0) * ph)

        middle_pixmap = pixmap.copy(src_x, src_y, src_w, src_h)

        from PySide6.QtGui import QPainter
        from PySide6.QtCore import Qt
        hole_pixmap = pixmap.copy()
        painter = QPainter(hole_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.setBrush(Qt.white)
        painter.setPen(Qt.NoPen)
        painter.drawRect(QRectF(src_x, src_y, src_w, src_h))
        painter.end()

        from app.image_item import ImageItem
        new_item = ImageItem(page_index, parent)
        new_item.setPixmap(middle_pixmap)
        new_x = old_pos.x() + v0 * pw * old_sx
        new_y = old_pos.y() + h0 * ph * old_sy
        new_item.setPos(new_x, new_y)
        new_item.setTransform(QTransform.fromScale(old_sx, old_sy))

        scene.removeItem(target)

        target.setPixmap(hole_pixmap)
        target.setPos(old_pos)
        target.setTransform(QTransform.fromScale(old_sx, old_sy))
        target._page_index = page_index
        scene.addItem(target)
        if parent and hasattr(parent, "add_image"):
            parent.add_image(target)

        scene.addItem(new_item)
        if parent and hasattr(parent, "add_image"):
            parent.add_image(new_item)

        undo_stack = scene._undo_stack if hasattr(scene, "_undo_stack") and scene._undo_stack else None
        if undo_stack:
            from app.undo_commands import SplitCommand
            undo_stack.beginMacro("提取中间")
            undo_stack.push(SplitCommand(
                scene, target, original_state,
                [target, new_item],
                [target.get_state(), new_item.get_state()]
            ))
            undo_stack.endMacro()

        return [target, new_item]

    def cancel(self):
        self._cleanup()

    def _cleanup(self):
        if self._active_line:
            self._scene.removeItem(self._active_line)
            self._active_line = None
        for line in self._placed_lines:
            self._scene.removeItem(line)
        self._placed_lines.clear()
        self._h_guides = []
        self._v_guides = []
        self._mode = SplitMode.IDLE
        self._target_image = None
        self._target_page = None
