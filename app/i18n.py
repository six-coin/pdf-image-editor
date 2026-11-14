"""文案查表。

启动时扫描 locales/ 目录，放进去什么语言就支持什么语言，**文件名就是语言
代码**。列表顺序就是文件名的字典序，不对中文特判。

每种语言在文件里用 ``language.name`` 声明自己的显示名（用该语言自己的文字），
而且必须是文件里的第一个键；程序里不硬编码任何语言名。

缺键回退到 ``en-US``，再缺返回键名本身，绝不抛异常。
"""

from __future__ import annotations

import ctypes
import json
import locale
import os
from typing import Any

from app import paths

#: 找不到系统语言时的回退。
FALLBACK_LANGUAGE = "en-US"

#: 语言包里的语言自称。用它自己的文字书写，界面上直接展示这个值。
NAME_KEY = "language.name"

_catalog: dict[str, dict[str, str]] = {}
_language: str = FALLBACK_LANGUAGE
_scan_cache: list[str] | None = None


def reset() -> None:
    """丢掉缓存。测试里切换语言目录后调用。"""
    global _scan_cache, _language
    _catalog.clear()
    _scan_cache = None
    _language = FALLBACK_LANGUAGE


def _scan() -> list[str]:
    global _scan_cache
    if _scan_cache is None:
        if paths.LOCALES_DIR.is_dir():
            _scan_cache = sorted(p.stem for p in paths.LOCALES_DIR.glob("*.json"))
        else:
            _scan_cache = []
    return _scan_cache


def _load(code: str) -> dict[str, str]:
    if code in _catalog:
        return _catalog[code]
    path = paths.LOCALES_DIR / f"{code}.json"
    table: dict[str, str] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            table = {str(k): str(v) for k, v in raw.items()}
    _catalog[code] = table
    return table


def available() -> list[str]:
    """可用的语言代码，按文件名排序；目录里没有文件时至少返回英语。"""
    return _scan() or [FALLBACK_LANGUAGE]


def system_language() -> str:
    """系统界面语言，映射到已安装的语言代码；都没有就用英语。"""
    codes = available()
    candidates: list[str] = []
    if os.name == "nt":
        try:
            lcid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
            name = locale.windows_locale.get(lcid)
            if name:
                candidates.append(name.replace("_", "-"))
        except Exception:  # 取不到系统语言时按下面的环境变量与回退处理
            pass
    raw = os.environ.get("LANG") or os.environ.get("LC_ALL") or ""
    if raw:
        candidates.append(raw.split(".")[0].replace("_", "-"))

    for code in candidates:
        if code in codes:
            return code
    for code in candidates:
        primary = code.split("-")[0].lower()
        for installed in codes:
            if installed.split("-")[0].lower() == primary:
                return installed
    return FALLBACK_LANGUAGE if FALLBACK_LANGUAGE in codes else codes[0]


def initial_language() -> str:
    """第一次启动时的界面语言：系统语言在列表里就用它，否则英语。"""
    return system_language()


def set_language(code: str | None) -> str:
    """切换语言，非法代码回退英语。返回实际生效的代码。"""
    global _language
    codes = available()
    if code in codes:
        _language = str(code)
    elif FALLBACK_LANGUAGE in codes:
        _language = FALLBACK_LANGUAGE
    else:
        _language = codes[0]
    return _language


def current() -> str:
    return _language


def language_names() -> dict[str, str]:
    """语言代码 → 界面显示名。显示名由各语言自己声明，缺键退回代码。"""
    names: dict[str, str] = {}
    for code in available():
        label = str(_load(code).get(NAME_KEY) or "").strip()
        names[code] = label or code
    return names


def strings(code: str | None = None) -> dict[str, str]:
    """给前端一次性下发的整张键表：英语打底，当前语言覆盖。"""
    table = dict(_load(FALLBACK_LANGUAGE))
    table.update(_load(code or _language))
    return table


def t(key: str, **params: Any) -> str:
    """查表并填占位符。任何异常路径都返回可读文本，不抛出。"""
    text = _load(_language).get(key)
    if text is None:
        text = _load(FALLBACK_LANGUAGE).get(key)
    if text is None:
        return key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text
