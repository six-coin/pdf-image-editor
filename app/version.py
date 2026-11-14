"""版本号。

全项目只有 ``pyproject.toml`` 里那一处版本号，运行期从那里读。读不出来时
返回 ``0.0.0``，不让版本号显示拦住启动。
"""

from __future__ import annotations

import tomllib
from functools import lru_cache

from app import paths


@lru_cache(maxsize=1)
def version() -> str:
    """当前程序版本，来自 ``pyproject.toml`` 的 ``project.version``。"""
    try:
        with (paths.PROGRAM_DIR / "pyproject.toml").open("rb") as handle:
            data = tomllib.load(handle)
        return str(data["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return "0.0.0"
