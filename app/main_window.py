import os
import random
import shutil
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QUndoStack, QPixmap, QImage
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QSpinBox, QInputDialog,
    QLabel, QWidget, QVBoxLayout, QMessageBox,
    QApplication, QLineEdit, QTextEdit,
    QDialog, QDialogButtonBox
)

from app.pdf_model import PdfModel
from app.pdf_scene import PdfScene
from app.pdf_canvas import PdfCanvas
from app.split_tool import SplitTool, SplitMode
from app.image_item import ImageItem
from app.dialogs.split_dialog import SplitDialog
from app.dialogs.reference_dialog import ReferenceDialog
from app.guide_config import load_config, save_config
from app.utils import mm_to_pt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple PDF Editor")
        self.resize(1200, 800)

        self._model = PdfModel()
        self._scene = PdfScene()
        self._canvas = PdfCanvas(self._scene)
        self._split_tool = SplitTool(self._scene)
        self._canvas.set_split_tool(self._split_tool)
        self._split_tool.set_guides_changed_callback(self._update_split_ui)

        self._undo_stack = QUndoStack(self)
        self._scene.set_undo_stack(self._undo_stack)

        self._current_file = None
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(lambda: self.statusBar().showMessage(""))

        self._setup_menu()
        self._setup_statusbar()
        self._setup_shortcuts()
        self._connect_signals()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        self.setCentralWidget(central)

        self.setAcceptDrops(True)

    def _setup_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("文件(&F)")

        open_action = QAction("打开(&O)...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        save_action = QAction("保存(&S)", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._on_save)
        file_menu.addAction(save_action)

        save_as_action = QAction("另存为(&A)...", self)
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self._on_save_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        split_action = QAction("PDF 分割(&C)...", self)
        split_action.triggered.connect(self._on_split)
        file_menu.addAction(split_action)

        preprocess_action = QAction("PDF 预处理(&V)...", self)
        preprocess_action.triggered.connect(self._on_preprocess)
        file_menu.addAction(preprocess_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = mb.addMenu("编辑(&E)")

        undo_action = QAction("撤销", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.triggered.connect(self._on_undo)
        edit_menu.addAction(undo_action)

        redo_action = QAction("重做", self)
        redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        redo_action.triggered.connect(self._on_redo)
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        add_white_action = QAction("添加白色矩形", self)
        add_white_action.triggered.connect(self._on_add_white_rect)
        edit_menu.addAction(add_white_action)

        paste_action = QAction("从剪贴板新增图像", self)
        paste_action.triggered.connect(self._on_paste_image)
        edit_menu.addAction(paste_action)

        self._edit_action = QAction("用外部编辑器编辑", self)
        self._edit_action.setEnabled(False)
        self._edit_action.triggered.connect(self._on_external_edit)
        edit_menu.addAction(self._edit_action)

        edit_menu.addSeparator()

        delete_action = QAction("删除选中", self)
        delete_action.setShortcut(QKeySequence.Delete)
        delete_action.triggered.connect(self._on_delete_selected)
        edit_menu.addAction(delete_action)

        edit_menu.addSeparator()

        front_action = QAction("置顶选中图片", self)
        front_action.setShortcut(QKeySequence("Ctrl+U"))
        front_action.triggered.connect(self._on_bring_to_front)
        edit_menu.addAction(front_action)

        back_action = QAction("置底选中图片", self)
        back_action.setShortcut(QKeySequence("Ctrl+L"))
        back_action.triggered.connect(self._on_send_to_back)
        edit_menu.addAction(back_action)

        edit_menu.addSeparator()

        self._split_complete_action = QAction("完成分割 (T)", self)
        self._split_complete_action.setEnabled(False)
        self._split_complete_action.triggered.connect(self._on_split_complete)
        edit_menu.addAction(self._split_complete_action)

        self._split_cancel_action = QAction("取消分割 (Esc)", self)
        self._split_cancel_action.setEnabled(False)
        self._split_cancel_action.triggered.connect(self._on_split_cancel)
        edit_menu.addAction(self._split_cancel_action)

        self._keep_middle_action = QAction("仅保留中间 (Q)", self)
        self._keep_middle_action.setEnabled(False)
        self._keep_middle_action.triggered.connect(self._on_keep_middle)
        edit_menu.addAction(self._keep_middle_action)

        self._punch_middle_action = QAction("提取中间部分 (I)", self)
        self._punch_middle_action.setEnabled(False)
        self._punch_middle_action.triggered.connect(self._on_punch_middle)
        edit_menu.addAction(self._punch_middle_action)

        view_menu = mb.addMenu("视图(&V)")

        self._guide_action = QAction("显示参考线(&V)", self)
        self._guide_action.setCheckable(True)
        self._guide_action.setChecked(True)
        self._guide_action.triggered.connect(self._on_toggle_guides)
        view_menu.addAction(self._guide_action)

        ref_action = QAction("参考线设置(&S)...", self)
        ref_action.triggered.connect(self._on_reference_settings)
        view_menu.addAction(ref_action)

        view_menu.addSeparator()

        zoom_in_action = QAction("放大", self)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        zoom_in_action.triggered.connect(self._canvas.zoom_in)
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("缩小", self)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        zoom_out_action.triggered.connect(self._canvas.zoom_out)
        view_menu.addAction(zoom_out_action)

        fit_action = QAction("适合宽度", self)
        fit_action.setShortcut(QKeySequence("Ctrl+0"))
        fit_action.triggered.connect(self._canvas.fit_to_width)
        view_menu.addAction(fit_action)

        zoom_custom_action = QAction("手动调节缩放(&T)...", self)
        zoom_custom_action.triggered.connect(self._on_custom_zoom)
        view_menu.addAction(zoom_custom_action)

    def _setup_statusbar(self):
        sb = self.statusBar()
        self._page_label = QLabel("0 / 0")
        self._zoom_label = QLabel("100%")
        sb.addWidget(self._page_label)
        sb.addPermanentWidget(self._zoom_label)
        self._current_page_idx = 0

    def _update_page_label(self):
        count = self._model.page_count
        if count > 0 and self._current_page_idx > 0:
            self._page_label.setText(f"第{self._current_page_idx}页 / 共{count}页")
        elif count > 0:
            self._page_label.setText(f"共{count}页")
        else:
            self._page_label.setText("0 / 0")

    def _update_current_page(self):
        if self._model.page_count <= 0:
            return
        vp = self._canvas.viewport()
        if vp is None:
            return
        center = self._canvas.mapToScene(vp.rect().center())
        page = self._scene.get_page_at_scene_y(center.y())
        if page:
            idx = page.page_index + 1
            if idx != self._current_page_idx:
                self._current_page_idx = idx
                self._update_page_label()

    def _setup_shortcuts(self):
        self._shortcut_e = QShortcut(QKeySequence("E"), self)
        self._shortcut_e.activated.connect(lambda: self._enter_split(SplitMode.HORIZONTAL))

        self._shortcut_r = QShortcut(QKeySequence("R"), self)
        self._shortcut_r.activated.connect(lambda: self._enter_split(SplitMode.VERTICAL))

        self._shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._shortcut_esc.activated.connect(self._on_esc)

        self._shortcut_q = QShortcut(QKeySequence("Q"), self)
        self._shortcut_q.activated.connect(self._on_keep_middle)

        self._shortcut_i = QShortcut(QKeySequence("I"), self)
        self._shortcut_i.activated.connect(self._on_punch_middle)

    def _connect_signals(self):
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas.verticalScrollBar().valueChanged.connect(self._update_current_page)
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def _on_undo(self):
        if self._split_tool.is_active:
            self._split_tool.undo_last()
        else:
            self._undo_stack.undo()

    def _on_redo(self):
        self._undo_stack.redo()

    def _on_esc(self):
        if self._split_tool.is_active:
            self._on_split_cancel()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 PDF", "", "PDF 文件 (*.pdf);;所有文件 (*)"
        )
        if path:
            self._load_file(path)

    def _load_file(self, path):
        self._split_tool.cancel()
        self._update_split_ui()
        self._undo_stack.clear()
        try:
            pages_data = self._model.load(path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件:\n{e}")
            return

        self._current_file = path
        self.setWindowTitle(f"Simple PDF Editor - {os.path.basename(path)}")

        self._scene.build_from_data(pages_data, show_guides=self._guide_action.isChecked())
        self._canvas.fit_to_width()
        self._undo_stack.setClean()
        self._current_page_idx = 1
        self._update_page_label()

    def _on_save(self):
        if self._current_file:
            self._do_save(self._current_file)
        else:
            self._on_save_as()

    def _on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", "", "PDF 文件 (*.pdf)"
        )
        if path:
            self._do_save(path)
            self._current_file = path
            self.setWindowTitle(f"Simple PDF Editor - {os.path.basename(path)}")

    def _do_save(self, path):
        try:
            images_data = self._scene.collect_images_for_save()
            self._model.save(path, images_data)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败:\n{e}")
            return
        self._flash_status("文件保存成功")
        self._undo_stack.setClean()

    def _on_custom_zoom(self):
        current = int(self._canvas.zoom_level * 100)
        value, ok = QInputDialog.getInt(
            self, "手动调节缩放", "缩放百分比:", current, 10, 1000, 10
        )
        if ok:
            self._canvas.zoom_level = value / 100.0

    def _on_split(self):
        if self._model.page_count <= 0:
            QMessageBox.warning(self, "提示", "请先打开一个 PDF 文件")
            return

        dlg = SplitDialog(self._model.page_count, self)
        if dlg.exec() == SplitDialog.Accepted:
            pages = dlg.selected_pages()
            if not pages:
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "保存分割结果", "", "PDF 文件 (*.pdf)"
            )
            if path:
                try:
                    self._model.save_split(path, pages)
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"分割失败:\n{e}")
                    return
                QMessageBox.information(self, "完成", "分割完成")

    def _on_toggle_guides(self, checked):
        self._scene.guide_overlay.set_visible(checked)

    def _on_reference_settings(self):
        cfg = load_config()
        dlg = ReferenceDialog(cfg, self)
        if dlg.exec() == ReferenceDialog.Accepted:
            new_cfg = dlg.get_values()
            save_config(new_cfg)
            self._scene.guide_overlay.reload_config()
            self._scene.guide_overlay.update_positions(self._scene.pages)

    def _on_zoom_changed(self, zoom):
        self._zoom_label.setText(f"{int(zoom * 100)}%")

    def _on_add_white_rect(self):
        if self._model.page_count <= 0:
            return
        item = self._scene.add_white_rectangle()
        if item:
            self._flash_status("已添加白色矩形")

    def _on_paste_image(self):
        if self._model.page_count <= 0:
            QMessageBox.warning(self, "提示", "请先打开一个 PDF 文件")
            return

        clip = QApplication.clipboard()
        qimg = clip.image()
        if qimg.isNull():
            QMessageBox.warning(self, "提示", "剪贴板中没有图像")
            return

        pixmap = QPixmap.fromImage(qimg)
        if pixmap.isNull():
            QMessageBox.warning(self, "提示", "无法读取剪贴板中的图像")
            return

        active = self._scene.active_page_index()
        if active < 0:
            active = 0
        page = self._scene.get_page_by_index(active)
        if page is None:
            return

        x = mm_to_pt(10)
        y = mm_to_pt(10)

        item = ImageItem(active)
        item.setPixmap(pixmap)
        item.setPos(x, y)
        item.setZValue(10)
        item.setParentItem(page)
        self._scene.addItem(item)
        page.add_image(item)
        self._scene.clearSelection()
        item.setSelected(True)

        if self._scene.undo_stack:
            from app.undo_commands import AddWhiteRectCommand
            self._scene.undo_stack.push(AddWhiteRectCommand(self._scene, item, page))

        self._flash_status("已从剪贴板添加图像")

    def _on_delete_selected(self):
        if self._split_tool.is_active:
            return
        self._scene.delete_selected()
        self._status_msg("")

    def _on_bring_to_front(self):
        max_z = 10
        for item in self._scene.items():
            if isinstance(item, ImageItem):
                max_z = max(max_z, item.zValue())
        for item in self._scene.selectedItems():
            if isinstance(item, ImageItem):
                item.setZValue(max_z + 1)

    def _on_send_to_back(self):
        min_z = 10
        for item in self._scene.items():
            if isinstance(item, ImageItem):
                min_z = min(min_z, item.zValue())
        for item in self._scene.selectedItems():
            if isinstance(item, ImageItem):
                item.setZValue(max(min_z - 1, 1))

    def _enter_split(self, mode):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QSpinBox, QLineEdit, QTextEdit)):
            return
        if not self._split_tool.is_active:
            sel = self._scene.selectedItems()
            img = None
            for s in sel:
                if isinstance(s, ImageItem):
                    img = s
                    break
            if img is None:
                self._flash_status("请先选中一张图片")
                return
            self._split_tool.start(img, mode)
            self._update_split_ui()
        else:
            self._split_tool.switch_mode(mode)
            self._update_split_ui()

    def _on_split_complete(self):
        if self._split_tool.is_active:
            self._split_tool.confirm(self._scene)
            self._update_split_ui()
            self._flash_status("分割完成")

    def _on_split_cancel(self):
        if self._split_tool.is_active:
            self._split_tool.cancel()
            self._update_split_ui()
            self._flash_status("已取消")

    def _on_keep_middle(self):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QSpinBox, QLineEdit, QTextEdit)):
            return
        if self._split_tool.is_active and self._split_tool.has_cross_hairs:
            self._split_tool.confirm_keep_middle(self._scene)
            self._update_split_ui()
            self._flash_status("已保留中间部分")

    def _on_punch_middle(self):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QSpinBox, QLineEdit, QTextEdit)):
            return
        if self._split_tool.is_active and self._split_tool.has_cross_hairs:
            self._split_tool.confirm_punch_middle(self._scene)
            self._update_split_ui()
            self._flash_status("已提取中间部分")

    def _update_split_ui(self):
        active = self._split_tool.is_active
        self._split_complete_action.setEnabled(active)
        self._split_cancel_action.setEnabled(active)
        can_cross = active and self._split_tool.has_cross_hairs
        self._keep_middle_action.setEnabled(can_cross)
        self._punch_middle_action.setEnabled(can_cross)
        if active:
            mode_name = "水平" if self._split_tool.mode == SplitMode.HORIZONTAL else "竖直"
            base = f"分割模式 [{mode_name}] - 点击放置参考线, T完成, Esc取消"
            if can_cross:
                base += ", Q保留中间, I提取中间"
            self._status_msg(base)
        else:
            self._status_msg("")

    def _status_msg(self, msg):
        self.statusBar().showMessage(msg)

    def _flash_status(self, msg):
        self.statusBar().showMessage(msg)
        self._flash_timer.start(5000)

    def _on_selection_changed(self):
        for item in self._scene.selectedItems():
            if isinstance(item, ImageItem):
                self._edit_action.setEnabled(True)
                return
        self._edit_action.setEnabled(False)

    def _on_external_edit(self):
        sel = self._scene.selectedItems()
        img = None
        for s in sel:
            if isinstance(s, ImageItem):
                img = s
                break
        if img is None:
            return

        pixmap = img.pixmap()
        if pixmap is None or pixmap.isNull():
            return

        old_w = pixmap.width()
        old_h = pixmap.height()

        temp_dir = os.path.join(os.getcwd(), "temp")
        os.makedirs(temp_dir, exist_ok=True)

        hex_name = format(random.getrandbits(32), "08x")
        temp_path = os.path.join(temp_dir, f"edit_{hex_name}.png")
        pixmap.save(temp_path, "PNG")

        os.startfile(temp_path)

        dlg = QDialog(self)
        dlg.setWindowTitle("外部编辑")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("编辑完成后，请点击完成以替换文档中的图片。"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("完成")
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.exec()

        new_pixmap = QPixmap(temp_path)
        ok = True
        if new_pixmap.isNull():
            QMessageBox.warning(self, "错误", "无法读取编辑后的图像")
            ok = False
        elif new_pixmap.width() != old_w or new_pixmap.height() != old_h:
            QMessageBox.warning(
                self, "错误",
                f"图像尺寸必须保持不变。\n原始: {old_w}×{old_h}\n当前: {new_pixmap.width()}×{new_pixmap.height()}"
            )
            ok = False

        if ok:
            old_state = img.get_state()
            img.setPixmap(new_pixmap)
            img.original_bytes = None
            new_state = img.get_state()
            from app.undo_commands import TransformCommand
            self._undo_stack.push(TransformCommand([(img, old_state, new_state)]))
            self._flash_status("图像已替换")

        os.remove(temp_path)

    def closeEvent(self, event):
        if self._undo_stack.isClean():
            self._model.close()
            self._clean_temp()
            event.accept()
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("未保存的修改")
        msg_box.setText("文档已修改，是否保存？")
        msg_box.setIcon(QMessageBox.Warning)
        save_btn = msg_box.addButton("保存(&S)", QMessageBox.AcceptRole)
        save_as_btn = msg_box.addButton("另存为(&A)...", QMessageBox.ActionRole)
        discard_btn = msg_box.addButton("不保存(&D)", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消(&C)", QMessageBox.RejectRole)
        msg_box.setDefaultButton(save_btn)
        msg_box.setEscapeButton(cancel_btn)
        msg_box.exec()
        clicked = msg_box.clickedButton()

        if clicked == save_btn:
            self._on_save()
            if not self._undo_stack.isClean():
                event.ignore()
                return
        elif clicked == save_as_btn:
            self._on_save_as()
            if not self._undo_stack.isClean():
                event.ignore()
                return
        elif clicked == discard_btn:
            pass
        else:
            event.ignore()
            return

        self._model.close()
        self._clean_temp()
        event.accept()

    def keyPressEvent(self, event):
        if self._split_tool.is_active:
            if event.key() == Qt.Key_E:
                self._split_tool.switch_mode(SplitMode.HORIZONTAL)
                self._update_split_ui()
                return
            elif event.key() == Qt.Key_R:
                self._split_tool.switch_mode(SplitMode.VERTICAL)
                self._update_split_ui()
                return
            elif event.key() == Qt.Key_T:
                self._on_split_complete()
                return
            elif event.key() == Qt.Key_I and self._split_tool.has_cross_hairs:
                self._on_punch_middle()
                return
        super().keyPressEvent(event)

    def _clean_temp(self):
        temp_dir = os.path.join(os.getcwd(), "temp")
        if os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

    def _on_preprocess(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要预处理的 PDF", "", "PDF 文件 (*.pdf);;所有文件 (*)"
        )
        if not path:
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存预处理结果", "", "PDF 文件 (*.pdf)"
        )
        if not save_path:
            return

        try:
            self._preprocess_pdf(path, save_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"预处理失败:\n{e}")
            return

        reply = QMessageBox.question(
            self, "完成", "预处理完成。是否在编辑器中打开结果？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._load_file(save_path)

    def _preprocess_pdf(self, input_path, output_path, threshold=235):
        import numpy as np
        from PIL import Image
        import io as io_module

        def make_grayscale(image_bytes, threshold):
            image = Image.open(io_module.BytesIO(image_bytes))
            if image.mode not in ("RGB", "RGBA", "LA", "L", "P"):
                image = image.convert("RGB")
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])
                image = background
            elif image.mode == "P":
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])
                image = background
            if image.mode != "L":
                image = image.convert("L")
            img_array = np.array(image, dtype=np.uint8)
            img_array[img_array >= threshold] = 255
            result_img = Image.fromarray(img_array, mode="L")
            output_io = io_module.BytesIO()
            result_img.save(output_io, format="PNG", icc_profile=None)
            return output_io.getvalue()

        import fitz
        doc = fitz.open(input_path)
        processed_xrefs = {}

        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            for img in image_list:
                xref = img[0]
                if xref in processed_xrefs:
                    stream = processed_xrefs[xref]
                else:
                    try:
                        base_image = doc.extract_image(xref)
                        original_bytes = base_image["image"]
                        gray_png = make_grayscale(original_bytes, threshold)
                        processed_xrefs[xref] = gray_png
                        stream = gray_png
                    except Exception as e:
                        print(f"警告：处理图像 xref={xref} 时出错: {e}")
                        continue
                try:
                    page.replace_image(xref, stream=stream)
                except Exception as e:
                    print(f"警告：替换图像 xref={xref} 时出错: {e}")

        doc.save(output_path, garbage=4, deflate=True)
        doc.close()
        print(f"黑白转换完成 -> {output_path}")
