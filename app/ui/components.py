from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QTextEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor, QColor

class MetricCard(QFrame):
    def __init__(self, label: str, default_val: str = "--", unit: str = ""):
        super().__init__()
        self.setObjectName("card")
        self.unit = unit
        self.setMinimumHeight(64)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        self.lbl_title = QLabel(label)
        self.lbl_title.setObjectName("metric_label")
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_title)

        self.lbl_val = QLabel(f"{default_val} {unit}".strip())
        self.lbl_val.setObjectName("metric_val")
        self.lbl_val.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_val)

    def set_value(self, val):
        self.lbl_val.setText(f"{val} {self.unit}".strip())

class ModeCard(QPushButton):
    selected = Signal(str)

    def __init__(self, mode_key: str, title: str, badge: str, description: str, est_hr: str):
        super().__init__()
        self.mode_key = mode_key
        self.setCheckable(True)
        self.setProperty("class", "mode-btn")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(105)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)
        self.lbl_title = QLabel(title)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #f8fafc;")
        header_layout.addWidget(self.lbl_title, stretch=1)

        self.lbl_badge = QLabel(badge)
        self.lbl_badge.setStyleSheet("background-color: #3b82f6; color: white; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold; white-space: nowrap;")
        header_layout.addWidget(self.lbl_badge, alignment=Qt.AlignRight | Qt.AlignTop)
        layout.addLayout(header_layout)

        self.lbl_desc = QLabel(description)
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color: #94a3b8; font-size: 11px; line-height: 1.3;")
        layout.addWidget(self.lbl_desc)

        layout.addStretch()

        footer_layout = QHBoxLayout()
        lbl_hr_tag = QLabel(f"予想: <b style='color:#38bdf8;'>{est_hr}</b>")
        lbl_hr_tag.setWordWrap(True)
        lbl_hr_tag.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        footer_layout.addWidget(lbl_hr_tag)
        layout.addLayout(footer_layout)

        self.clicked.connect(lambda: self.selected.emit(self.mode_key))

class LogConsole(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("💻 マイニング動作ログ / Stratum出力")
        title.setStyleSheet("font-weight: bold; color: #94a3b8; font-size: 12px;")
        header.addWidget(title)
        header.addStretch()

        btn_clear = QPushButton("ログ消去")
        btn_clear.setStyleSheet("background-color: #334155; border: none; border-radius: 4px; padding: 3px 8px; font-size: 11px;")
        btn_clear.clicked.connect(self.clear_log)
        header.addWidget(btn_clear)
        layout.addLayout(header)

        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("log_view")
        self.text_edit.setReadOnly(True)
        self.text_edit.setMinimumHeight(130)
        layout.addWidget(self.text_edit)

    def append_log(self, text: str, level: str = "info"):
        color_map = {
            "info": "#94a3b8",
            "success": "#34d399",
            "warn": "#fbbf24",
            "error": "#f87171"
        }
        color = color_map.get(level, "#94a3b8")
        html_msg = f"<span style='color: {color};'>{text}</span>"
        self.text_edit.append(html_msg)
        self.text_edit.moveCursor(QTextCursor.End)

    def clear_log(self):
        self.text_edit.clear()
