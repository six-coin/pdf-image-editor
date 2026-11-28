"""字体表。

文本框只支持六种字体，路径写死在这里——程序是 Windows 专用，系统字体一定在。
``pymupdf.Font`` 解析一份 .ttc 要几十毫秒、占几十兆内存，所以按需加载并缓存：
不打开文本框就一份都不加载。

字体文件缺失时退回 Helvetica：画不出汉字，但不会让保存整页失败。
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

import pymupdf

# (键, CSS 里的族名, 候选文件名)。键会写进 PDF 的 /SixCoin 里，不能随便改。
FAMILIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("msyh", "Microsoft YaHei", ("msyh.ttc", "msyh.ttf")),
    ("simsun", "SimSun", ("simsun.ttc", "simsun.ttf")),
    ("simfang", "FangSong", ("simfang.ttf",)),
    ("simkai", "KaiTi", ("simkai.ttf",)),
    ("simhei", "SimHei", ("simhei.ttf",)),
    ("times", "Times New Roman", ("times.ttf",)),
)

DEFAULT_FAMILY = "msyh"

_FALLBACK = "helv"
_cache: dict[str, pymupdf.Font] = {}
_lock = Lock()


def families() -> tuple[str, ...]:
    return tuple(key for key, _name, _files in FAMILIES)


def css_name(key: str) -> str:
    for name, family, _files in FAMILIES:
        if name == key:
            return family
    return FAMILIES[0][1]


def font_dir() -> Path:
    """系统字体目录。测试可以用 ``SIXCOIN_FONT_DIR`` 指到别处。"""
    override = os.environ.get("SIXCOIN_FONT_DIR")
    if override:
        return Path(override)
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    return Path(windir) / "Fonts"


def font_path(key: str) -> Path | None:
    for name, _css, files in FAMILIES:
        if name != key:
            continue
        for filename in files:
            candidate = font_dir() / filename
            if candidate.is_file():
                return candidate
    return None


def font(key: str) -> pymupdf.Font:
    """取一份（缓存的）字体对象。未知的键按默认字体处理。"""
    name = key if key in families() else DEFAULT_FAMILY
    with _lock:
        cached = _cache.get(name)
        if cached is not None:
            return cached
        path = font_path(name)
        try:
            loaded = pymupdf.Font(fontfile=str(path)) if path else pymupdf.Font(_FALLBACK)
        except Exception:
            # 字体文件损坏或格式不认识：退回内置字体，至少不中断保存。
            loaded = pymupdf.Font(_FALLBACK)
        _cache[name] = loaded
        return loaded


def normalize(key: object) -> str:
    text = str(key).strip() if key is not None else ""
    return text if text in families() else DEFAULT_FAMILY


def missing_glyphs(text: str, key: str) -> bool:
    """这段文字在这个字体里有没有缺字。缺字时 MuPDF 会静默换成别的字体。"""
    target = font(key)
    for char in text:
        if char in "\n\r\t ":
            continue
        if not target.has_glyph(ord(char)):
            return True
    return False


def retarget_runs(runs: list[tuple[str, str]], key: str) -> list[tuple[str, str]]:
    """把文字段换成目标字体，但只换目标字体真正有字形的字符。

    例如全选一段「中文 abc」并选 Times New Roman：``abc`` 换成 Times，
    汉字保留原来的字体。没有字形却硬换，MuPDF 保存时会静默换成别的字体，
    屏幕上的字形和落盘结果就对不上了。
    """
    target_key = normalize(key)
    target = font(target_key)
    result: list[tuple[str, str]] = []
    for text, current in runs:
        current_key = normalize(current)
        buffer: list[str] = []
        buffer_font = current_key
        for char in str(text):
            # 空白不参与字形判断：字体里都有空格，换过去不影响观感。
            use = target_key if char in "\n\r\t " or target.has_glyph(ord(char)) else current_key
            if buffer and buffer_font != use:
                result.append(("".join(buffer), buffer_font))
                buffer = []
            buffer_font = use
            buffer.append(char)
        if buffer:
            result.append(("".join(buffer), buffer_font))

    merged: list[tuple[str, str]] = []
    for text, family in result:
        if merged and merged[-1][1] == family:
            merged[-1] = (merged[-1][0] + text, family)
        else:
            merged.append((text, family))
    return merged
