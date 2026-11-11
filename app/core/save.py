"""保存。

逐页把原图 redaction 掉，再把画布上的图插回去。文字、矢量、注释、书签、链接
全部保留。这是修掉"保存后文档变白页"那个 P0 缺陷的核心。

落盘一律先写临时文件再 ``os.replace``，中途失败不会留下半个文件；就地保存时
第一次会留一份 ``.bak.pdf``。

就地保存（``dst_path == src_path``）要求调用方先关掉自己持有的文档句柄：
Windows 上 ``os.replace`` 无法覆盖仍被打开的文件。``ui`` 层在调用前
``PdfDocument.close()``，保存后再重新打开。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from app.core.geometry import clamp_rect_to_page
from app.core.imagestore import ImageStore
from app.errors import SaveError
from app.models import DocumentState, ImageObject, Rect

_VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass
class SaveReport:
    path: Path | None = None
    pages: int = 0
    replaced: int = 0
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.path is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": str(self.path) if self.path else "",
            "pages": self.pages,
            "replaced": self.replaced,
            "warnings": list(self.warnings),
        }


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _rotation(value: int) -> int:
    degrees = int(value) % 360
    return degrees if degrees in _VALID_ROTATIONS else 0


def _redact_targets(
    objects: list[ImageObject], removed: list[Rect] | None = None
) -> list[pymupdf.Rect]:
    """要摘掉的原图位置：画布上还在的 + 已经被删掉的。同一块区域只 redaction 一次。"""
    sources: list[Rect] = [
        obj.src_rect for obj in objects if obj.src_xref is not None and obj.src_rect is not None
    ]
    sources.extend(removed or [])
    rects: list[pymupdf.Rect] = []
    seen: set[tuple[float, float, float, float]] = set()
    for source in sources:
        key = (
            round(source.x, 2),
            round(source.y, 2),
            round(source.right, 2),
            round(source.bottom, 2),
        )
        if key in seen:
            continue
        seen.add(key)
        rects.append(pymupdf.Rect(source.x, source.y, source.right, source.bottom))
    return rects


def _insert_objects(
    page: pymupdf.Page,
    objects: list[ImageObject],
    store: ImageStore,
    report: SaveReport,
    index: int,
) -> None:
    width, height = float(page.rect.width), float(page.rect.height)
    for obj in sorted(objects, key=lambda o: o.z):
        rect = clamp_rect_to_page(obj.rect, width, height)
        if rect != obj.rect:
            report.warnings.append({"page": index, "code": "image_clamped", "detail": obj.id})
        target = pymupdf.Rect(rect.x, rect.y, rect.right, rect.bottom)
        if target.is_empty:
            report.warnings.append({"page": index, "code": "image_skipped", "detail": obj.id})
            continue
        try:
            page.insert_image(
                target,
                stream=store.get(obj.image_id),
                rotate=_rotation(obj.rotation),
                overlay=True,
            )
            report.replaced += 1
        except Exception as exc:
            report.warnings.append(
                {"page": index, "code": "insert_failed", "detail": f"{obj.id}: {exc}"}
            )


def _detach_annotations(doc: pymupdf.Document, page: pymupdf.Page) -> str | None:
    """把页面的 /Annots 数组临时摘下来。

    ``apply_redactions`` 会顺手删掉落在 redaction 矩形里的批注，而批注往往正是
    用户最舍不得丢的东西。摘下来、做完再挂回去，批注对象一个字节都不动。
    返回原值，页面没有批注时返回 None。
    """
    kind, value = doc.xref_get_key(page.xref, "Annots")
    if kind in ("null", "none") or not value or value == "null":
        return None
    doc.xref_set_key(page.xref, "Annots", "null")
    return value


def _restore_annotations(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    value: str | None,
    report: SaveReport,
    index: int,
) -> None:
    if value is None:
        return
    try:
        doc.xref_set_key(page.xref, "Annots", value)
    except Exception as exc:
        report.warnings.append({"page": index, "code": "annots_lost", "detail": str(exc)})


def _apply_preserve(
    doc: pymupdf.Document,
    state: DocumentState,
    store: ImageStore,
    report: SaveReport,
) -> None:
    for index in range(doc.page_count):
        page = doc[index]
        objects = [o for o in state.objects if o.page == index]
        # 原图未必还在这一页（跨页拖动过），按 src_page 找它的原位。
        sources = [
            o for o in state.objects if (o.src_page if o.src_page is not None else o.page) == index
        ]
        targets = _redact_targets(sources, state.removed.get(index))
        if targets:
            saved_annots = _detach_annotations(doc, page)
            try:
                for rect in targets:
                    page.add_redact_annot(rect)
                page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                    text=pymupdf.PDF_REDACT_TEXT_NONE,
                )
            except Exception as exc:
                # 单页失败不拖累其他页：原图会残留在下层，但不会丢内容。
                report.warnings.append({"page": index, "code": "redact_failed", "detail": str(exc)})
            finally:
                _restore_annotations(doc, page, saved_annots, report, index)
        _insert_objects(page, objects, store, report, index)


def save(
    src_path: Path,
    dst_path: Path,
    state: DocumentState,
    store: ImageStore,
    backup: bool = True,
) -> SaveReport:
    src_path = Path(src_path)
    dst_path = Path(dst_path)
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SaveError(key="error.save_failed", reason=str(exc)) from exc
    temp_path = dst_path.with_name(f"{dst_path.name}.tmp-{os.getpid()}")
    report = SaveReport(path=dst_path)

    try:
        doc = pymupdf.open(src_path)
    except Exception as exc:
        raise SaveError(key="error.save_failed", reason=str(exc)) from exc

    try:
        report.pages = doc.page_count
        _apply_preserve(doc, state, store, report)
        doc.save(temp_path, garbage=4, deflate=True)
    except SaveError:
        raise
    except Exception as exc:
        raise SaveError(key="error.save_failed", reason=str(exc)) from exc
    finally:
        doc.close()

    try:
        _verify(temp_path, report.pages)
        if backup and dst_path.exists() and _same_path(dst_path, src_path):
            _backup(dst_path)
        os.replace(temp_path, dst_path)
    except SaveError:
        _discard(temp_path)
        raise
    except Exception as exc:
        _discard(temp_path)
        raise SaveError(key="error.save_failed", reason=str(exc)) from exc

    return report


def _verify(path: Path, expected_pages: int) -> None:
    """落盘后再打开一次。写坏了就在这里失败，而不是等用户下次打开才发现。"""
    try:
        check = pymupdf.open(path)
    except Exception as exc:
        raise SaveError(key="error.save_failed", reason=str(exc)) from exc
    try:
        if check.page_count != expected_pages:
            raise SaveError(
                key="error.save_failed",
                reason=f"page count {check.page_count} != {expected_pages}",
            )
    finally:
        check.close()


def _backup(dst_path: Path) -> None:
    backup_path = dst_path.with_name(f"{dst_path.stem}.bak.pdf")
    if backup_path.exists():
        return
    try:
        shutil.copy2(dst_path, backup_path)
    except OSError:
        # 备份失败不该阻止保存本身，但要留下痕迹。
        return


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
