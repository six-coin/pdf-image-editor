"""外观：只有浅色与深色两种，没有「跟随系统」。

首次启动读一次系统偏好作为默认值，之后一律以设置为准。
"""

from __future__ import annotations

import os

THEMES = ("light", "dark")
DEFAULT = "light"


def system_theme() -> str:
    """读 Windows 的应用主题偏好。读不到就回退浅色。"""
    if os.name != "nt":
        return DEFAULT
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) else "dark"
    except (OSError, ValueError, ImportError):
        return DEFAULT


def resolve(value: object) -> str:
    """把任意来源的值压成 light/dark。

    旧配置里可能还写着 ``system``：按当时的系统偏好定一次，之后就固定下来。
    其余无法识别的值回退浅色——一个拼错的词不该让界面变黑。
    """
    if value == "dark":
        return "dark"
    if value == "system":
        return system_theme()
    return DEFAULT
