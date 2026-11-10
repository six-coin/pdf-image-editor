"""窗口装配。

启动顺序：日志 → API（配置错误在这里就能报）→ 资源服务 → 窗口 → 关闭握手。
"""

from __future__ import annotations

import ctypes
import logging

import webview

from app import i18n, logging_setup, paths
from app.system.asset_server import AssetServer
from app.ui.web.api import EditorApi

_LOGGER = logging.getLogger(__name__)

# 与页面 --bg 同色，否则首帧会闪白。
_BACKGROUND = {"light": "#f0f2f5", "dark": "#14161a"}


def _screen_size() -> tuple[int, int]:
    try:
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1600, 1000


def _make_closing_handler(api: EditorApi):
    def on_closing():
        if not api.dirty or api.close_confirmed:
            return True
        # closing 在 UI 线程执行，这里绝不能直接 evaluate_js，会死锁。
        api.request_close_prompt()
        return False

    return on_closing


def main() -> None:
    logging_setup.setup("pdf_image_editor")

    api = EditorApi()
    server = AssetServer(api, api.store, paths.WEB_DIR)
    server.start()
    api.attach_server(server)

    config = api.settings_snapshot
    i18n.set_language(config["language"])

    screen_w, screen_h = _screen_size()
    window = webview.create_window(
        i18n.t("app.title"),
        server.static_url(),
        js_api=api,
        width=int(screen_w * 0.85),
        height=int(screen_h * 0.85),
        min_size=(960, 640),
        background_color=_BACKGROUND.get(config["theme"], _BACKGROUND["light"]),
        text_select=False,
    )
    api.attach_window(window)
    window.events.closing += _make_closing_handler(api)

    try:
        webview.start()
    finally:
        server.stop()
        api.shutdown()


if __name__ == "__main__":
    main()
