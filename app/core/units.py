"""单位换算与页码范围解析。

只做数值与字符串处理，不认识 PDF 也不认识界面。
"""

from __future__ import annotations

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
MM_TO_PT = PT_PER_INCH / MM_PER_INCH


def mm_to_pt(mm: float) -> float:
    return mm * MM_TO_PT


def pt_to_mm(pt: float) -> float:
    return pt / MM_TO_PT


def parse_page_range(text: str, max_pages: int) -> tuple[list[int], list[tuple[str, str]]]:
    """把 "1-3,5,7-9" 解析成 0 基页号。

    返回 ``(pages, errors)``；``errors`` 里每项是 ``(错误码, 原始片段)``，
    错误码取 ``reversed`` / ``out_of_range`` / ``bad_token``。解析不抛异常，
    由调用方决定怎么提示——静默返回空列表是最糟的做法。
    """
    pages: set[int] = set()
    errors: list[tuple[str, str]] = []
    if max_pages <= 0:
        return [], errors

    for raw in text.replace(" ", "").replace("，", ",").split(","):
        token = raw.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                errors.append(("bad_token", token))
                continue
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                errors.append(("bad_token", token))
                continue
            if start > end:
                errors.append(("reversed", token))
                continue
            if start < 1 or end > max_pages:
                errors.append(("out_of_range", token))
                continue
            pages.update(range(start - 1, end))
        else:
            try:
                page = int(token)
            except ValueError:
                errors.append(("bad_token", token))
                continue
            if page < 1 or page > max_pages:
                errors.append(("out_of_range", token))
                continue
            pages.add(page - 1)

    return sorted(pages), errors
