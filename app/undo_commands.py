from PySide6.QtGui import QUndoCommand


class TransformCommand(QUndoCommand):
    def __init__(self, changes):
        super().__init__("移动/缩放")
        self._changes = changes

    def undo(self):
        for item, old_state, _ in self._changes:
            item.apply_state(old_state)

    def redo(self):
        for item, _, new_state in self._changes:
            item.apply_state(new_state)


class DeleteCommand(QUndoCommand):
    def __init__(self, scene, items_data):
        super().__init__("删除")
        self._scene = scene
        self._items_data = items_data

    def undo(self):
        for d in self._items_data:
            item = d["item"]
            item.setParentItem(d["parent"])
            if d["parent"] and hasattr(d["parent"], "add_image"):
                d["parent"].add_image(item)
            self._scene.addItem(item)
            item.apply_state(d["state"])

    def redo(self):
        for d in self._items_data:
            item = d["item"]
            if item.parentItem() and hasattr(item.parentItem(), "remove_image"):
                item.parentItem().remove_image(item)
            self._scene.removeItem(item)


class SplitCommand(QUndoCommand):
    def __init__(self, scene, original_item, original_state, new_items, new_states):
        super().__init__("分割")
        self._scene = scene
        self._original_item = original_item
        self._original_state = original_state
        self._new_items = new_items
        self._new_states = new_states

    def undo(self):
        for item in self._new_items:
            if item.parentItem() and hasattr(item.parentItem(), "remove_image"):
                item.parentItem().remove_image(item)
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._original_item.setParentItem(self._original_state["parent"])
        if self._original_state["parent"] and hasattr(self._original_state["parent"], "add_image"):
            self._original_state["parent"].add_image(self._original_item)
        self._scene.addItem(self._original_item)
        self._original_item.apply_state(self._original_state)

    def redo(self):
        if self._original_item.scene() == self._scene:
            self._scene.removeItem(self._original_item)
        for item, state in zip(self._new_items, self._new_states):
            item.setParentItem(state["parent"])
            if state["parent"] and hasattr(state["parent"], "add_image"):
                state["parent"].add_image(item)
            self._scene.addItem(item)
            item.apply_state(state)


class AddWhiteRectCommand(QUndoCommand):
    def __init__(self, scene, item, parent):
        super().__init__("添加矩形")
        self._scene = scene
        self._item = item
        self._parent = parent
        self._state = item.get_state()

    def undo(self):
        if self._item.parentItem() and hasattr(self._item.parentItem(), "remove_image"):
            self._item.parentItem().remove_image(self._item)
        self._scene.removeItem(self._item)

    def redo(self):
        self._item.setParentItem(self._parent)
        if self._parent and hasattr(self._parent, "add_image"):
            self._parent.add_image(self._item)
        self._scene.addItem(self._item)
        self._item.apply_state(self._state)
