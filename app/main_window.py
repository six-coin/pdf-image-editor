import os
import random
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QUndoStack, QPixmap, QImage
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QToolBar, QSpinBox,
    QLabel, QWidget, QVBoxLayout, QMessageBox,
    QPushButton, QApplication, QLineEdit, QTextEdit,
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
        self._setup_toolbar()
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

        split_action = QAction("PDF 分割...", self)
        split_action.triggered.connect(self._on_split)
        file_menu.addAction(split_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = mb.addMenu("编辑(&E)")

        undo_action = self._undo_stack.createUndoAction(self, "撤销(&U)")
        edit_menu.addAction(undo_action)

        redo_action = self._undo_stack.createRedoAction(self, "重做(&R)")
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        add_white_action = QAction("添加白色矩形", self)
        add_white_action.triggered.connect(self._on_add_white_rect)
        edit_menu.addAction(add_white_action)

        paste_action = QAction("从剪贴板新增图像", self)
        paste_action.triggered.connect(self._on_paste_image)
        edit_menu.addAction(paste_action)

        delete_action = QAction("删除选中", self)
        delete_action.setShortcut(QKeySequence.Delete)
        delete_action.triggered.connect(self._on_delete_selected)
        edit_menu.addAction(delete_action)

        view_menu = mb.addMenu("视图(&V)")

        self._guide_action = QAction("显示参考线", self)
        self._guide_action.setCheckable(True)
        self._guide_action.setChecked(True)
        self._guide_action.triggered.connect(self._on_toggle_guides)
        view_menu.addAction(self._guide_action)

        ref_action = QAction("参考线设置...", self)
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

    def _setup_toolbar(self):
        tb = QToolBar("工具栏")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel("缩放: "))
        self._zoom_spin = QSpinBox()
        self._zoom_spin.setRange(10, 1000)
        self._zoom_spin.setValue(100)
        self._zoom_spin.setSuffix("%")
        self._zoom_spin.setFixedWidth(80)
        self._zoom_spin.valueChanged.connect(self._on_zoom_spin)
        tb.addWidget(self._zoom_spin)

        tb.addSeparator()

        self._split_complete_btn = QPushButton("完成分割 (Enter)")
        self._split_complete_btn.setEnabled(False)
        self._split_complete_btn.clicked.connect(self._on_split_complete)
        tb.addWidget(self._split_complete_btn)

        self._split_cancel_btn = QPushButton("取消分割 (Esc)")
        self._split_cancel_btn.setEnabled(False)
        self._split_cancel_btn.clicked.connect(self._on_split_cancel)
        tb.addWidget(self._split_cancel_btn)

        self._keep_middle_btn = QPushButton("仅保留中间 (Q)")
        self._keep_middle_btn.setEnabled(False)
        self._keep_middle_btn.clicked.connect(self._on_keep_middle)
        tb.addWidget(self._keep_middle_btn)

        tb.addSeparator()

        add_white_btn = QPushButton("添加白色矩形")
        add_white_btn.clicked.connect(self._on_add_white_rect)
        tb.addWidget(add_white_btn)

        paste_btn = QPushButton("从剪贴板新增图像")
        paste_btn.clicked.connect(self._on_paste_image)
        tb.addWidget(paste_btn)

        tb.addSeparator()

        self._edit_btn = QPushButton("用外部编辑器编辑")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_external_edit)
        tb.addWidget(self._edit_btn)

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

        self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._shortcut_undo.activated.connect(self._on_undo)

        self._shortcut_q = QShortcut(QKeySequence("Q"), self)
        self._shortcut_q.activated.connect(self._on_keep_middle)

    def _connect_signals(self):
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas.verticalScrollBar().valueChanged.connect(self._update_current_page)
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def _on_undo(self):
        if self._split_tool.is_active:
            self._split_tool.undo_last()
        else:
            self._undo_stack.undo()

    def _on_esc(self):
        if self._split_tool.is_active:
            self._on_split_cancel()
        else:
            pass

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

    def _on_zoom_spin(self, value):
        self._canvas.zoom_level = value / 100.0

    def _on_zoom_changed(self, zoom):
        self._zoom_spin.blockSignals(True)
        self._zoom_spin.setValue(int(zoom * 100))
        self._zoom_spin.blockSignals(False)
        self._zoom_label.setText(f"{int(zoom * 100)}%")

    def _on_add_white_rect(self):
        if self._model.page_count <= 0:
            return
        item = self._scene.add_white_rectangle()
        if item:
            self._status_msg("已添加白色矩形")

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

        self._status_msg("已从剪贴板添加图像")

    def _on_delete_selected(self):
        if self._split_tool.is_active:
            return
        self._scene.delete_selected()
        self._status_msg("")

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
                self._status_msg("请先选中一张图片")
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
            self._status_msg("分割完成")

    def _on_split_cancel(self):
        if self._split_tool.is_active:
            self._split_tool.cancel()
            self._update_split_ui()
            self._status_msg("已取消")

    def _on_keep_middle(self):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QSpinBox, QLineEdit, QTextEdit)):
            return
        if self._split_tool.is_active and self._split_tool.has_cross_hairs:
            self._split_tool.confirm_keep_middle(self._scene)
            self._update_split_ui()
            self._status_msg("已保留中间部分")

    def _update_split_ui(self):
        active = self._split_tool.is_active
        self._split_complete_btn.setEnabled(active)
        self._split_cancel_btn.setEnabled(active)
        can_keep_middle = active and self._split_tool.has_cross_hairs
        self._keep_middle_btn.setEnabled(can_keep_middle)
        if active:
            mode_name = "水平" if self._split_tool.mode == SplitMode.HORIZONTAL else "竖直"
            base = f"分割模式 [{mode_name}] - 点击放置参考线, Enter/T完成, Esc取消"
            if can_keep_middle:
                base += ", Q保留中间"
            self._status_msg(base)
        else:
            self._status_msg("")

    def _status_msg(self, msg):
        self.statusBar().showMessage(msg)

    def _flash_status(self, msg):
        self.statusBar().showMessage(msg)
        self._flash_timer.start(2000)

    def _on_selection_changed(self):
        for item in self._scene.selectedItems():
            if isinstance(item, ImageItem):
                self._edit_btn.setEnabled(True)
                return
        self._edit_btn.setEnabled(False)

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
        if new_pixmap.isNull():
            QMessageBox.warning(self, "错误", "无法读取编辑后的图像")
            return
        if new_pixmap.width() != old_w or new_pixmap.height() != old_h:
            QMessageBox.warning(
                self, "错误",
                f"图像尺寸必须保持不变。\n原始: {old_w}×{old_h}\n当前: {new_pixmap.width()}×{new_pixmap.height()}"
            )
            return

        old_state = img.get_state()
        img.setPixmap(new_pixmap)
        new_state = img.get_state()

        from app.undo_commands import TransformCommand
        self._undo_stack.push(TransformCommand([(img, old_state, new_state)]))
        self._flash_status("图像已替换")

    def closeEvent(self, event):
        if self._undo_stack.isClean():
            self._model.close()
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
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_T):
                self._on_split_complete()
                return
        super().keyPressEvent(event)
