"""窗口装配。

启动顺序：cwd → 目录准备 → 单实例 → 日志 → API（配置错误在这里就能报）→ 资源
服务 → 窗口 → 关闭握手。关窗后如果用户点过「立即重启」，由这里在释放单实例
锁之后拉起新进程——数据目录的搬迁只发生在启动早期，重开窗口是搬不动的。
"""

from __future__ import annotations

import ctypes
import logging
import subprocess

import webview
from webview.dom import DOMEventHandler

from app import bootstrap, i18n, logging_setup, paths
from app import settings as settings_module
from app.errors import ConfigError
from app.system.asset_server import AssetServer
from app.system.single import MAIN_MUTEX, InstanceLock, activate_window
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


def _install_file_drop(window: webview.Window, api: EditorApi) -> None:
    """把「拖文件进窗口」接到页面上。

    WebView2 只把文件的完整路径交给宿主，页面自己拿不到——所以这里必须用
    pywebview 的 DOM drop 事件，而不是页面里的 drag 监听。``prevent_default``
    顺手挡住 WebView2 默认的「把拖进来的文件当网页打开」。

    绑定必须等页面加载完：``loaded`` 的回调本来就在工作线程里跑，不占 UI 线程。
    """

    def on_drop(event) -> None:
        transfer = event.get("dataTransfer") if isinstance(event, dict) else None
        files = (transfer or {}).get("files") or []
        for item in files:
            full = item.get("pywebviewFullPath") if isinstance(item, dict) else None
            if full:
                # 一次只能开一个文档：多选拖进来时只认第一个。
                api.offer_drop(str(full))
                return
        if files:
            # 没有完整路径就打不开文件，留一条日志，免得只剩「拖了没反应」。
            _LOGGER.warning("拖入的文件没有完整路径：%s", files)

    def on_loaded() -> None:
        try:
            window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)
        except Exception:
            # 注册失败只影响拖拽打开，不能拖累启动与其它功能。
            _LOGGER.exception("注册拖拽打开失败")

    window.events.loaded += on_loaded


def main() -> None:
    # 第一件事：把工作目录钉在程序目录。之后不再改，见 bootstrap.ensure_cwd。
    bootstrap.ensure_cwd()
    warnings = bootstrap.prepare()
    lock = InstanceLock(MAIN_MUTEX)
    if not lock.acquire():
        _activate_existing()
        return

    api: EditorApi | None = None
    try:
        api = _run(warnings)
    finally:
        lock.release()
    if api is not None and api.restart_requested:
        _relaunch()


def _run(warnings: list[str]) -> EditorApi | None:
    # 日志文件名跟入口名走：main.pyw 写 main_*.log。
    logging_setup.setup("main")

    try:
        api = EditorApi()
    except ConfigError as error:
        logging_setup.fatal(str(error))
        return None
    for warning in warnings:
        _LOGGER.warning(warning)

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
    _install_file_drop(window, api)

    try:
        webview.start()
    finally:
        server.stop()
        api.shutdown()
    return api


def _relaunch() -> None:
    """释放单实例锁之后拉起一个新进程。

    数据目录的搬迁只在启动早期、所有业务模块打开文件之前发生，所以「改完目录
    重启」必须是真重启。锁在调用本函数之前已经放掉，新进程不会撞上「已经在运行」。
    """
    command = [str(bootstrap.pythonw()), str(paths.MAIN_ENTRY)]
    try:
        subprocess.Popen(command, cwd=str(paths.PROGRAM_DIR), close_fds=True)
    except OSError as error:
        _LOGGER.error("重启失败：{}", error)
        bootstrap.info(i18n.t("about.restart_failed", error=error), i18n.t("app.title"))


def _activate_existing() -> None:
    """已经有一个窗口开着：把它提到前面，然后安静退出。

    不再弹「已经在运行」的框：用户点第二次的意思就是「让我看到那个窗口」，
    窗到前台就够了；提不上来（窗口标题对不上、被别的会话占用）也只留一条
    日志，双击完弹一个框只会让人以为出了故障。
    """
    try:
        i18n.set_language(str(settings_module.load_app()["language"]))
    except Exception:  # 读配置失败不该挡住「多开」这条路径
        pass
    if activate_window(i18n.t("app.title")):
        return
    # 提不上来也要留一条记录：「双击了没反应」是最难解释的现象。
    logging_setup.setup("main")
    _LOGGER.info("已有实例在运行，但没能把窗口提到前面")


if __name__ == "__main__":
    main()
