"""撤销栈：幂等、往返、宏、深度上限、脏标记。"""

from __future__ import annotations

from app.core.undo import (
    ImageReplaced,
    ObjectsChanged,
    StructureChanged,
    UndoStack,
)
from app.models import DocumentState, ImageObject, Rect


def _object(object_id: str = "a", x: float = 0.0, z: int = 10) -> ImageObject:
    return ImageObject(id=object_id, page=0, rect=Rect(x, 0, 10, 10), image_id="img", z=z)


def test_push_applies_immediately():
    state = DocumentState()
    stack = UndoStack(state)
    stack.push(StructureChanged([], [_object()]))
    assert state.find("a") is not None


def test_apply_is_idempotent():
    state = DocumentState()
    stack = UndoStack(state)
    command = StructureChanged([], [_object()])
    stack.push(command)
    command.apply(state)
    command.apply(state)
    assert len(state.objects) == 1


def test_undo_and_redo_roundtrip():
    state = DocumentState()
    stack = UndoStack(state)
    stack.push(StructureChanged([], [_object()]))

    assert stack.undo() is True
    assert state.objects == []
    assert stack.redo() is True
    assert len(state.objects) == 1


def test_undo_on_empty_stack_is_false():
    stack = UndoStack(DocumentState())
    assert stack.undo() is False
    assert stack.redo() is False


def test_objects_changed_moves_and_restores():
    state = DocumentState(objects=[_object()])
    stack = UndoStack(state)
    before = state.find("a").clone()
    after = state.find("a").clone()
    after.rect = Rect(50, 50, 10, 10)

    stack.push(ObjectsChanged([before], [after]))
    assert state.find("a").rect.x == 50

    stack.undo()
    assert state.find("a").rect.x == 0


def test_macro_collapses_into_one_entry():
    state = DocumentState()
    stack = UndoStack(state)
    stack.begin_macro("edit.split")
    stack.push(StructureChanged([], [_object("a")]))
    stack.push(StructureChanged([_object("a")], [_object("a"), _object("b")]))
    stack.end_macro()

    assert stack.depth == 1
    assert len(state.objects) == 2

    stack.undo()
    assert state.objects == []


def test_image_replaced_swaps_ids():
    state = DocumentState(objects=[_object()])
    stack = UndoStack(state)
    stack.push(ImageReplaced("a", "old", "new"))
    assert state.find("a").image_id == "new"
    stack.undo()
    assert state.find("a").image_id == "old"


def test_dirty_follows_position():
    state = DocumentState()
    stack = UndoStack(state)
    assert stack.dirty is False

    stack.push(StructureChanged([], [_object("a")]))
    assert stack.dirty is True

    stack.mark_saved()
    assert stack.dirty is False

    stack.push(StructureChanged([_object("a")], [_object("a"), _object("b")]))
    assert stack.dirty is True

    stack.undo()
    assert stack.dirty is False


def test_new_branch_after_undo_is_dirty():
    state = DocumentState()
    stack = UndoStack(state)
    stack.push(StructureChanged([], [_object("a")]))
    stack.mark_saved()
    stack.push(StructureChanged([_object("a")], [_object("a"), _object("b")]))
    stack.undo()
    stack.push(StructureChanged([_object("a")], [_object("c")]))
    assert stack.dirty is True


def test_limit_drops_oldest_entries():
    state = DocumentState()
    stack = UndoStack(state, limit=2)
    for index in range(4):
        stack.push(StructureChanged([], [_object(str(index))]))
    assert stack.depth == 2


def test_clear_resets_everything():
    state = DocumentState()
    stack = UndoStack(state)
    stack.push(StructureChanged([], [_object("a")]))
    stack.clear()
    assert stack.depth == 0
    assert stack.can_undo is False
    assert stack.dirty is False
