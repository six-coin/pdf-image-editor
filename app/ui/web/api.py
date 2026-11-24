"""js_api 对象。

前端只能通过这里的方法碰后端。约定：
- 越界或非法参数不抛异常，原样返回当前快照（网页拿到 traceback 最难排查）。
- 所有对文档状态的读写都在同一把锁里；pywebview 给每次调用单起一个线程。
- 长任务返回 task id，前端轮询 ``poll_task``。
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import RLock
from typing import Any

import pymupdf
import webview
from loguru import logger

from app import i18n, paths, settings
from app import version as version_module
from app.core import fonts as font_table
from app.core import palette, tablelines, textlayout
from app.core import split as split_ops
from app.core.document import PdfDocument
from app.core.geometry import MIN_SIZE, clamp_rect_to_page
from app.core.imagestore import ImageStore
from app.core.render import RenderCache
from app.core.save import save as save_to_disk
from app.core.save import sweep_backups
from app.core.undo import ImageReplaced, ObjectsChanged, StructureChanged, UndoStack
from app.core.units import parse_page_range
from app.errors import AppError
from app.models import (
    DocumentState,
    HighlightObject,
    ImageObject,
    PageInfo,
    Rect,
    TextObject,
    TextRun,
)
from app.system import clipboard, opener, preprocess
from app.system import theme as theme_tool
from app.system.asset_server import AssetServer

PREVIEW_PX = 320
CANVAS_PX = 1600
_TASK_HISTORY = 20
# 文本框最窄能拖到多少。再窄就只剩一条线，字全被挤到下一行。
MIN_TEXT_WIDTH = 24.0
MM_TO_PT = 72.0 / 25.4
PX_TO_PT = 72.0 / 96.0


class EditorApi:
    def __init__(self) -> None:
        self._lock = RLock()
        self._store = ImageStore()
        self._doc: PdfDocument | None = None
        self._state = DocumentState()
        self._cache: RenderCache | None = None
        self._stack: UndoStack | None = None
        self._loaded_pages: set[int] = set()
        self._generation = 0
        self._rev = 0
        self._tasks: dict[str, dict[str, Any]] = {}
        self._task_seq = 0
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdfedit")
        self._server: AssetServer | None = None
        self._window: webview.Window | None = None
        # 必须在 load_app() 之前判断：它会把默认配置写到磁盘。
        self.first_run = not paths.APP_CONFIG_PATH.exists()
        self._settings = settings.load_app()
        # 日志文件在读到设置之前就开了（默认级别），这里补上用户选的那一份。
        settings.apply_log_settings(self._settings)
        self._reference = settings.load_reference()
        self._align = settings.load_align()
        _sweep_temp()
        _sweep_backups(paths.backup_dir(), int(self._settings.get("backup_retention_days", 30)))
        self._close_confirmed = False
        self._restart_requested = False

    # ---- 装配 ----

    def attach_server(self, server: AssetServer) -> None:
        self._server = server

    def attach_window(self, window: webview.Window) -> None:
        self._window = window

    def _retitle(self) -> None:
        """窗口标题跟着界面语言走。

        老版本 pywebview 没有 ``set_title``，改标题失败也绝不能影响语言切换
        本身，所以这里兜住一切异常。
        """
        if self._window is None:
            return
        try:
            self._window.set_title(i18n.t("app.title"))
        except Exception as error:
            logger.debug("修改窗口标题失败: {}", error)

    @property
    def settings_snapshot(self) -> dict[str, Any]:
        return dict(self._settings)

    @property
    def store(self) -> ImageStore:
        return self._store

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            if self._doc is not None:
                self._doc.close()
                self._doc = None

    # ---- 读取 ----

    def get_strings(self) -> dict[str, str]:
        return i18n.strings()

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot()

    def poll_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._tasks.get(str(task_id))
            return dict(task) if task else {"state": "unknown"}

    # ---- 文档 ----

    def browse_pdf(self) -> str | None:
        if self._window is None:
            return None
        try:
            directory = str(paths.ensure_pdfs_dir())
        except OSError:
            directory = ""
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=directory,
            file_types=(i18n.t("dialog.filter_pdf"), i18n.t("dialog.filter_all")),
        )
        return _first_path(result)

    def browse_folder(self) -> str | None:
        """选目录：改数据目录用。"""
        if self._window is None:
            return None
        try:
            result = self._window.create_file_dialog(
                webview.FileDialog.FOLDER, directory=str(paths.DATA_DIR)
            )
        except Exception as error:  # 对话框打不开时返回空，由界面提示
            logger.warning("打开目录对话框失败: {}", error)
            return None
        return _first_path(result)

    def open_path(self, path: str, force: bool = False) -> dict[str, Any]:
        if not path:
            return {"ok": False, "reason": "invalid", "message": i18n.t("error.pdf_open", name="")}
        if paths.is_backup_path(path):
            return {
                "ok": False,
                "reason": "backup",
                "message": i18n.t("error.backup_open", name=Path(path).name),
            }
        with self._lock:
            if self._stack is not None and self._stack.dirty and not force:
                return {
                    "ok": False,
                    "reason": "dirty",
                    "message": i18n.t("dialog.unsaved_text"),
                }
            self._generation += 1
            generation = self._generation
            task_id = self._new_task("open")
        self._executor.submit(self._open_worker, Path(path), generation, task_id)
        return {"ok": True, "task": task_id}

    def _open_worker(self, path: Path, generation: int, task_id: str) -> None:
        try:
            doc = PdfDocument.open(path, self._store)
            pages: list[PageInfo] = []
            for index in range(doc.page_count):
                width, height = doc.page_pt_size(index)
                pages.append(PageInfo(index=index, width=width, height=height))
        except AppError as exc:
            logger.warning("打开失败 {}: {}", path, exc)
            self._finish_task(task_id, "error", str(exc))
            return
        except Exception:
            logger.exception("打开失败 {}", path)
            self._finish_task(task_id, "error", i18n.t("error.unexpected"))
            return

        with self._lock:
            if generation != self._generation:
                doc.close()
                self._finish_task(task_id, "ready")
                return
            if self._doc is not None:
                self._doc.close()
            self._doc = doc
            self._cache = self._new_cache(doc)
            self._state = DocumentState(path=doc.path, pages=pages)
            self._stack = UndoStack(self._state, limit=int(self._settings["undo_limit"]))
            self._loaded_pages.clear()
            self._finish_task(task_id, "ready")
        logger.info("已打开 {} 共 {} 页", path, len(pages))

    def offer_drop(self, path: str) -> None:
        """把拖进窗口的文件交给页面。

        打开动作必须走页面那条路：那里才有「上一个文件还没保存」的三选一询问。
        后端只管把完整路径送过去——WebView2 只把真实路径交给宿主，页面自己拿不到。
        """
        if self._window is None or not path:
            return
        literal = json.dumps(str(path))
        try:
            self._window.evaluate_js(
                f"window.host && window.host.dropPath ? void window.host.dropPath({literal}) : null"
            )
        except Exception:
            logger.exception("把拖入的文件交给页面失败 {}", path)

    # ---- 渲染 ----

    def load_page(self, index: int, dpi: int = 150) -> dict[str, Any]:
        with self._lock:
            doc = self._doc
            if doc is None:
                return {"ok": False, "message": i18n.t("error.no_document")}
            try:
                page_index = int(index)
                page_dpi = int(dpi)
            except (TypeError, ValueError):
                return {"ok": False, "message": i18n.t("error.invalid_argument", name="page")}
            if not 0 <= page_index < doc.page_count:
                return {
                    "ok": False,
                    "message": i18n.t("error.pdf_page_out_of_range", page=page_index + 1),
                }

            info = doc.page_info(page_index)
            if 0 <= page_index < len(self._state.pages):
                self._state.pages[page_index] = info

            # 每页的图片只抽一次：重复抽会把用户已经删掉、切掉的原图重新塞回模型，
            # 表现就是"保留一格之后大图又回来了"。已装载的页记在 _loaded_pages 里。
            if page_index not in self._loaded_pages:
                for obj in doc.editable_images(page_index):
                    self._state.objects.append(obj)
                for obj in doc.overlay_objects(page_index):
                    self._state.objects.append(obj)
                self._loaded_pages.add(page_index)

            if self._cache is not None:
                self._cache.page_png(page_index, page_dpi)

            url = (
                self._server.page_url(page_index, page_dpi, self._generation)
                if self._server
                else ""
            )
            return {"ok": True, "url": url, "w": info.width, "h": info.height}

    def render_page(self, index: int, dpi: int = 150) -> bytes:
        """给资源服务用。不加装饰器：它必须抛异常，让服务返回 500。"""
        with self._lock:
            if self._cache is None:
                raise AppError(key="error.no_document")
            return self._cache.page_png(int(index), int(dpi))

    # ---- 选择与编辑 ----

    def select(self, ids: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._doc is None:
                return self._snapshot()
            self._state.selection = self._selection_on_one_page(ids or [])
            return self._snapshot()

    def commit_transform(
        self,
        items: list[dict[str, Any]] | None = None,
        selection: list[str] | None = None,
    ) -> dict[str, Any]:
        """提交一次拖动或缩放。越界在这里夹取，前端算错了也不会把图存到页外。

        ``selection`` 一起提交，拖谁就选谁，省掉一次额外往返。
        """
        with self._lock:
            doc = self._doc
            stack = self._stack
            if doc is None or stack is None:
                return self._snapshot()

            # 目标页可能还没装载过。先把它的原图抽进模型，否则模型里只有刚拖过去
            # 的那张、文件里却有两张：保存后重定基线对不上，页面装载时还会重复抽图。
            self._ensure_pages(items, doc)

            before: list[ImageObject] = []
            after: list[ImageObject] = []
            for raw in items or []:
                if not isinstance(raw, dict):
                    continue
                obj = self._state.find(str(raw.get("id", "")))
                if obj is None:
                    continue
                try:
                    x = float(raw["x"])
                    y = float(raw["y"])
                    w = float(raw["w"])
                    h = float(raw["h"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not all(math.isfinite(value) for value in (x, y, w, h)):
                    continue

                page = obj.page
                try:
                    requested = int(raw.get("page", page))
                except (TypeError, ValueError):
                    requested = page
                if 0 <= requested < doc.page_count:
                    page = requested

                page_w, page_h = doc.page_pt_size(page)
                updated = obj.clone()
                updated.page = page
                if isinstance(updated, TextObject):
                    # 文本框只认宽度：高度永远由排版算，前端拖不出「拉高」。
                    rect = self._text_rect(updated, x, y, w, page_w, page_h)
                elif isinstance(updated, HighlightObject):
                    # 荧光带只能挪位置，宽高保持模型里的值。
                    rect = clamp_rect_to_page(
                        Rect(x, y, updated.rect.w, updated.rect.h), page_w, page_h
                    )
                else:
                    rect = clamp_rect_to_page(Rect(x, y, w, h), page_w, page_h)
                    if rect.w < MIN_SIZE or rect.h < MIN_SIZE:
                        continue
                updated.rect = rect
                if updated.page == obj.page and updated.rect == obj.rect:
                    # 没有实际变化（比如宽图竖着拖，长边没动）：别塞一条空撤销记录。
                    continue
                before.append(obj.clone())
                after.append(updated)

            if after:
                stack.push(ObjectsChanged(before, after, "edit.move"))
            if selection is not None:
                self._state.selection = self._selection_on_one_page(selection)
            return self._snapshot()

    def _selection_on_one_page(self, ids: list[Any]) -> list[str]:
        """只保留落在同一页的选择。

        多选后要画一个组框、按组缩放，跨页的对象没有共同的坐标系；所以以第一个
        有效 id 所在的页为准，其余页的对象直接丢掉。前端也会拦，这里是兜底。
        """
        page_by_id = {obj.id: obj.page for obj in self._state.objects}
        chosen: list[str] = []
        page: int | None = None
        for raw in ids:
            object_id = str(raw)
            target = page_by_id.get(object_id)
            if target is None:
                continue
            if page is None:
                page = target
            elif target != page:
                continue
            chosen.append(object_id)
        return chosen

    def _ensure_pages(self, items: list[dict[str, Any]] | None, doc: PdfDocument) -> None:
        """把这次操作涉及、但还没装载过的页的原图先抽进模型。

        不抽的话，拖过去的那张会成为该页唯一被模型知晓的图；保存时文件里
        却还有这一页原有的图，模型和文件对不上，只能整体重建。
        """
        wanted: set[int] = set()
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            try:
                page = int(raw.get("page", -1))
            except (TypeError, ValueError):
                continue
            if 0 <= page < doc.page_count:
                wanted.add(page)

        for index in sorted(wanted - self._loaded_pages):
            for obj in doc.editable_images(index):
                self._state.objects.append(obj)
            for obj in doc.overlay_objects(index):
                self._state.objects.append(obj)
            self._loaded_pages.add(index)

    def delete_objects(self, ids: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            stack = self._stack
            if stack is None:
                return self._snapshot()
            doomed = {str(item) for item in (ids or [])}
            targets = [obj for obj in self._state.objects if obj.id in doomed]
            if not targets:
                return self._snapshot()

            before = self._state.clone_objects()
            for obj in targets:
                if not isinstance(obj, ImageObject):
                    continue
                # 对象没了，但它在原文件里还占着位置，保存时仍要 redaction。
                origin = obj.src_page if obj.src_page is not None else obj.page
                self._state.mark_removed(origin, obj.src_rect)
            self._state.drop([obj.id for obj in targets])
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.delete"))
            return self._snapshot()

    def reorder_objects(self, ids: list[str] | None = None, mode: str = "front") -> dict[str, Any]:
        with self._lock:
            stack = self._stack
            if stack is None:
                return self._snapshot()
            wanted = {str(item) for item in (ids or [])}
            targets = [obj for obj in self._state.objects if obj.id in wanted]
            if not targets:
                return self._snapshot()

            page = targets[0].page
            before = self._state.clone_objects()
            same_page = [obj for obj in self._state.objects if obj.page == page]
            chosen = [obj for obj in same_page if obj.id in wanted]
            rest = [obj for obj in same_page if obj.id not in wanted]
            ordered = rest + chosen if mode == "front" else chosen + rest
            for offset, obj in enumerate(ordered):
                obj.z = 10 + offset
            stack.push(ObjectsChanged(before, self._state.clone_objects(), "edit.reorder"))
            return self._snapshot()

    def undo(self) -> dict[str, Any]:
        with self._lock:
            if self._stack is not None:
                self._stack.undo()
            return self._snapshot()

    def redo(self) -> dict[str, Any]:
        with self._lock:
            if self._stack is not None:
                self._stack.redo()
            return self._snapshot()

    # ---- 切分与打孔 ----

    def split_object(
        self, object_id: str, cuts_x: list[float] | None = None, cuts_y: list[float] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if self._stack is None:
                return self._snapshot()
            if not isinstance(self._state.find(str(object_id)), ImageObject):
                return self._snapshot()
            pieces = split_ops.build_split(
                self._state.objects, str(object_id), _floats(cuts_x), _floats(cuts_y), self._store
            )
            return self._swap_pieces(str(object_id), pieces, "edit.split")

    def keep_cell(
        self,
        object_id: str,
        cuts_x: list[float] | None = None,
        cuts_y: list[float] | None = None,
        row: int = 0,
        col: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            if self._stack is None:
                return self._snapshot()
            if not isinstance(self._state.find(str(object_id)), ImageObject):
                return self._snapshot()
            pieces = split_ops.keep_cell(
                self._state.objects,
                str(object_id),
                _floats(cuts_x),
                _floats(cuts_y),
                int(row),
                int(col),
                self._store,
            )
            return self._swap_pieces(str(object_id), pieces, "edit.keep")

    def punch_cell(
        self,
        object_id: str,
        cuts_x: list[float] | None = None,
        cuts_y: list[float] | None = None,
        row: int = 0,
        col: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            stack = self._stack
            if stack is None:
                return self._snapshot()
            if not isinstance(self._state.find(str(object_id)), ImageObject):
                return self._snapshot()
            result = split_ops.punch_cell(
                self._state.objects,
                str(object_id),
                _floats(cuts_x),
                _floats(cuts_y),
                int(row),
                int(col),
                self._store,
            )
            original = self._state.find(str(object_id))
            if result is None or original is None:
                return self._snapshot()

            hole_image, piece = result
            before = self._state.clone_objects()
            original.image_id = hole_image
            self._state.objects.append(piece)
            self._state.renormalize(original.page)
            self._state.selection = [piece.id]
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.punch"))
            return self._snapshot()

    # ---- 文本框与荧光笔 ----

    def create_text(
        self,
        page: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        style: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在落点新建一个文本框。样式由前端给（「当前默认值」只活在前端）。"""
        with self._lock:
            doc = self._doc
            stack = self._stack
            if doc is None or stack is None:
                return self._snapshot()
            index = _page_index(page, doc.page_count)
            if doc.page(index).rotation % 360 != 0:
                # 旋转页的坐标系与画布对不上，和「旋转页的图片不可编辑」同一个理由。
                return self._snapshot()
            page_w, page_h = doc.page_pt_size(index)
            style = style if isinstance(style, dict) else {}

            font_key = font_table.normalize(style.get("font", self._settings["text_font"]))
            size_px = _int_between(style.get("size"), self._settings["text_size_px"], 6, 200)
            color = palette.normalize_text(style.get("color", self._settings["text_color"]))
            line_height = _float_between(
                style.get("line_height"), self._settings["text_line_height"], 0.8, 3.0
            )
            width = _float_between(
                style.get("width"),
                float(self._settings["text_width_mm"]) * MM_TO_PT,
                MIN_TEXT_WIDTH,
                max(page_w, MIN_TEXT_WIDTH),
            )
            left = min(max(_float_of(x), 0.0), max(page_w - width, 0.0))
            top = min(max(_float_of(y), 0.0), page_h)

            obj = TextObject(
                id=f"t-{uuid.uuid4().hex[:8]}",
                page=index,
                rect=Rect(left, top, width, 0.0),
                runs=[TextRun("", font_key)],
                size_px=size_px,
                line_height=line_height,
                color=color,
                z=self._state.next_z(index),
            )
            obj.rect = self._reflow(obj)

            before = self._state.clone_objects()
            self._state.objects.append(obj)
            self._state.selection = [obj.id]
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.text"))
            # 告诉前端「建的是哪一个」：旋转页之类被拒的情况下没有这个键，
            # 前端据此判断该不该进编辑态。
            return {**self._snapshot(), "created": obj.id}

    def update_text(
        self,
        object_id: str,
        runs: list[Any] | None = None,
        style: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """改内容或样式。内容被清空就等于删掉这个文本框。"""
        with self._lock:
            stack = self._stack
            obj = self._state.find(str(object_id))
            if stack is None or not isinstance(obj, TextObject):
                return self._snapshot()

            before = self._state.clone_objects()
            if runs is not None:
                parsed = [TextRun.from_any(item) for item in runs]
                parsed = [run for run in parsed if run.text]
                if not parsed or not "".join(run.text for run in parsed).strip():
                    self._state.drop([obj.id])
                    stack.push(StructureChanged(before, self._state.clone_objects(), "edit.text"))
                    return self._snapshot()
                obj.runs = [TextRun(run.text, font_table.normalize(run.font)) for run in parsed]
            if isinstance(style, dict):
                if "size" in style:
                    obj.size_px = _int_between(style.get("size"), obj.size_px, 6, 200)
                if "color" in style:
                    obj.color = palette.normalize_text(style.get("color"))
                if "line_height" in style:
                    obj.line_height = _float_between(
                        style.get("line_height"), obj.line_height, 0.8, 3.0
                    )
            obj.rect = self._reflow(obj)
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.text"))
            return self._snapshot()

    def create_highlight(
        self,
        page: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        w: float = 0.0,
        color: str | None = None,
        height_px: int | None = None,
    ) -> dict[str, Any]:
        """横着拉一条荧光带。高度取设置里的默认值，宽由拖拽决定。"""
        with self._lock:
            doc = self._doc
            stack = self._stack
            if doc is None or stack is None:
                return self._snapshot()
            index = _page_index(page, doc.page_count)
            if doc.page(index).rotation % 360 != 0:
                return self._snapshot()
            page_w, page_h = doc.page_pt_size(index)

            height = (
                _int_between(height_px, self._settings["highlight_height_px"], 4, 200) * PX_TO_PT
            )
            width = max(_float_of(w), 4.0)
            left = min(max(_float_of(x), 0.0), max(page_w - width, 0.0))
            top = min(max(_float_of(y), 0.0), max(page_h - height, 0.0))

            obj = HighlightObject(
                id=f"h-{uuid.uuid4().hex[:8]}",
                page=index,
                rect=Rect(left, top, width, height),
                color=palette.normalize_highlight(
                    color if color is not None else self._settings["highlight_color"]
                ),
                z=self._state.next_z(index),
            )
            before = self._state.clone_objects()
            self._state.objects.append(obj)
            self._state.selection = [obj.id]
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.highlight"))
            return {**self._snapshot(), "created": obj.id}

    def update_highlight(self, object_id: str, color: str | None = None) -> dict[str, Any]:
        with self._lock:
            stack = self._stack
            obj = self._state.find(str(object_id))
            if stack is None or not isinstance(obj, HighlightObject):
                return self._snapshot()
            before = self._state.clone_objects()
            obj.color = palette.normalize_highlight(color)
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.highlight"))
            return self._snapshot()

    def fill_cell(
        self,
        object_id: str,
        cuts_x: list[float] | None = None,
        cuts_y: list[float] | None = None,
        row: int = 0,
        col: int = 0,
    ) -> dict[str, Any]:
        """把选中的格子涂白：不产出小块，只删掉这一格的内容。"""
        with self._lock:
            stack = self._stack
            if stack is None:
                return self._snapshot()
            original = self._state.find(str(object_id))
            if not isinstance(original, ImageObject):
                return self._snapshot()
            image_id = split_ops.fill_cell(
                self._state.objects,
                str(object_id),
                _floats(cuts_x),
                _floats(cuts_y),
                int(row),
                int(col),
                self._store,
            )
            if image_id is None:
                return self._snapshot()
            before = self._state.clone_objects()
            original.image_id = image_id
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.fill"))
            return self._snapshot()

    def _reflow(self, obj: TextObject) -> Rect:
        """按当前内容重算文本框高度。宽度是用户定的，高度永远是算出来的。"""
        _lines, height = textlayout.layout(obj.runs, obj.rect.w, obj.size_px, obj.line_height)
        return Rect(obj.rect.x, obj.rect.y, obj.rect.w, max(float(height), 1.0))

    def _text_rect(
        self, obj: TextObject, x: float, y: float, width: float, page_w: float, page_h: float
    ) -> Rect:
        """文本框只接受位置与宽度：高度一律按内容重算。"""
        limit = max(page_w, MIN_TEXT_WIDTH)
        new_width = min(max(float(width), MIN_TEXT_WIDTH), limit)
        left = min(max(float(x), 0.0), max(page_w - new_width, 0.0))
        top = min(max(float(y), 0.0), page_h)
        obj.rect = Rect(left, top, new_width, obj.rect.h)
        return self._reflow(obj)

    def _swap_pieces(
        self, object_id: str, pieces: list[ImageObject] | None, label: str
    ) -> dict[str, Any]:
        stack = self._stack
        if pieces is None or stack is None:
            return self._snapshot()
        original = self._state.find(object_id)
        if original is None:
            return self._snapshot()

        before = self._state.clone_objects()
        self._state.objects = [obj for obj in self._state.objects if obj.id != object_id]
        self._state.objects.extend(pieces)
        self._state.renormalize(original.page)
        self._state.selection = [obj.id for obj in pieces]
        stack.push(StructureChanged(before, self._state.clone_objects(), label))
        return self._snapshot()

    # ---- 保存 ----

    def save_document(self, path: str | None = None) -> dict[str, Any]:
        """保存。给了 path 就是另存为，保存后以目标文件为新基线。"""
        with self._lock:
            doc = self._doc
            if doc is None:
                return {"ok": False, "message": i18n.t("error.no_document")}
            source = doc.path
            target = Path(path) if path else source
            state = self._state
            store = self._store
            # 只读文件原地保存会撞 WinError 5，提前拦下来给一句人话。
            if target.exists() and not os.access(target, os.W_OK):
                return {"ok": False, "message": i18n.t("error.file_readonly", name=target.name)}
            # Windows 上 os.replace 覆盖不了仍被打开的文件，先放掉句柄。
            doc.close()
            self._doc = None

        try:
            report = save_to_disk(source, target, state, store, backup_dir=paths.backup_dir())
        except AppError as exc:
            logger.warning("保存失败 {}: {}", target, exc)
            with self._lock:
                # 文件没动过，编辑也还在：只把句柄接回去，不重建状态。
                self._restore_handle(source)
            return {"ok": False, "message": str(exc)}
        except Exception:
            logger.exception("保存失败 {}", target)
            with self._lock:
                self._restore_handle(source)
            return {"ok": False, "message": i18n.t("error.unexpected")}

        with self._lock:
            # 把新文件当作基线，但对象、撤销栈、页面 DOM 都不重建——保存完界面不该闪一下。
            # 对不上（张数不一致）就退回完整重建。
            if self._rebase_after_save(target):
                self._state.path = target
                # 栈留着，只是把"已保存"的位置挪到当前：还能继续撤销。
                if self._stack is not None:
                    self._stack.mark_saved()
            else:
                self._generation += 1
                try:
                    self._reset_to_file(target)
                except Exception:
                    # 文件已经写好了，只是界面没能跟上；这不能报成「保存失败」。
                    logger.exception("保存后重新打开失败 {}", target)
                    report.warnings.append(
                        {"page": None, "code": "reopen_failed", "detail": str(target)}
                    )
        logger.info("已保存 {}，替换 {} 张图", target, report.replaced)
        return {"ok": True, **report.to_dict(), "generation": self._generation}

    def _new_cache(self, doc: PdfDocument) -> RenderCache:
        """按配置里的渲染上限建缓存。改小上限只影响之后新渲染的页。"""
        return RenderCache(doc, max_dpi=int(self._settings.get("render_dpi_cap", 300)))

    def _restore_handle(self, path: Path) -> None:
        """保存失败后把文档句柄接回来，内存里的编辑原样保留。"""
        try:
            doc = PdfDocument.open(path, self._store)
        except AppError:
            logger.exception("保存失败后无法重新打开 {}", path)
            self._doc = None
            self._cache = None
            return
        self._doc = doc
        self._cache = self._new_cache(doc)

    def _reset_to_file(self, path: Path) -> None:
        """保存成功后以文件为新基线：对象与撤销栈全部重建，src_rect 刷新到新位置。"""
        doc = PdfDocument.open(path, self._store)
        self._doc = doc
        self._cache = self._new_cache(doc)
        state = DocumentState(path=doc.path)
        for index in range(doc.page_count):
            width, height = doc.page_pt_size(index)
            state.pages.append(PageInfo(index=index, width=width, height=height))
        self._state = state
        self._stack = UndoStack(state, limit=int(self._settings["undo_limit"]))
        self._loaded_pages.clear()

    def _rebase_after_save(self, path: Path) -> bool:
        """保存后把新文件当作基线，但不重建对象——界面不重新加载。

        新文件里每张图的位置就是对象当前的 ``rect``，插入时按 z 升序，所以两边
        都按 z 排序后可以一一对应。对不上就返回 ``False``，调用方退回完整重建。
        """
        try:
            doc = PdfDocument.open(path, self._store)
        except AppError:
            logger.exception("保存后无法重新打开 {}", path)
            return False

        try:
            by_page: dict[int, list[ImageObject]] = {}
            for obj in self._state.objects:
                if isinstance(obj, ImageObject):
                    by_page.setdefault(obj.page, []).append(obj)

            # 只处理已经装载过的页：没装载过的页没有对象，这里也不该替它抽图。
            pages = sorted(set(self._loaded_pages) | set(by_page))
            fresh: dict[int, list[ImageObject]] = {}
            for index in pages:
                if index >= doc.page_count:
                    doc.close()
                    return False
                extracted = doc.editable_images(index)
                if len(extracted) != len(by_page.get(index, [])):
                    doc.close()
                    return False
                fresh[index] = extracted
        except Exception:
            logger.exception("保存后重建基线失败 {}", path)
            doc.close()
            return False

        for index, extracted in fresh.items():
            mine = sorted(by_page.get(index, []), key=lambda o: o.z)
            for obj, src in zip(mine, extracted, strict=False):
                obj.src_xref = src.src_xref
                obj.src_rect = src.src_rect
                obj.src_page = obj.page
                obj.image_id = src.image_id

        self._doc = doc
        self._cache = self._new_cache(doc)
        self._loaded_pages.update(pages)
        # 被删掉的图已经在文件里彻底消失，墓碑表必须清空：
        # 留着的话下次保存会照着旧坐标去擦，可能擦掉刚放进去的新图。
        self._state.removed.clear()
        return True

    def reload_document(self, force: bool = False) -> dict[str, Any]:
        """从磁盘重新加载当前文件。会丢弃内存里的编辑。"""
        with self._lock:
            doc = self._doc
            if doc is None:
                return {"ok": False, "message": i18n.t("error.no_document")}
            if self._stack is not None and self._stack.dirty and not force:
                return {
                    "ok": False,
                    "needs_confirm": True,
                    "message": i18n.t("dialog.reload_text"),
                }
            path = doc.path
            doc.close()
            self._doc = None

        with self._lock:
            try:
                self._generation += 1
                self._reset_to_file(path)
            except AppError as exc:
                logger.warning("重新加载失败 {}: {}", path, exc)
                self._restore_handle(path)
                return {"ok": False, "message": str(exc)}
            return self._snapshot()

    # ---- 另存与导出 ----

    def browse_save(self, suggested: str = "") -> str | None:
        if self._window is None:
            return None
        directory = ""
        with self._lock:
            if self._doc is not None:
                directory = str(self._doc.path.parent)
            else:
                try:
                    directory = str(paths.ensure_pdfs_dir())
                except OSError:
                    directory = ""
        result = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=directory,
            save_filename=str(suggested or ""),
            file_types=(i18n.t("dialog.filter_pdf"),),
        )
        return _first_path(result)

    def export_pages(self, text: str, path: str) -> dict[str, Any]:
        """把指定页导出成一个新 PDF。页码解析放在后端，前端只做输入时的预览。"""
        with self._lock:
            doc = self._doc
            if doc is None:
                return {"ok": False, "message": i18n.t("error.no_document")}
            if self._stack is not None and self._stack.dirty:
                return {"ok": False, "message": i18n.t("error.save_first")}

            pages, problems = parse_page_range(str(text or ""), doc.page_count)
            if not pages:
                return {"ok": False, "message": i18n.t("error.page_range_empty")}

            target = Path(path)
            temp_path = target.with_name(f"{target.name}.tmp-{os.getpid()}")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                out = pymupdf.open()
                try:
                    for index in pages:
                        out.insert_pdf(doc.doc, from_page=index, to_page=index)
                    out.save(temp_path, garbage=4, deflate=True)
                finally:
                    out.close()
                os.replace(temp_path, target)
            except Exception as exc:
                logger.exception("导出失败")
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                return {"ok": False, "message": i18n.t("error.save_failed", reason=str(exc))}

            logger.info("已导出 {} 页到 {}", len(pages), target)
            return {
                "ok": True,
                "path": str(target),
                "pages": len(pages),
                "errors": [{"code": code, "token": token} for code, token in problems],
            }

    # ---- 剪贴板与外部编辑 ----

    def paste_image(self, page: int = 0) -> dict[str, Any]:
        data = clipboard.read_image()
        if not data:
            return {**self._snapshot(), "ok": False, "message": i18n.t("error.clipboard_empty")}

        with self._lock:
            doc = self._doc
            stack = self._stack
            if doc is None or stack is None:
                return {**self._snapshot(), "ok": False, "message": i18n.t("error.no_document")}
            try:
                index = int(page)
            except (TypeError, ValueError):
                index = 0
            if not 0 <= index < doc.page_count:
                index = 0

            try:
                pix = pymupdf.Pixmap(data)
            except Exception:
                return {
                    **self._snapshot(),
                    "ok": False,
                    "message": i18n.t("error.image_invalid"),
                }

            page_w, page_h = doc.page_pt_size(index)
            width = page_w * 0.4
            height = width * pix.height / pix.width if pix.width else width
            rect = clamp_rect_to_page(
                Rect((page_w - width) / 2, (page_h - height) / 2, width, height), page_w, page_h
            )
            obj = ImageObject(
                id=f"paste-{uuid.uuid4().hex[:8]}",
                page=index,
                rect=rect,
                image_id=self._store.put(data),
                z=self._state.next_z(index),
            )
            before = self._state.clone_objects()
            self._state.objects.append(obj)
            self._state.selection = [obj.id]
            stack.push(StructureChanged(before, self._state.clone_objects(), "edit.paste"))
            return self._snapshot()

    def edit_external(self, object_id: str) -> dict[str, Any]:
        """把图片落到临时文件并用系统默认程序打开。"""
        with self._lock:
            obj = self._state.find(str(object_id))
            if not isinstance(obj, ImageObject):
                return {"ok": False, "message": i18n.t("error.invalid_argument", name="id")}
            data = self._store.get(obj.image_id)

        session = paths.session_temp_dir(f"edit-{uuid.uuid4().hex[:8]}")
        try:
            session.mkdir(parents=True, exist_ok=True)
            target = session / "image.png"
            target.write_bytes(data)
        except OSError as exc:
            return {"ok": False, "message": i18n.t("error.save_failed", reason=str(exc))}

        if not opener.open_external(target):
            return {"ok": False, "message": i18n.t("error.external_open")}
        return {"ok": True, "path": str(target)}

    def replace_image(self, object_id: str, path: str) -> dict[str, Any]:
        """外部编辑器改完之后回填。图片尺寸可以变，显示矩形保持不变。"""
        source = Path(str(path))
        try:
            data = source.read_bytes()
        except OSError:
            _cleanup_session(source)
            return {"ok": False, "message": i18n.t("error.external_edit_failed")}
        if not data:
            _cleanup_session(source)
            return {"ok": False, "message": i18n.t("error.external_edit_failed")}
        try:
            pymupdf.Pixmap(data)
        except Exception:
            _cleanup_session(source)
            return {"ok": False, "message": i18n.t("error.external_edit_failed")}

        with self._lock:
            obj = self._state.find(str(object_id))
            stack = self._stack
            if not isinstance(obj, ImageObject) or stack is None:
                return self._snapshot()
            stack.push(ImageReplaced(obj.id, obj.image_id, self._store.put(data), "edit.image"))
            snapshot = self._snapshot()

        _cleanup_session(source)
        return snapshot

    def straighten_table(self, object_id: str) -> dict[str, Any]:
        """把选中图片里的表格框线拉直。

        检测与重绘还没接进来，但接口形状先固定：锁内取字节 → 锁外计算 →
        锁内确认这张图没被换掉 → 压一条 ``ImageReplaced``。这样下一轮只改
        ``tablelines.straighten``，前端和撤销都不用再动。
        """
        with self._lock:
            obj = self._state.find(str(object_id))
            if not isinstance(obj, ImageObject):
                return {"ok": False, "message": i18n.t("error.invalid_argument", name="id")}
            data = self._store.get(obj.image_id)

        try:
            new_data, report = tablelines.straighten(data)
        except Exception as exc:
            logger.warning("表格框线处理失败: {}", exc)
            with self._lock:
                snapshot = self._snapshot()
            return {
                **snapshot,
                "ok": False,
                "message": i18n.t("error.table_lines_failed", reason=str(exc)),
            }

        if not report.applied:
            with self._lock:
                snapshot = self._snapshot()
            key = (
                "status.table_lines_none"
                if report.reason == "no_lines"
                else "status.table_lines_pending"
            )
            return {
                **snapshot,
                "ok": False,
                "message": i18n.t(key),
            }

        with self._lock:
            current = self._state.find(str(object_id))
            stack = self._stack
            if (
                not isinstance(current, ImageObject)
                or stack is None
                or current.image_id != obj.image_id
            ):
                return {
                    **self._snapshot(),
                    "ok": False,
                    "message": i18n.t("status.table_lines_stale"),
                }
            stack.push(
                ImageReplaced(
                    current.id,
                    current.image_id,
                    self._store.put(new_data),
                    "edit.table_lines",
                )
            )
            return {**self._snapshot(), "ok": True, "report": report.to_dict()}

    # ---- 预处理 ----

    def preprocess_pdf(self, source_mode: str = "other") -> dict[str, Any]:
        """选源文件、选目标文件，然后把黑白化丢进线程池。

        ``source_mode="current"`` 直接用当前打开的文档当源文件，省掉一次选文件。
        有未保存修改时拒绝：处理的是磁盘上的版本，不是内存里的编辑，跑完再打开
        结果就会「吃掉」那些改动。
        """
        if self._window is None:
            return {"ok": False, "reason": "unavailable", "message": i18n.t("error.unexpected")}

        with self._lock:
            current = self._doc.path if self._doc is not None else None
            dirty = bool(self._stack and self._stack.dirty)

        if str(source_mode) == "current":
            if current is None:
                return {"ok": False, "message": i18n.t("error.no_document")}
            if dirty:
                return {"ok": False, "reason": "dirty", "message": i18n.t("error.save_first")}
            source = current
        else:
            picked = _first_path(
                self._window.create_file_dialog(
                    webview.FileDialog.OPEN,
                    directory=str(current.parent) if current is not None else "",
                    file_types=(i18n.t("dialog.filter_pdf"), i18n.t("dialog.filter_all")),
                )
            )
            if not picked:
                return {"ok": False, "reason": "cancel"}
            source = Path(picked)

        target = _first_path(
            self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=str(source.parent),
                save_filename=f"{source.stem}-bw.pdf",
                file_types=(i18n.t("dialog.filter_pdf"),),
            )
        )
        if not target:
            return {"ok": False, "reason": "cancel"}

        task_id = self._new_task("preprocess")
        self._executor.submit(self._preprocess_worker, source, Path(target), task_id)
        return {"ok": True, "task": task_id}

    def _preprocess_worker(self, source: Path, target: Path, task_id: str) -> None:
        threshold = int(self._settings.get("preprocess_threshold", 235))
        try:
            count = preprocess.process(
                source,
                target,
                threshold,
                lambda done, total: self._set_progress(task_id, done, total),
            )
        except AppError as exc:
            logger.warning("预处理失败 {}: {}", source, exc)
            self._finish_task(task_id, "error", str(exc))
            return
        except Exception:
            logger.exception("预处理失败 {}", source)
            self._finish_task(task_id, "error", i18n.t("error.unexpected"))
            return
        logger.info("预处理完成 {} -> {}（{} 张图）", source, target, count)
        self._finish_task(task_id, "ready", result={"path": str(target), "count": count})

    def _set_progress(self, task_id: str, done: int, total: int) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task["progress"] = {"done": done, "total": total}

    # ---- 参考线 ----

    def update_reference(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            merged = dict(self._reference)
            if isinstance(values, dict):
                merged.update(values)
            try:
                settings.save_reference(merged)
                self._reference = settings.load_reference()
            except AppError as exc:
                logger.warning("保存参考线失败: {}", exc)
                return {**self._snapshot(), "ok": False, "message": str(exc)}
            return self._snapshot()

    def update_align(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        """对齐线：结构同参考线，但只在移动吸附时用，平时不画出来。"""
        with self._lock:
            merged = dict(self._align)
            if isinstance(values, dict):
                merged.update(values)
            try:
                settings.save_align(merged)
                self._align = settings.load_align()
            except AppError as exc:
                logger.warning("保存对齐线失败: {}", exc)
                return {**self._snapshot(), "ok": False, "message": str(exc)}
            return self._snapshot()

    # ---- 设置 ----

    def update_settings(self, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            merged = dict(self._settings)
            if isinstance(patch, dict):
                merged.update(patch)
            try:
                settings.save_app(merged)
                self._settings = settings.load_app()
            except AppError as exc:
                logger.warning("保存设置失败: {}", exc)
                return {**self._snapshot(), "ok": False, "message": str(exc)}
            # 只有动了日志三件套才重配日志：其余设置不该顺手把文件重开一遍。
            if isinstance(patch, dict) and any(str(key).startswith("log_") for key in patch):
                settings.apply_log_settings(self._settings)
            i18n.set_language(self._settings["language"])
            self._retitle()
            return self._snapshot()

    def set_language(self, code: str) -> dict[str, Any]:
        return self.update_settings({"language": code})

    def complete_first_run(self, language: str) -> dict[str, Any]:
        """首次启动选完语言：语言落盘，外观按系统偏好定一次。"""
        with self._lock:
            merged = dict(self._settings)
            merged["language"] = str(language)
            merged["theme"] = theme_tool.system_theme()
            try:
                settings.save_app(merged)
                self._settings = settings.load_app()
            except AppError as exc:
                logger.warning("保存设置失败: {}", exc)
                return {**self._snapshot(), "ok": False, "message": str(exc)}
            i18n.set_language(self._settings["language"])
            self._retitle()
            self.first_run = False
            return self._snapshot()

    def get_readme(self) -> dict[str, Any]:
        """当前语言的使用手册；没有这一份就退回英文。"""
        language = i18n.current()
        path = paths.PROGRAM_DIR / "docs" / "readme" / f"{language}.md"
        if not path.is_file():
            language = i18n.FALLBACK_LANGUAGE
            path = paths.PROGRAM_DIR / "docs" / "readme" / f"{language}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        return {"language": language, "markdown": text}

    def preview_language(self, code: str) -> dict[str, Any]:
        """首次运行的语言下拉框：只换内存里的语言，不落盘。

        落盘会让「第一次运行」的判据（app.json 是否存在）提前成立，用户中途
        关掉窗口就再也看不到语言选择。
        """
        i18n.set_language(code)
        self._retitle()
        return {"ok": True, "language": i18n.current(), "strings": i18n.strings()}

    def set_data_dir(self, raw: str) -> dict[str, Any]:
        """记下新的数据目录：当场校验，下次启动把文件搬过去。

        校验放在这里而不是下次启动：失败必须立刻告诉用户，否则界面只会一直说
        「重启后生效」，重启之后什么也没发生。
        """
        try:
            target = paths.request_data_dir(str(raw), base=paths.DATA_DIR)
        except AppError as exc:
            return {**self._snapshot(), "ok": False, "message": str(exc)}
        except OSError as error:
            return {
                **self._snapshot(),
                "ok": False,
                "message": i18n.t("about.data_dir_failed", error=error),
            }
        if paths.pending_data_dir() is None:
            return {**self._snapshot(), "message": i18n.t("about.data_dir_same")}
        return {**self._snapshot(), "message": i18n.t("about.data_dir_saved", path=target)}

    def reset_data_dir(self) -> dict[str, Any]:
        """把数据目录恢复成默认位置。"""
        return self.set_data_dir(str(paths.DATA_DIR_DEFAULT))

    def restart_app(self) -> dict[str, Any]:
        """重启程序：先把结果送回网页，再关窗。

        数据目录的搬迁只在启动早期发生，所以改完目录必须真重启一次。有未保存的
        修改时拒绝：重启等于丢弃，得先让用户自己决定。
        """
        if self.dirty:
            return {
                **self._snapshot(),
                "ok": False,
                "message": i18n.t("about.data_dir_restart_dirty"),
            }
        self._restart_requested = True
        self._close_confirmed = True
        # 关窗放进定时器：调用方要能拿到返回值，否则「重启」看起来像卡住了。
        timer = threading.Timer(0.2, self._close_window)
        timer.daemon = True
        timer.start()
        return {"ok": True, "message": ""}

    def _close_window(self) -> None:
        if self._window is None:
            return
        try:
            self._window.destroy()
        except Exception as error:  # 窗口已经关了或平台不支持
            logger.debug("关闭窗口失败: {}", error)

    def reset_settings(self) -> dict[str, Any]:
        """把应用设置、参考线、快捷键全部恢复默认。

        界面语言可能跟着变，所以调用方拿回快照后还要重新取一次语言表。
        """
        with self._lock:
            try:
                settings.save_app(settings.default_app())
                settings.save_reference(dict(settings.DEFAULT_REFERENCE))
                settings.save_align(dict(settings.DEFAULT_ALIGN))
                self._settings = settings.load_app()
                self._reference = settings.load_reference()
                self._align = settings.load_align()
            except AppError as exc:
                logger.warning("重置设置失败: {}", exc)
                return {**self._snapshot(), "ok": False, "message": str(exc)}
            settings.apply_log_settings(self._settings)
            i18n.set_language(self._settings["language"])
            self._retitle()
            return self._snapshot()

    # ---- 关闭 ----

    @property
    def close_confirmed(self) -> bool:
        return self._close_confirmed

    @property
    def restart_requested(self) -> bool:
        """窗口关掉之后是否要拉起一个新进程。"""
        return self._restart_requested

    def confirm_close(self) -> None:
        self._close_confirmed = True

    @property
    def dirty(self) -> bool:
        with self._lock:
            return bool(self._stack and self._stack.dirty)

    def request_close_prompt(self) -> None:
        if self._window is None:
            return
        self._executor.submit(self._ask_unsaved)

    def _ask_unsaved(self) -> None:
        try:
            self._window.evaluate_js(
                "window.host && window.host.askUnsaved && window.host.askUnsaved()"
            )
        except Exception:
            logger.exception("关闭询问失败")

    def answer_close(self, action: str) -> dict[str, Any]:
        if action in ("discard", "close"):
            self._close_confirmed = True
            if self._window is not None:
                self._window.destroy()
        elif action == "cancel":
            self._close_confirmed = False
        return {"ok": True}

    # ---- 内部 ----

    def _payload(self, obj: Any) -> dict[str, Any]:
        if isinstance(obj, TextObject):
            data = obj.to_dict()
            lines, height = textlayout.layout(obj.runs, obj.rect.w, obj.size_px, obj.line_height)
            # 屏幕与 PDF 用同一份排版：前端按这里下发的行/字段位置画，不再自己换行。
            data["h"] = height
            data["lines"] = [
                {
                    "baseline": line.baseline,
                    "runs": [[run.text, run.font, run.x, run.width] for run in line.runs],
                }
                for line in lines
            ]
            data["hex"] = palette.TEXT_COLORS[obj.color]
            return data
        if isinstance(obj, HighlightObject):
            data = obj.to_dict()
            data["hex"] = palette.HIGHLIGHT_COLORS[obj.color]
            return data

        data = obj.to_dict()
        if self._server is not None:
            data["thumb"] = self._server.image_url(obj.image_id, PREVIEW_PX)
            data["src"] = self._server.image_url(obj.image_id, CANVAS_PX)
        else:
            data["thumb"] = ""
            data["src"] = ""
        return data

    def _snapshot(self) -> dict[str, Any]:
        # 版本号在生成快照的那一刻分配。前端只认更大的 rev，晚到的旧回包自动作废。
        self._rev += 1
        doc = self._doc
        pages = [page.to_dict() for page in self._state.pages]
        objects = [self._payload(obj) for obj in self._state.objects]
        return {
            "ok": True,
            "rev": self._rev,
            "message": "",
            "version": version_module.version(),
            "first_run": self.first_run,
            "data_dir": str(paths.DATA_DIR),
            "data_dir_next": str(paths.pending_data_dir() or ""),
            "data_dir_default": str(paths.DATA_DIR_DEFAULT),
            "data_dir_status": dict(paths.MIGRATION),
            "doc": {
                "path": str(doc.path) if doc else "",
                "name": doc.path.name if doc else "",
                "dirty": bool(self._stack and self._stack.dirty),
                "page_count": doc.page_count if doc else 0,
                "generation": self._generation,
                "can_save": doc is not None,
            },
            "pages": pages,
            "objects": objects,
            "selection": list(self._state.selection),
            "history": {
                "can_undo": bool(self._stack and self._stack.can_undo),
                "can_redo": bool(self._stack and self._stack.can_redo),
                "label": self._stack.label if self._stack else "",
            },
            "language": i18n.current(),
            "languages": i18n.available(),
            "language_names": i18n.language_names(),
            "theme": self._settings.get("theme", "light"),
            "show_guides": bool(self._settings.get("show_guides", True)),
            "show_inspector": bool(self._settings.get("show_inspector", True)),
            "eight_handles": bool(self._settings.get("eight_handles", True)),
            "keybindings": dict(self._settings.get("keybindings") or {}),
            "reference": dict(self._reference),
            "align": dict(self._align),
            "palette": palette.palette_payload(),
            "fonts": [
                {"key": key, "css": font_table.css_name(key)} for key in font_table.families()
            ],
            "defaults": {
                "text_font": str(self._settings.get("text_font", "msyh")),
                "text_size_px": int(self._settings.get("text_size_px", 14)),
                "text_color": str(self._settings.get("text_color", "blue")),
                "text_width_mm": float(self._settings.get("text_width_mm", 40.0)),
                "text_line_height": float(self._settings.get("text_line_height", 1.15)),
                "highlight_height_px": int(self._settings.get("highlight_height_px", 15)),
                "highlight_color": str(self._settings.get("highlight_color", "yellow")),
            },
            "undo_limit": int(self._settings.get("undo_limit", 100)),
            "log_level": str(self._settings.get("log_level", "INFO")),
            "log_cleanup": bool(self._settings.get("log_cleanup", True)),
            "log_retention_days": int(self._settings.get("log_retention_days", 30)),
            "backup_retention_days": int(self._settings.get("backup_retention_days", 30)),
        }

    def _new_task(self, label: str) -> str:
        with self._lock:
            self._task_seq += 1
            task_id = f"{label}-{self._task_seq}"
            self._tasks[task_id] = {
                "state": "running",
                "progress": {},
                "message": "",
                "label": label,
            }
            while len(self._tasks) > _TASK_HISTORY:
                self._tasks.pop(next(iter(self._tasks)))
            return task_id

    def _finish_task(
        self,
        task_id: str,
        state: str,
        message: str = "",
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task["state"] = state
                task["message"] = message
                if result is not None:
                    task["result"] = result


def _cleanup_session(path: Path) -> None:
    """删掉本次外部编辑的临时目录。只碰 TEMP_DIR 下面自己建的那一层。"""
    try:
        parent = path.parent
        if parent.parent != paths.TEMP_DIR:
            return
        for item in parent.iterdir():
            item.unlink(missing_ok=True)
        parent.rmdir()
    except OSError:
        pass


def _sweep_temp(max_age_seconds: float = 86400.0) -> None:
    """清掉上次运行留下的编辑临时目录。只动 edit-* 且超过一天的。"""
    root = paths.TEMP_DIR
    if not root.is_dir():
        return
    now = time.time()
    for entry in root.glob("edit-*"):
        if not entry.is_dir():
            continue
        try:
            if now - entry.stat().st_mtime < max_age_seconds:
                continue
            for item in entry.iterdir():
                item.unlink(missing_ok=True)
            entry.rmdir()
        except OSError:
            continue


def _sweep_backups(directory: Path, retention_days: int) -> None:
    """清掉超过保留期的备份。删不掉的跳过，下次启动再试。"""
    try:
        removed = sweep_backups(directory, retention_days)
    except OSError:
        logger.warning("清理过期备份失败 {}", directory)
        return
    if removed:
        logger.info("已清理 {} 份过期备份", removed)


def _first_path(result: Any) -> str | None:
    """文件对话框有时返回 str，有时返回 list，统一成一个路径。"""
    if not result:
        return None
    if isinstance(result, (list, tuple)):
        return str(result[0]) if result else None
    return str(result)


def _floats(values: Any) -> list[float]:
    """把前端传来的切分线夹到 (0,1) 并丢掉非法值。"""
    if not isinstance(values, (list, tuple)):
        return []
    result: list[float] = []
    for raw in values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and 0.0 < value < 1.0:
            result.append(value)
    return result


def _float_of(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _float_between(value: Any, default: float, low: float, high: float) -> float:
    if value is None:
        return float(default)
    return min(max(_float_of(value, float(default)), low), high)


def _int_between(value: Any, default: int, low: int, high: int) -> int:
    if value is None:
        return int(default)
    return int(min(max(_float_of(value, float(default)), float(low)), float(high)))


def _page_index(value: Any, count: int) -> int:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return 0
    return index if 0 <= index < count else 0
