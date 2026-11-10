"""静态守卫：分层没被破坏、没有 chdir、没有 print、入口够薄。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
ENTRY = ROOT / "pdf_image_editor.pyw"

UI_LIBS = {"PySide6", "PyQt5", "PyQt6", "webview"}


def _sources(directory: Path):
    for path in sorted(directory.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def _imported(text: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _calls(text: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_core_has_no_ui_imports():
    for path, text in _sources(APP / "core"):
        roots = {m.split(".")[0] for m in _imported(text)}
        assert not (roots & UI_LIBS), path.name


def test_core_does_not_reach_up():
    for path, text in _sources(APP / "core"):
        modules = _imported(text)
        assert not [m for m in modules if m.startswith("app.ui")], path.name
        assert not [m for m in modules if m.startswith("app.system")], path.name


def test_system_has_no_ui_imports():
    directory = APP / "system"
    if not directory.is_dir():
        return
    for path, text in _sources(directory):
        roots = {m.split(".")[0] for m in _imported(text)}
        assert not (roots & UI_LIBS), path.name
        assert not [m for m in _imported(text) if m.startswith("app.ui")], path.name


def test_no_chdir_anywhere():
    for path, text in _sources(APP):
        assert "chdir" not in _calls(text), path.name


def test_no_print_anywhere():
    for path, text in _sources(APP):
        assert "print" not in _calls(text), path.name


def test_entry_is_thin():
    lines = [line for line in ENTRY.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) < 30


def test_every_module_has_a_docstring():
    for path, text in _sources(APP):
        module = ast.parse(text)
        assert ast.get_docstring(module), path.name
