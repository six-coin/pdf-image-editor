"""日志配置与致命错误出口。

日志写本地目录的 ``logs/``，每次启动新建一个带时间戳的文件——出问题时能一眼
定位是哪次运行。``diagnose=False``：默认会把局部变量全打进日志，密钥会跟着
泄露。

「自动清空一个月以前的日志」由 :func:`purge` 完成：启动时扫一遍目录，删掉超过
保留期的文件。不用 loguru 的 ``retention``，它只在轮转那一刻生效——日志目录
一直没涨到 5 MB 就永远不会清理，与这句承诺对不上。

``.pyw`` 进程没有控制台，所以致命错误必须弹原生窗口。弹窗统一三段：出了什么事、
发生时间、日志在哪。
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import NoReturn

from loguru import logger

from app import i18n, paths

#: 界面上可选的四个级别，顺序就是设置页里的顺序。
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
DEFAULT_LEVEL = "INFO"
#: 默认保留一个月，也就是「自动清空一个月以前的日志」。
DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365

_LOG_FORMAT = "[{level}] [{time:YYYY-MM-DD HH:mm:ss}] {message}"
_ROTATION = "5 MB"
_SECONDS_PER_DAY = 86400
_MB_ICONERROR = 0x00000010

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


def setup(
    name: str,
    *,
    level: str = DEFAULT_LEVEL,
    cleanup: bool = True,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> Path:
    """配置日志，返回本次的日志文件路径。

    只生效一次：``bootstrap.guard`` 在崩溃路径上还会再调一次，那时必须沿用
    已经开好的文件与用户选的设置，而不是新建一个文件、把级别打回默认值。
    之后要改设置请用 :func:`configure`。
    """
    global _log_file
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    if _log_file is not None:
        return _log_file
    _log_file = paths.LOG_DIR / f"{name}_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

    _install(level, cleanup, retention_days)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    return _log_file


def configure(
    *,
    level: str = DEFAULT_LEVEL,
    cleanup: bool = True,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> None:
    """按设置重配日志：文件不换，三项立刻生效。

    设置界面改完就调这里。文件名按启动时间取，所以「下次启动生效」只适用于
    文件名本身，不适用于级别与清理。
    """
    if _log_file is None:  # 还没 setup 过（测试里、或被 guard 提前拦下）
        return
    _install(level, cleanup, retention_days)


def log_file() -> Path | None:
    return _log_file


def purge(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """删掉超过保留期的日志文件，返回删掉的个数。

    只认 ``logs/*.log``：轮转出来的文件同样以 ``.log`` 结尾，一并按时间清掉。
    删不掉的文件（另一个进程正开着它）跳过——Windows 不允许删正在写的文件，
    下次启动再试一次就够了，不值得为此报错。
    """
    cutoff = datetime.now().timestamp() - _clamp_days(retention_days) * _SECONDS_PER_DAY
    removed = 0
    for path in paths.LOG_DIR.glob("*.log"):
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError as error:
            logger.debug("清理旧日志失败：{}（{}）", path.name, error)
    return removed


def _install(level: str, cleanup: bool, retention_days: int) -> None:
    """装好文件与 stderr 两个出口。级别先归一化，清理顺手做掉。"""
    normalized = _level(level)
    logger.remove()
    logger.add(
        str(_log_file),
        level=normalized,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,  # 不把局部变量写进日志，避免泄露密钥
        rotation=_ROTATION,
        format=_LOG_FORMAT,
    )
    if sys.stderr is not None:  # pythonw 下没有 stderr，控制台里跑时才加
        logger.add(sys.stderr, level=normalized, format=_LOG_FORMAT, colorize=True)
    if cleanup:
        purge(retention_days)


def _level(value: object) -> str:
    """认不出来的级别回退默认值：手改配置写成 ``verbose`` 不该拦住启动。"""
    text = str(value or "").strip().upper()
    return text if text in LOG_LEVELS else DEFAULT_LEVEL


def _clamp_days(value: object) -> int:
    try:
        days = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS
    return max(MIN_RETENTION_DAYS, min(days, MAX_RETENTION_DAYS))


def fatal(message: str) -> NoReturn:
    """记日志 → 弹窗 → 立刻退出。用于启动期无法降级的错误。"""
    try:
        logger.critical(message)
        logger.complete()
    except Exception:
        # 日志系统本身坏了也要能把话说给用户听，这里只能吞。
        pass
    try:
        ctypes.windll.user32.MessageBoxW(
            None, crash_text(message), i18n.t("app.title"), _MB_ICONERROR
        )
    except Exception:  # 弹窗失败时只能静默退出
        pass
    # 用 os._exit 而不是 sys.exit：后者会等所有非 daemon 线程，可能永远退不掉。
    os._exit(1)


def crash_text(message: str) -> str:
    """崩溃弹窗的正文：错误、时间、日志位置。"""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    where = str(_log_file or paths.LOG_DIR)
    return (
        f"{message}\n\n"
        f"{i18n.t('fatal.time_line', value=stamp)}\n"
        f"{i18n.t('fatal.log_line', value=where)}"
    )


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
    logger.opt(exception=(args.exc_type, args.exc_value, args.exc_traceback)).error(
        "线程 {} 中未捕获的异常", args.thread.name if args.thread else "?"
    )
