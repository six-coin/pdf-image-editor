"""文案查表。

启动时扫描 locales/ 目录，放进去什么语言就支持什么语言。
每种语言在文件里用 ``language.name`` 声明自己的显示名（用该语言自己的文字），
而且必须是文件里的第一个键；程序里不硬编码任何语言名。
缺键回退默认语言，再缺返回键名本身，绝不抛异常。
"""

from __future__ import annotations

import json
from typing import Any

from app import paths

DEFAULT_LANGUAGE = "zh-CN"

#: 语言包里的语言自称。用它自己的文字书写，界面上直接展示这个值。
NAME_KEY = "language.name"

_catalog: dict[str, dict[str, str]] = {}
_language: str = DEFAULT_LANGUAGE
_scan_cache: list[str] | None = None


def reset() -> None:
    """丢掉缓存。测试里切换语言目录后调用。"""
    global _scan_cache, _language
    _catalog.clear()
    _scan_cache = None
    _language = DEFAULT_LANGUAGE


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
    """返回可用的语言代码；目录里没有任何文件时至少返回默认语言。"""
    codes = _scan()
    return codes or [DEFAULT_LANGUAGE]


def set_language(code: str | None) -> str:
    """切换语言，非法代码回退默认语言。返回实际生效的代码。"""
    global _language
    codes = available()
    if code in codes:
        _language = str(code)
    elif DEFAULT_LANGUAGE in codes:
        _language = DEFAULT_LANGUAGE
    else:
        _language = codes[0]
    return _language


def current() -> str:
    return _language


def language_names() -> dict[str, str]:
    """语言代码 → 界面显示名。

    显示名由每种语言在自己的语言包里用 ``language.name`` 声明，所以列表里
    永远显示"简体中文 (中国)"而不是当前界面语言翻译出来的名字。缺键时退回
    语言代码本身。
    """
    names: dict[str, str] = {}
    for code in available():
        label = str(_load(code).get(NAME_KEY) or "").strip()
        names[code] = label or code
    return names


def strings(code: str | None = None) -> dict[str, str]:
    """给前端一次性下发的整张键表。

    以默认语言打底再覆盖当前语言：前端只有一张表、没有回退逻辑，缺键时会
    直接把键名画到界面上，所以这里就得补齐。
    """
    table = dict(_load(DEFAULT_LANGUAGE))
    table.update(_load(code or _language))
    return table


def t(key: str, **params: Any) -> str:
    """查表并填占位符。任何异常路径都返回可读文本，不抛出。"""
    text = _load(_language).get(key)
    if text is None:
        text = _load(DEFAULT_LANGUAGE).get(key)
    if text is None:
        return key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text
