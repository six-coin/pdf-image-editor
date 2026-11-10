"""撤销栈。

命令只存几何与图片 id，不存像素：图片字节在 ``ImageStore`` 里按 sha1 常驻，
撤销只是把 ``image_id`` 指回去。``apply`` 必须是幂等的——按 id 覆盖，不是追加。
"""

from __future__ import annotations

from app.models import DocumentState, ImageObject


class Command:
    label: str = ""

    def apply(self, state: DocumentState) -> None:
        raise NotImplementedError

    def revert(self, state: DocumentState) -> None:
        raise NotImplementedError


class ObjectsChanged(Command):
    """移动、缩放、改 z、改页码——只动已有对象。"""

    def __init__(
        self, before: list[ImageObject], after: list[ImageObject], label: str = "edit.move"
    ) -> None:
        self._before = [o.clone() for o in before]
        self._after = [o.clone() for o in after]
        self.label = label

    def apply(self, state: DocumentState) -> None:
        state.upsert(self._after)

    def revert(self, state: DocumentState) -> None:
        state.upsert(self._before)


class StructureChanged(Command):
    """增、删、切分、打孔——对象集合本身变了，存整份列表。"""

    def __init__(
        self, before: list[ImageObject], after: list[ImageObject], label: str = "edit.structure"
    ) -> None:
        self._before = [o.clone() for o in before]
        self._after = [o.clone() for o in after]
        self.label = label

    def apply(self, state: DocumentState) -> None:
        state.replace_all(self._after)

    def revert(self, state: DocumentState) -> None:
        state.replace_all(self._before)


class ImageReplaced(Command):
    """外部编辑器改完图，只换 image_id。"""

    def __init__(
        self,
        object_id: str,
        before_image: str,
        after_image: str,
        label: str = "edit.image",
    ) -> None:
        self._object_id = object_id
        self._before_image = before_image
        self._after_image = after_image
        self.label = label

    def _swap(self, state: DocumentState, image_id: str) -> None:
        obj = state.find(self._object_id)
        if obj is not None:
            obj.image_id = image_id

    def apply(self, state: DocumentState) -> None:
        self._swap(state, self._after_image)

    def revert(self, state: DocumentState) -> None:
        self._swap(state, self._before_image)


class MacroCommand(Command):
    """复合操作合并成一条，一次撤销全退。"""

    def __init__(self, label: str, commands: list[Command]) -> None:
        self.label = label
        self._commands = list(commands)

    def apply(self, state: DocumentState) -> None:
        for command in self._commands:
            command.apply(state)

    def revert(self, state: DocumentState) -> None:
        for command in reversed(self._commands):
            command.revert(state)


class UndoStack:
    def __init__(self, state: DocumentState, limit: int = 100) -> None:
        self._state = state
        self._limit = max(1, int(limit))
        self._entries: list[tuple[int, Command]] = []
        self._index = 0
        self._serial = 0
        self._saved = 0
        self._macro: list[Command] | None = None
        self._macro_label = ""

    # ---- 查询 ----

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._entries)

    @property
    def depth(self) -> int:
        return len(self._entries)

    @property
    def label(self) -> str:
        if self._index == 0:
            return ""
        return self._entries[self._index - 1][1].label

    @property
    def _position(self) -> int:
        return self._entries[self._index - 1][0] if self._index else 0

    @property
    def dirty(self) -> bool:
        return self._position != self._saved

    # ---- 修改 ----

    def push(self, command: Command) -> None:
        """入栈并立刻生效。重复 apply 同一命令结果不变。"""
        if self._macro is not None:
            command.apply(self._state)
            self._macro.append(command)
            return
        self._entries = self._entries[: self._index]
        self._serial += 1
        command.apply(self._state)
        self._entries.append((self._serial, command))
        self._index += 1
        self._trim()

    def undo(self) -> bool:
        if not self.can_undo:
            return False
        self._index -= 1
        self._entries[self._index][1].revert(self._state)
        return True

    def redo(self) -> bool:
        if not self.can_redo:
            return False
        self._entries[self._index][1].apply(self._state)
        self._index += 1
        return True

    def clear(self) -> None:
        self._entries.clear()
        self._index = 0
        self._serial = 0
        self._saved = 0
        self._macro = None

    def mark_saved(self) -> None:
        self._saved = self._position

    # ---- 宏 ----

    def begin_macro(self, label: str) -> None:
        if self._macro is not None:
            return
        self._macro = []
        self._macro_label = label

    def end_macro(self) -> None:
        commands = self._macro
        self._macro = None
        if not commands:
            return
        if len(commands) == 1:
            macro: Command = commands[0]
        else:
            macro = MacroCommand(self._macro_label, commands)
        self._entries = self._entries[: self._index]
        self._serial += 1
        self._entries.append((self._serial, macro))
        self._index += 1
        self._trim()

    def _trim(self) -> None:
        while len(self._entries) > self._limit:
            serial, _ = self._entries.pop(0)
            self._index -= 1
            if self._saved == serial:
                # 存档点已被挤出栈外，再也回不去了。
                self._saved = -1
