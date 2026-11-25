"""文本框与荧光笔的落盘与读回。

这两样东西不画成 PDF 批注，而是画进**页面内容流**：打印、复制文字、任何阅读器
都按普通内容处理，不依赖各家对批注外观流的支持。

做法是「草稿页 + 整页嫁接」：

1. 建一份内存里的草稿文档，页面尺寸 = 目标页的 mediabox；
2. 荧光带用裸操作符 + ``/ExtGState <</BM /Multiply>>`` 画在最下面；
3. 文字用 ``TextWriter`` 画（一个 TextWriter 一种颜色，混排字体在同一条流里）；
4. ``scratch.subset_fonts()`` —— **只子集化我们自己的字体**，原文档的字体
   一个字节都不动；
5. ``page.show_pdf_page`` 把草稿页嫁接成目标页上的一个 Form XObject；
6. 在这条内容流的首行写标记，把这一页的对象 JSON 挂到 XObject 的 ``/SixCoin``。

标记是唯一的身份凭据：``garbage=4`` 会重编号对象，xref 存不住。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager

import pymupdf

from app.core import fonts, palette, textlayout
from app.models import HighlightObject, TextObject

MARK_PREFIX = b"% sixcoin-overlay v1 "
_META_KEY = "SixCoin"
_GS_NAME = "GSmul"
_PX_TO_PT = textlayout.PX_TO_PT
# 内容流里的 ``/名字 Do``：show_pdf_page 挂上去的 Form XObject 只能靠它认。
_NAME_DO = re.compile(rb"/([^\s/<>\[\](){}]+)\s+Do\b")


def _num(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _resources_owner(doc: pymupdf.Document, page: pymupdf.Page) -> tuple[int, str] | None:
    """页面实际使用的 ``/Resources`` 在哪：``(对象 xref, 键前缀)``。

    ``/Resources`` 不一定写在页面自己身上：可以是间接对象，也可以挂在父节点上由
    页面继承（生成器省体积的常见做法）。只读页面自己的键会在后两种结构上落空，
    于是认不出覆盖层 XObject 的名字——标记写不进去，下一次保存就当这页没有覆盖层。
    """
    xref = page.xref
    for _ in range(32):
        kind, value = doc.xref_get_key(xref, "Resources")
        if kind == "xref":
            return int(value.split()[0]), ""
        if kind == "dict":
            return xref, "Resources/"
        kind, value = doc.xref_get_key(xref, "Parent")
        if kind != "xref":
            return None
        xref = int(value.split()[0])
    return None


def _xobject_owner(doc: pymupdf.Document, page: pymupdf.Page) -> tuple[int, str] | None:
    """``/XObject`` 字典在哪：``(对象 xref, 键前缀)``。字典本身也可能是间接对象。"""
    owner = _resources_owner(doc, page)
    if owner is None:
        return None
    xref, prefix = owner
    kind, value = doc.xref_get_key(xref, f"{prefix}XObject")
    if kind == "xref":
        return int(value.split()[0]), ""
    if kind == "dict":
        return xref, f"{prefix}XObject/"
    return None


def _xobject_xref(doc: pymupdf.Document, page: pymupdf.Page, name: str) -> int | None:
    owner = _xobject_owner(doc, page)
    if owner is None:
        return None
    xref, prefix = owner
    kind, value = doc.xref_get_key(xref, f"{prefix}{name}")
    if kind != "xref" or not value:
        return None
    try:
        return int(value.split()[0])
    except (IndexError, ValueError):
        return None


def _add_multiply(doc: pymupdf.Document, page: pymupdf.Page) -> None:
    xref = doc.get_new_xref()
    doc.update_object(xref, "<< /Type /ExtGState /BM /Multiply /ca 1 /CA 1 >>")
    kind, value = doc.xref_get_key(page.xref, "Resources")
    if kind == "xref":
        doc.xref_set_key(int(value.split()[0]), f"ExtGState/{_GS_NAME}", f"{xref} 0 R")
    else:
        doc.xref_set_key(page.xref, f"Resources/ExtGState/{_GS_NAME}", f"{xref} 0 R")


def _own_streams(doc: pymupdf.Document, page: pymupdf.Page) -> list[tuple[int, str]]:
    """属于本项目的覆盖层内容流：``(xref, XObject 资源名)``。"""
    found: list[tuple[int, str]] = []
    for xref in page.get_contents():
        data = doc.xref_stream(xref) or b""
        if not data.startswith(MARK_PREFIX):
            continue
        head = data.split(b"\n", 1)[0]
        parts = head.split()
        name = parts[3].decode("ascii", "ignore") if len(parts) >= 4 else ""
        found.append((xref, name))
    return found


def _set_contents(doc: pymupdf.Document, page: pymupdf.Page, xrefs: list[int]) -> None:
    if xrefs:
        doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]")
    else:
        doc.xref_set_key(page.xref, "Contents", "null")


@contextmanager
def hidden(doc: pymupdf.Document, page: pymupdf.Page) -> Iterator[None]:
    """渲染背景时临时摘掉本项目的覆盖层。

    覆盖层是真正的页面内容，前端又会用 DOM 按模型再画一遍。如果背景图也把它
    画进去，文字就等于被「烘焙」在背景上：移动文本框时原位留下一个擦不掉的
    残影，重开文件还会看到两份叠在一起。

    只从 ``/Contents`` 里摘掉，不删 XObject 与字体：退出上下文立刻原样挂回去，
    保存、导出、读回都不受影响。
    """
    own = {xref for xref, _name in _own_streams(doc, page)}
    if not own:
        yield
        return
    contents = page.get_contents()
    _set_contents(doc, page, [xref for xref in contents if xref not in own])
    try:
        yield
    finally:
        _set_contents(doc, page, contents)


def take(doc: pymupdf.Document, page: pymupdf.Page) -> list[dict]:
    """撤掉上一版的覆盖层，返回它原来的内容（读不出来时返回空表）。

    返回值是兜底用的：新的一版万一画不上去，还能把旧的照原样画回来，而不是让
    这一页的文本框凭空消失。

    只删标记里点名的那一个 XObject——遍历删掉整个 XObject 字典会把页面上的
    图片（``fzImg0``）一起删掉，下一次保存就会报 ``cannot find XObject resource``。
    """
    own = _own_streams(doc, page)
    if not own:
        return []
    items = _items_from(doc, page, own)
    doomed = {xref for xref, _name in own}
    _set_contents(doc, page, [xref for xref in page.get_contents() if xref not in doomed])
    owner = _xobject_owner(doc, page)
    if owner is not None:
        xref, prefix = owner
        for _stream, name in own:
            if not name:
                continue
            try:
                # 删在真正持有它的字典里：页面的 /Resources 可能是继承来的，
                # 往页面自己身上写会造出一个空 Resources，把继承的图片和字体
                # 全挡在外面。
                doc.xref_set_key(xref, f"{prefix}{name}", "null")
            except Exception:
                # 资源键删不掉不影响页面：覆盖层流已经从 /Contents 摘掉了。
                pass
    return items


def read(doc: pymupdf.Document, page: pymupdf.Page) -> list[dict]:
    """读出这一页由本项目产生的对象（原始 JSON 列表）。"""
    return _items_from(doc, page, _own_streams(doc, page))


def _items_from(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    streams: list[tuple[int, str]],
) -> list[dict]:
    for _xref, name in streams:
        xobj = _xobject_xref(doc, page, name) if name else None
        if xobj is None:
            continue
        kind, value = doc.xref_get_key(xobj, _META_KEY)
        if kind != "xref" or not value:
            continue
        try:
            stream = int(value.split()[0])
            payload = json.loads((doc.xref_stream(stream) or b"").decode("utf-8"))
        except (ValueError, OSError):
            continue
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def objects_for_page(page: pymupdf.Page, items: list[dict]) -> list[TextObject | HighlightObject]:
    """把 JSON 还原成模型对象。位置一律按当前页的坐标系。"""
    result: list[TextObject | HighlightObject] = []
    index = page.number
    for item in items:
        kind = item.get("k")
        if kind == "text":
            result.append(TextObject.from_pdf_dict(item, index))
        elif kind == "hl":
            band = HighlightObject.from_pdf_dict(item, index)
            # 旧文件里可能存着绿/蓝/红荧光带；现在只认黄色，读进来就统一掉。
            band.color = palette.normalize_highlight(band.color)
            result.append(band)
    return result


def _text_ops(writer: pymupdf.TextWriter, obj: TextObject, lines) -> None:
    size_pt = obj.size_px * _PX_TO_PT
    for line in lines:
        for run in line.runs:
            writer.append(
                (obj.rect.x + run.x, obj.rect.y + line.baseline),
                run.text,
                font=fonts.font(run.font),
                fontsize=size_pt,
            )


def draw(
    doc: pymupdf.Document, page: pymupdf.Page, items: list[TextObject | HighlightObject]
) -> bool:
    """把这一页的文本框与荧光带画成一条新的覆盖层。"""
    if not items or page.rotation % 360 != 0:
        return False
    box = page.mediabox
    width, height = float(box.width), float(box.height)
    scratch = pymupdf.open()
    try:
        sheet = scratch.new_page(width=width, height=height)

        bands = [o for o in items if isinstance(o, HighlightObject) and o.rect.is_valid()]
        if bands:
            _add_multiply(scratch, sheet)
            ops = ["q", f"/{_GS_NAME} gs"]
            for band in sorted(bands, key=lambda o: o.z):
                rect = band.rect
                red, green, blue = palette.highlight_rgb(band.color)
                # 裸操作符是 PDF 原生的左下原点。
                ops.append(
                    f"{_num(red)} {_num(green)} {_num(blue)} rg "
                    f"{_num(rect.x)} {_num(height - rect.y - rect.h)} "
                    f"{_num(rect.w)} {_num(rect.h)} re f"
                )
            ops.append("Q\n")
            pymupdf.TOOLS._insert_contents(sheet, "\n".join(ops).encode("ascii"), overlay=1)

        by_color: dict[str, list[tuple[TextObject, list]]] = {}
        for obj in items:
            if not isinstance(obj, TextObject) or not obj.rect.is_valid():
                continue
            lines, _height = textlayout.layout(obj.runs, obj.rect.w, obj.size_px, obj.line_height)
            if not any(line.runs for line in lines):
                continue
            by_color.setdefault(obj.color, []).append((obj, lines))

        for color, entries in by_color.items():
            writer = pymupdf.TextWriter(sheet.rect)
            for obj, lines in entries:
                _text_ops(writer, obj, lines)
            writer.write_text(sheet, color=palette.text_rgb(color))

        scratch.subset_fonts()

        before_contents = page.get_contents()
        try:
            page.show_pdf_page(pymupdf.Rect(0, 0, width, height), scratch, 0)
        except Exception:
            _restore_contents(doc, page, before_contents)
            raise
        new_streams = [x for x in page.get_contents() if x not in before_contents]
        if not new_streams:
            return False
        # 名字以内容流里的 ``/xxx Do`` 为准：/Resources 可能是继承来的，
        # 在页面自己身上比对资源字典会漏掉刚挂上去的 XObject。
        name = _drawn_name(doc, new_streams[-1])
        xobj = _xobject_xref(doc, page, name) if name else None
        if xobj is None:
            # 认不出挂上去的是哪个 XObject：把这条流摘掉，别留半条覆盖层。
            _restore_contents(doc, page, before_contents)
            return False

        payload = {
            "v": 1,
            "items": [obj.to_pdf_dict() for obj in sorted(items, key=lambda o: o.z)],
        }
        meta = doc.get_new_xref()
        doc.update_object(meta, "<<>>")
        doc.update_stream(meta, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        doc.xref_set_key(xobj, _META_KEY, f"{meta} 0 R")

        stream = new_streams[-1]
        marker = MARK_PREFIX + name.encode("ascii") + b"\n"
        doc.update_stream(stream, marker + (doc.xref_stream(stream) or b""))
        return True
    finally:
        scratch.close()


def _drawn_name(doc: pymupdf.Document, stream_xref: int) -> str | None:
    data = doc.xref_stream(stream_xref) or b""
    found = _NAME_DO.findall(data)
    return found[-1].decode("ascii", "ignore") if found else None


def _restore_contents(doc: pymupdf.Document, page: pymupdf.Page, contents: list[int]) -> None:
    try:
        _set_contents(doc, page, contents)
    except Exception:
        # 回滚失败也只能继续往上抛原始错误，别把它盖掉。
        pass
