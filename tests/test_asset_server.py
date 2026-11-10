"""资源服务与快照接口。不启动窗口，只跑 HTTP。"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest


def test_empty_snapshot_is_safe(editor):
    instance, _server = editor
    snapshot = instance.get_state()
    assert snapshot["ok"] is True
    assert snapshot["doc"]["page_count"] == 0
    assert snapshot["pages"] == []


def test_open_and_render(editor, pdf_factory, wait):
    instance, _server = editor
    started = instance.open_path(str(pdf_factory()), force=True)
    assert started["ok"] is True
    assert wait(instance, started["task"])["state"] == "ready"

    snapshot = instance.get_state()
    assert snapshot["doc"]["page_count"] == 1
    assert snapshot["pages"][0]["w"] == pytest.approx(595, abs=1)

    page = instance.load_page(0, 96)
    assert page["ok"] is True
    assert len(page["objects"]) == 1
    assert page["objects"][0]["src"].startswith("http://127.0.0.1:")

    with urllib.request.urlopen(page["url"]) as response:
        body = response.read()
        assert response.headers["Content-Type"] == "image/png"
        assert body.startswith(b"\x89PNG")


def test_static_index_is_served(editor):
    _instance, server = editor
    with urllib.request.urlopen(server.static_url()) as response:
        text = response.read().decode("utf-8")
    assert "<!doctype html>" in text.lower()
    assert "main.js" in text


def test_wrong_token_is_404(editor):
    _instance, server = editor
    url = server.static_url().replace(server.token, "wrong-token")
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(url)
    assert info.value.code == 404


def test_path_traversal_is_blocked(editor):
    _instance, server = editor
    url = f"{server.base_url}/a/{server.token}/static/../api.py"
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(url)
    assert info.value.code == 404


def test_bad_arguments_return_snapshot_not_exception(editor, opened):
    instance, _server = editor
    opened()

    assert instance.load_page(99, 96)["ok"] is False
    assert instance.load_page("abc", 96)["ok"] is False
    assert instance.poll_task("nope")["state"] == "unknown"
    assert instance.update_settings({"undo_limit": 9999})["ok"] is True
    assert instance.get_state()["ok"] is True


def test_second_open_requires_force_when_dirty(editor, opened, pdf_factory):
    instance, _server = editor
    opened("a.pdf")

    from app.core.undo import StructureChanged

    instance._stack.push(StructureChanged([], []))  # noqa: SLF001 - 直接驱动内部状态
    blocked = instance.open_path(str(pdf_factory("b.pdf")))
    assert blocked["ok"] is False
    assert blocked["reason"] == "dirty"

    allowed = instance.open_path(str(pdf_factory("b.pdf")), force=True)
    assert allowed["ok"] is True
