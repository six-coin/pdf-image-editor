"""启动期的公共步骤。

入口在做任何事之前调用 :func:`ensure_cwd` 与 :func:`prepare`：把工作目录钉在
程序目录、建目录，并把数据目录搬迁的结果交给日志。「第一次运行」的判据是数据
目录里有没有 ``app.json``。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

from app import i18n, paths

_MB_ICONINFORMATION = 0x00000040
_MB_SETFOREGROUND = 0x00010000


def ensure_cwd() -> None:
    """把进程的工作目录固定到程序目录。

    工作目录是进程级全局状态，被所有线程共享，所以只在启动最早期调用一次（那时
    还没有任何线程）。之后谁都不许再改：内部路径一律由 :mod:`app.paths` 给绝对
    路径，切换 cwd 只会让「从快捷方式 / 计划任务启动」与「双击 bat 启动」产生两种
    行为。
    """
    try:
        os.chdir(paths.PROGRAM_DIR)
    except OSError:
        # 程序目录不可读时保持原样：内部路径全是绝对路径，不影响运行。
        pass


def _migration_warnings() -> list[str]:
    """把 ``paths.MIGRATION`` 翻成几条给人看的日志。"""
    result = paths.MIGRATION
    status = result["status"]
    if status == "done":
        messages = [f"数据目录已迁移 {result['moved']} 项：{result['source']} → {result['target']}"]
    elif status == "failed":
        messages = [f"数据目录迁移失败，仍在 {result['source']}，下次启动再试"]
    elif status == "nested":
        messages = [
            f"数据目录未搬迁：目标在源目录里面（{result['source']} → {result['target']}），已忽略"
        ]
    else:
        messages = []
    messages.extend(str(item) for item in result["warnings"])
    return messages


def prepare() -> list[str]:
    """建目录，返回需要写进日志的警告。"""
    warnings: list[str] = _migration_warnings()
    # pdfs 是打开对话框的默认落点，开机就建好：第一次点「打开」不该停在一个
    # 不存在的目录上。
    folders = (paths.DATA_DIR, paths.PDFS_DIR, paths.LOCAL_DIR, paths.LOG_DIR, paths.LOCK_DIR)
    for folder in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            warnings.append(f"无法创建 {folder}：{error}")
    return warnings


def is_first_run() -> bool:
    """数据目录里还没有配置文件，就是第一次运行。"""
    return not paths.APP_CONFIG_PATH.exists()


def pythonw() -> Path:
    return paths.PYTHONW if paths.PYTHONW.is_file() else Path(sys.executable)


def sync_language() -> None:
    """多开提示与崩溃弹窗要按用户选过的语言说话；读不到配置就用系统语言。

    这里直接读文件，不走 ``settings.load_app()``：那条路径会顺手写一份默认
    配置，把「第一次运行」标记冲掉。
    """
    i18n.set_language(current_language())


def current_language() -> str:
    """配置文件里记下的界面语言；没有或读不出来时按系统语言判定。"""
    try:
        raw = json.loads(paths.APP_CONFIG_PATH.read_text(encoding="utf-8"))
        language = raw["language"]
    except (OSError, ValueError, KeyError, TypeError):
        return i18n.initial_language()
    return language if isinstance(language, str) and language else i18n.initial_language()


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
            # 弹窗要说用户选的语言：这里可能发生在读配置之前，先同步一次。
            sync_language()
            logging_setup.fatal(
                i18n.t("fatal.unexpected", error=f"{type(error).__name__}: {error}")
            )
        except Exception:  # 连日志都起不来时只能静默退出
            os._exit(1)
