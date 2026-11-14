"""用系统默认程序打开文件。

工作目录必须显式传：进程 cwd 是程序目录（见 ``bootstrap.ensure_cwd``），不是被
打开文件所在的目录，外部编辑器按相对路径找资源就会失败。
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger


def open_external(path: Path) -> bool:
    """用关联程序打开。返回是否成功发起，不等待它关闭。"""
    try:
        os.startfile(str(path), cwd=str(path.parent))
        return True
    except OSError:
        logger.exception("无法打开外部程序 {}", path)
        return False
