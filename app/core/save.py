"""保存。

逐页把原图 redaction 掉，再把画布上的图插回去。文字、矢量、注释、书签、链接
全部保留——保存只应该改变图片，其他内容一个字节都不该动。

落盘一律先写临时文件再 ``os.replace``，中途失败不会留下半个文件；就地保存时
往调用方给的备份目录里留一份 ``YYYYMMDD-原标题.bak.pdf``。

就地保存（``dst_path == src_path``）要求调用方先关掉自己持有的文档句柄：
Windows 上 ``os.replace`` 无法覆盖仍被打开的文件。``ui`` 层在调用前
``PdfDocument.close()``，保存后再重新打开。
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pymupdf

from app.core import overlay
from app.core.imagestore import ImageStore
from app.errors import SaveError
from app.models import DocumentState, HighlightObject, ImageObject, Rect, TextObject

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
    for obj in sorted(objects, key=lambda o: o.z):
        # 不夹回页面：单张图片允许被移到页外（拼版/裁切时很有用），
        # PDF 内容流可以画在页面矩形之外，阅读器按页裁掉即可。
        rect = obj.rect
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
                # 必须显式关掉：默认的 keep_proportion=True 会按图片原始比例
                # 把图居中塞进矩形，用户调过的长宽比在重新打开时就被抹掉了。
                # PyMuPDF 2.x 起这条对 JPEG 与 PNG 一致生效。
                keep_proportion=False,
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
    # 只动「模型里装载过」的页。没装载的页在模型里一个对象都没有：擦掉它的覆盖层
    # 之后没有任何东西能画回去，保存一次就少一页的文字。这是丢页的根因，别改成
    # 无条件遍历——``None`` 是调用方不跟踪装载状态，按全部装载处理。
    loaded = state.loaded if state.loaded is not None else set(range(doc.page_count))

    # 按页分好再进循环：几百个对象时，每页都扫一遍整张表会明显拖慢保存。
    images: dict[int, list[ImageObject]] = {}
    sources: dict[int, list[ImageObject]] = {}
    overlays: dict[int, list[TextObject | HighlightObject]] = {}
    for obj in state.objects:
        if isinstance(obj, ImageObject):
            images.setdefault(obj.page, []).append(obj)
            origin = obj.src_page if obj.src_page is not None else obj.page
            sources.setdefault(origin, []).append(obj)
        else:
            overlays.setdefault(obj.page, []).append(obj)

    for index in range(doc.page_count):
        if index not in loaded:
            continue
        page = doc[index]
        # 覆盖层必须在 redaction 之前撤掉：apply_redactions 会把整页内容流合并成
        # 一条，标记流混进去之后就再也认不出来了。
        previous = overlay.take(doc, page)
        targets = _redact_targets(sources.get(index, []), state.removed.get(index))
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
        _insert_objects(page, images.get(index, []), store, report, index)
        items = sorted(overlays.get(index, []), key=lambda o: o.z)
        try:
            drawn = overlay.draw(doc, page, items)
        except Exception as exc:
            # 文本/荧光笔画不上去不能把整次保存拖垮：图已经处理完了。
            report.warnings.append({"page": index, "code": "overlay_failed", "detail": str(exc)})
            drawn = False
        if items and not drawn:
            # 新的覆盖层没写进去，旧的又已经被撤掉了：把原来那版原样画回去，
            # 宁可这一页的编辑没更新，也不能让它整页文字凭空消失。
            restored = False
            if previous:
                try:
                    restored = overlay.draw(doc, page, overlay.objects_for_page(page, previous))
                except Exception:
                    restored = False
            report.warnings.append(
                {
                    "page": index,
                    "code": "overlay_kept" if restored else "overlay_lost",
                    "detail": f"{len(items)} items",
                }
            )


def save(
    src_path: Path,
    dst_path: Path,
    state: DocumentState,
    store: ImageStore,
    backup_dir: Path | None = None,
) -> SaveReport:
    """保存。``backup_dir`` 给了就地保存时先往那里复制一份原文件。"""
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
        if backup_dir is not None and dst_path.exists() and _same_path(dst_path, src_path):
            _backup(dst_path, Path(backup_dir), report)
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


def backup_path(directory: Path, source: Path, day: date | None = None, index: int = 0) -> Path:
    """备份名字：``YYYYMMDD-原标题.bak.pdf``，撞名时变成 ``…-in.bak1.pdf``。

    同一天保存第二次时不再「已经有了就不备份」——那样第二次保存前的那一版
    就永久丢了。改成往后排号，每次保存前的状态都留得下来；序号直接跟在 ``bak``
    后面，不加括号和空格，路径里少两个容易出问题的字符。
    """
    stamp = (day or date.today()).strftime("%Y%m%d")
    stem = Path(source).stem
    suffix = str(index) if index else ""
    return directory / f"{stamp}-{stem}.bak{suffix}.pdf"


def _backup(dst_path: Path, directory: Path, report: SaveReport) -> None:
    """把即将被覆盖的文件复制到备份目录。失败只记警告，不阻止保存。"""
    target: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        index = 0
        while True:
            target = backup_path(directory, dst_path, index=index)
            if not target.exists():
                break
            index += 1
            if index > 999:
                raise OSError(f"too many backups of {dst_path.name}")
        shutil.copy2(dst_path, target)
    except OSError as exc:
        # 复制到一半失败会留下一个看着像备份、其实是残片的东西，先收掉。
        if target is not None:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        # 备份失败不该阻止保存本身，但必须让用户知道这次没有备份——静默失败
        # 等于告诉用户「有备份」而实际上没有。
        report.warnings.append({"page": None, "code": "backup_failed", "detail": str(exc)})


def sweep_backups(directory: Path, retention_days: int) -> int:
    """删掉超过保留期的备份，返回删了几个。

    按修改时间判断，不看文件名里的日期：文件名说的是「备份的是哪一版」，修改
    时间才是「这份文件在这里放了多久」。删不掉的（正被别的程序打开）跳过，
    下次启动再试。
    """
    if retention_days <= 0:
        return 0
    root = Path(directory)
    if not root.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for entry in root.glob("*.pdf"):
        try:
            if not entry.is_file() or entry.stat().st_mtime >= cutoff:
                continue
            entry.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
