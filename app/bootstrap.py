"""启动期的公共步骤。

入口在做任何事之前调用 :func:`prepare`：建目录、把旧版本留在程序目录里的
数据搬到新位置。「第一次运行」的判据是数据目录里有没有 ``app.json``。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from app import i18n, paths

_MB_ICONINFORMATION = 0x00000040
_MB_SETFOREGROUND = 0x00010000


def prepare() -> list[str]:
    """建目录并迁移旧数据，返回需要写进日志的警告。"""
    warnings: list[str] = []
    for folder in (paths.DATA_DIR, paths.LOCAL_DIR, paths.LOG_DIR, paths.LOCK_DIR):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            warnings.append(f"无法创建 {folder}：{error}")
    warnings.extend(paths.migrate_legacy())
    return warnings


def is_first_run() -> bool:
    """数据目录里还没有配置文件，就是第一次运行。"""
    return not paths.APP_CONFIG_PATH.exists()


def pythonw() -> Path:
    return paths.PYTHONW if paths.PYTHONW.is_file() else Path(sys.executable)


def restart_app() -> bool:
    """重启主程序：调用方先释放单实例锁，再调这里。"""
    try:
        subprocess.Popen(
            [str(pythonw()), str(paths.MAIN_ENTRY)],
            cwd=str(paths.PROGRAM_DIR),
            close_fds=True,
        )
        return True
    except OSError:
        return False


def info(message: str, title: str = "") -> None:
    """提示框（信息图标）。多开、需要用户知道但不致命的事情用它。"""
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None, str(message), title or "PDF Image Editor", _MB_ICONINFORMATION | _MB_SETFOREGROUND
        )
    except Exception:  # 弹窗失败时没有别的出口
        pass


def guard(main, name: str) -> None:
    """入口的最后一道防线：任何未捕获异常都变成「错误 + 时间 + 日志路径」弹窗。"""
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - 这里就是要兜住一切
        try:
            from app import logging_setup

            logging_setup.setup(name)
            logging_setup.fatal(
                i18n.t("fatal.unexpected", error=f"{type(error).__name__}: {error}")
            )
        except Exception:  # 连日志都起不来时只能静默退出
            os._exit(1)
