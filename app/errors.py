"""异常类型。

约定：异常对象里带的是**已经本地化的文案**——在抛出那一刻用 ``i18n.t`` 取好，
界面层 ``str(exc)`` 就能直接显示。同时保留 ``key`` 与 ``params``，方便测试断言
和以后做二次翻译。代价是切换语言后已抛出的异常文案不会跟着变，单机工具可以接受。
"""

from __future__ import annotations

from typing import Any

from app import i18n


class AppError(Exception):
    """本程序抛出的所有异常的基类。"""

    def __init__(self, message: str = "", *, key: str | None = None, **params: Any) -> None:
        if key is not None:
            message = i18n.t(key, **params)
        super().__init__(message)
        self.key = key
        self.params = params


class ConfigError(AppError):
    """配置缺失、读不出来、结构不合法。"""


class PdfError(AppError):
    """PDF 打不开、解析失败、页号越界。"""


class SaveError(AppError):
    """写盘失败。"""


class ActionError(AppError):
    """单个编辑动作无法完成，但程序可以继续。"""
