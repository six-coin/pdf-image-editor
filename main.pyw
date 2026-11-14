"""PDF Image Editor 主程序入口。

双击 run.bat 时由虚拟环境里的 pythonw.exe 执行本文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _run() -> None:
    from app import bootstrap
    from app.ui.web.app import main

    bootstrap.guard(main, "pdf_image_editor")


if __name__ == "__main__":
    _run()
