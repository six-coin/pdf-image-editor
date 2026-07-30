from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QDialogButtonBox
)


class ReferenceDialog(QDialog):
    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle("参考线设置")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        self._spins = {}

        for key, label_text in [
            ("left_cm", "左边距 (cm)"),
            ("top_cm", "上边距 (cm)"),
            ("right_cm", "右边距 (cm)"),
            ("bottom_cm", "下边距 (cm)"),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label_text))
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setValue(values.get(key, 1.0))
            spin.setSuffix(" cm")
            row.addWidget(spin)
            layout.addLayout(row)
            self._spins[key] = spin

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return {k: spin.value() for k, spin in self._spins.items()}
