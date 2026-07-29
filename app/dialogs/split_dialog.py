from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt

from app.utils import parse_page_range


class SplitDialog(QDialog):
    def __init__(self, total_pages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF 分割")
        self.setMinimumWidth(400)
        self._total = total_pages

        layout = QVBoxLayout(self)

        info = QLabel(f"总页数: {total_pages}")
        layout.addWidget(info)

        layout.addWidget(QLabel("页码范围 (例: 1-3,5,7-9):"))
        self._range_edit = QLineEdit()
        self._range_edit.setPlaceholderText("1-3,5,7-9")
        self._range_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._range_edit)

        self._preview = QLabel("预览: ")
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._button_box.accepted.connect(self._validate_and_accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        self._selected_pages = []

    def _on_text_changed(self):
        text = self._range_edit.text()
        pages = parse_page_range(text, self._total)
        display = ", ".join(str(p + 1) for p in pages)
        preview_text = f"预览: {display}" if display else "预览: (无)"
        self._preview.setText(preview_text)
        self._selected_pages = pages

    def _validate_and_accept(self):
        text = self._range_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "错误", "请输入页码范围")
            return
        pages = parse_page_range(text, self._total)
        if not pages:
            QMessageBox.warning(self, "错误", "没有有效的页码范围")
            return
        self._selected_pages = pages
        self.accept()

    def selected_pages(self):
        return self._selected_pages
