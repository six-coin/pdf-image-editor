"""日志配置与致命错误出口。

每次启动新建一个日志文件，出问题时能一眼定位是哪次运行。
``diagnose=False`` 避免把局部变量写进日志（密钥会跟着泄露）。
``.pyw`` 进程没有控制台，所以致命错误必须弹原生窗口。
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import NoReturn

from loguru import logger

from app import i18n, paths

_configured = False
_log_file: Path | None = None


class _InterceptHandler(logging.Handler):
    """把标准库 logging 接进 loguru。

    http.server、pymupdf 这些第三方库用的是标准库 logging，不接一下它们的
    输出就只会在 stderr 里，而 pythonw 下 stderr 是 None。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def log_file() -> Path | None:
    return _log_file


def setup(name: str, *, level: str = "DEBUG", enqueue: bool = True) -> Path:
    """配置 loguru 并挂上两个 excepthook。重复调用只生效一次。"""
    global _configured, _log_file
    if _configured and _log_file is not None:
        return _log_file

    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = paths.LOG_DIR / f"{name}_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

    logger.remove()
    logger.add(
        str(_log_file),
        level=level,
        encoding="utf-8",
        enqueue=enqueue,
        backtrace=True,
        diagnose=False,
        rotation="5 MB",
        retention="14 days",
        format="[{level}] [{time:YYYY-MM-DD HH:mm:ss}] {message}",
    )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    _configured = True
    logger.info("启动 {}", name)
    return _log_file


def _excepthook(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    logger.opt(exception=(exc_type, exc, tb)).critical("未捕获异常")
    fatal(i18n.t("fatal.unexpected", error=f"{exc_type.__name__}: {exc}"))


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    logger.opt(exception=(args.exc_type, args.exc_value, args.exc_traceback)).critical(
        "线程 {} 未捕获异常", args.thread.name if args.thread else "?"
    )


def fatal(message: str) -> NoReturn:
    """记日志 → 弹窗 → 立刻退出。用于启动期无法降级的错误。"""
    try:
        logger.critical(message)
        logger.complete()
    except Exception:
        # 日志系统本身坏了也要能把话说给用户听，这里只能吞。
        pass
    title = i18n.t("app.title")
    hint = i18n.t("fatal.log_hint", path=str(_log_file or paths.LOG_DIR))
    ctypes.windll.user32.MessageBoxW(None, f"{message}\n\n{hint}", title, 0x10)
    # 用 os._exit 而不是 sys.exit：后者会等所有非 daemon 线程，可能永远退不掉。
    import os

    os._exit(1)
