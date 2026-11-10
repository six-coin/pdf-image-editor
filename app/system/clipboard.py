"""从剪贴板取图。

用 ctypes 直接调 Win32，不引入 Pillow：
- 浏览器复制的图通常以 "PNG" / "JFIF" 格式放进去，直接透传；
- 截图工具放的是 CF_DIB / CF_DIBV5，手工解析成 RGB 采样交给 PyMuPDF 编码。

只支持 24/32 位、无压缩或位域的 DIB。其他格式返回 None，由上层提示"剪贴板里没有图像"。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import pymupdf
from loguru import logger

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = wintypes.HANDLE
_user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
_user32.RegisterClipboardFormatW.restype = wintypes.UINT

_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalSize.restype = ctypes.c_size_t

CF_DIB = 8
CF_DIBV5 = 17

_BI_RGB = 0
_BI_BITFIELDS = 3


def _format(name: str) -> int:
    return int(_user32.RegisterClipboardFormatW(name))


def _read(fmt: int) -> bytes | None:
    handle = _user32.GetClipboardData(fmt)
    if not handle:
        return None
    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        size = int(_kernel32.GlobalSize(handle))
        if size <= 0:
            return None
        return ctypes.string_at(pointer, size)
    finally:
        _kernel32.GlobalUnlock(handle)


def read_image() -> bytes | None:
    """返回 PNG 或 JPEG 字节；剪贴板里没有可用图像时返回 None。"""
    if not _user32.OpenClipboard(None):
        return None
    try:
        for name in ("PNG", "JFIF"):
            data = _read(_format(name))
            if data:
                return data
        for fmt in (CF_DIBV5, CF_DIB):
            data = _read(fmt)
            if not data:
                continue
            png = _dib_to_png(data)
            if png:
                return png
        return None
    finally:
        _user32.CloseClipboard()


def _dib_to_png(data: bytes) -> bytes | None:
    if len(data) < 40:
        return None

    header_size = int.from_bytes(data[0:4], "little")
    width = int.from_bytes(data[4:8], "little", signed=True)
    height = int.from_bytes(data[8:12], "little", signed=True)
    planes = int.from_bytes(data[12:14], "little")
    bits = int.from_bytes(data[14:16], "little")
    compression = int.from_bytes(data[16:20], "little")

    if planes != 1 or bits not in (24, 32) or compression not in (_BI_RGB, _BI_BITFIELDS):
        logger.warning("剪贴板位图不支持：{}bpp / compression {}", bits, compression)
        return None

    top_down = height < 0
    rows = abs(height)
    if width <= 0 or rows <= 0 or width > 20000 or rows > 20000:
        return None

    offset = header_size
    if compression == _BI_BITFIELDS:
        offset += 12  # 三个颜色掩码

    stride = ((width * bits + 31) // 32) * 4
    if len(data) < offset + stride * rows:
        return None

    pixel_bytes = bits // 8
    row_bytes = width * pixel_bytes
    buffer = bytearray(width * rows * 3)

    for y in range(rows):
        source_row = y if top_down else rows - 1 - y
        start = offset + source_row * stride
        row = data[start : start + row_bytes]
        # 扩展切片批量重排，比逐像素快两个数量级
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::3]
        rgb[1::3] = row[1::3]
        rgb[2::3] = row[0::3]
        target = y * width * 3
        buffer[target : target + width * 3] = rgb

    try:
        pix = pymupdf.Pixmap(pymupdf.csRGB, width, rows, bytes(buffer), False)
        return pix.tobytes("png")
    except Exception:
        logger.exception("剪贴板位图编码失败")
        return None
