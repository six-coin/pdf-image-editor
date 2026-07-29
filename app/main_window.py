import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QToolBar, QSpinBox,
    QLabel, QWidget, QVBoxLayout, QMessageBox,
    QPushButton, QApplication, QLineEdit, QTextEdit
)

from app.pdf_model import PdfModel
from app.pdf_scene import PdfScene
from app.pdf_canvas import PdfCanvas
from app.split_tool import SplitTool, SplitMode
from app.image_item import ImageItem
from app.dialogs.split_dialog import SplitDialog


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

        self._current_file = None

        self._setup_menu()
        self._setup_toolbar()
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

        view_menu = mb.addMenu("视图(&V)")

        self._guide_action = QAction("显示参考线", self)
        self._guide_action.setCheckable(True)
        self._guide_action.setChecked(True)
        self._guide_action.triggered.connect(self._on_toggle_guides)
        view_menu.addAction(self._guide_action)

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

        edit_menu = mb.addMenu("编辑(&E)")

        add_white_action = QAction("添加白色矩形", self)
        add_white_action.triggered.connect(self._on_add_white_rect)
        edit_menu.addAction(add_white_action)

        delete_action = QAction("删除选中", self)
        delete_action.setShortcut(QKeySequence.Delete)
        delete_action.triggered.connect(self._on_delete_selected)
        edit_menu.addAction(delete_action)

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

        tb.addSeparator()

        add_white_btn = QPushButton("添加白色矩形")
        add_white_btn.clicked.connect(self._on_add_white_rect)
        tb.addWidget(add_white_btn)

    def _setup_shortcuts(self):
        self._shortcut_e = QShortcut(QKeySequence("E"), self)
        self._shortcut_e.activated.connect(lambda: self._enter_split(SplitMode.HORIZONTAL))

        self._shortcut_r = QShortcut(QKeySequence("R"), self)
        self._shortcut_r.activated.connect(lambda: self._enter_split(SplitMode.VERTICAL))

        self._shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._shortcut_esc.activated.connect(self._on_split_cancel)

        self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._shortcut_undo.activated.connect(self._split_tool.undo_last)

    def _connect_signals(self):
        self._canvas.zoom_changed.connect(self._on_zoom_changed)

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 PDF", "", "PDF 文件 (*.pdf);;所有文件 (*)"
        )
        if path:
            self._load_file(path)

    def _load_file(self, path):
        self._split_tool.cancel()
        self._update_split_ui()
        try:
            pages_data = self._model.load(path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件:\n{e}")
            return

        self._current_file = path
        self.setWindowTitle(f"Simple PDF Editor - {os.path.basename(path)}")

        self._scene.build_from_data(pages_data, show_guides=self._guide_action.isChecked())
        self._canvas.fit_to_width()

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
        QMessageBox.information(self, "完成", "文件已保存")

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

    def _on_zoom_spin(self, value):
        self._canvas.zoom_level = value / 100.0

    def _on_zoom_changed(self, zoom):
        self._zoom_spin.blockSignals(True)
        self._zoom_spin.setValue(int(zoom * 100))
        self._zoom_spin.blockSignals(False)

    def _on_add_white_rect(self):
        if self._model.page_count <= 0:
            return
        item = self._scene.add_white_rectangle()
        if item:
            self._status_msg("已添加白色矩形")

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

    def _update_split_ui(self):
        active = self._split_tool.is_active
        self._split_complete_btn.setEnabled(active)
        self._split_cancel_btn.setEnabled(active)
        if active:
            mode_name = "水平" if self._split_tool.mode == SplitMode.HORIZONTAL else "竖直"
            self._status_msg(f"分割模式 [{mode_name}] - 点击放置参考线, Enter完成, Esc取消")
        else:
            self._status_msg("")

    def _status_msg(self, msg):
        self.statusBar().showMessage(msg)

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
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._on_split_complete()
                return
        super().keyPressEvent(event)
