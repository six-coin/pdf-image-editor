"""共享夹具。

所有测试都不碰真实的 config/ 与 logs/，PDF 一律现场生成，用完即弃。
"""

from __future__ import annotations

import time

import pymupdf
import pytest

from app import i18n, paths
from app.core.imagestore import ImageStore


@pytest.fixture(autouse=True)
def fixed_locale():
    """把语言钉死，断言文案时不用管环境。"""
    i18n.reset()
    i18n.set_language("zh-CN")
    yield
    i18n.reset()
    i18n.set_language("zh-CN")


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(paths, "APP_CONFIG_PATH", config_dir / "app.json")
    monkeypatch.setattr(paths, "REFERENCE_CONFIG_PATH", config_dir / "reference.json")
    monkeypatch.setattr(paths, "LEGACY_REFERENCE_PATH", config_dir / "reference_line.json")
    return config_dir


def _solid(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    return bytes(color) * (width * height)


@pytest.fixture
def pdf_factory(tmp_path):
    """生成测试用 PDF：带文字层和若干张不同尺寸的图片。"""

    def _make(
        name: str = "sample.pdf",
        *,
        text: str = "Hello text layer",
        images: int = 1,
        pages: int = 1,
        size: tuple[float, float] = (595.0, 842.0),
    ) -> object:
        doc = pymupdf.open()
        for index in range(pages):
            page = doc.new_page(width=size[0], height=size[1])
            if text:
                page.insert_text((72, 72), f"{text} {index + 1}", fontsize=16)
            for slot in range(images):
                width = 40 + slot * 20
                height = 30 + slot * 10
                color = (255, 0, 0) if slot == 0 else (0, 0, 255)
                pix = pymupdf.Pixmap(
                    pymupdf.csRGB, width, height, _solid(width, height, color), False
                )
                x0 = 100 + slot * 120
                page.insert_image(pymupdf.Rect(x0, 100, x0 + 200, 250), pixmap=pix)
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return path

    return _make


@pytest.fixture
def store():
    return ImageStore()


@pytest.fixture
def editor(temp_config):
    """起一个真实的 EditorApi + 资源服务，不建窗口。"""
    from app.system.asset_server import AssetServer
    from app.ui.web.api import EditorApi

    instance = EditorApi()
    server = AssetServer(instance, instance.store, paths.WEB_DIR)
    server.start()
    instance.attach_server(server)
    yield instance, server
    server.stop()
    instance.shutdown()


def wait_task(instance, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    status = {"state": "timeout"}
    while time.time() < deadline:
        status = instance.poll_task(task_id)
        if status.get("state") != "running":
            return status
        time.sleep(0.02)
    return status


@pytest.fixture
def wait():
    return wait_task


@pytest.fixture
def opened(editor, pdf_factory):
    """打开一个测试文档并把所有页都装载好，返回路径。"""

    def _open(name: str = "sample.pdf", **kwargs):
        instance, _server = editor
        path = pdf_factory(name, **kwargs)
        started = instance.open_path(str(path), force=True)
        assert started["ok"] is True
        assert wait_task(instance, started["task"])["state"] == "ready"
        for index in range(instance.get_state()["doc"]["page_count"]):
            assert instance.load_page(index, 96)["ok"] is True
        return path

    return _open
