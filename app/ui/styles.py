MAIN_STYLE = """
QMainWindow, QWidget {
    background-color: #11141a;
    color: #f3f4f6;
    font-family: 'Segoe UI', 'Meiryo', sans-serif;
    font-size: 13px;
}

QFrame#card {
    background-color: #1a202c;
    border: 1px solid #2d3748;
    border-radius: 10px;
    padding: 12px;
}

QFrame#banner {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a202c, stop:1 #2d3748);
    border: 1px solid #4a5568;
    border-radius: 12px;
    padding: 14px;
}

QLabel#title {
    font-size: 20px;
    font-weight: bold;
    color: #fbbf24; /* Monacoin Gold */
}

QLabel#subtitle {
    font-size: 12px;
    color: #94a3b8;
}

QLabel#metric_val {
    font-size: 22px;
    font-weight: bold;
    color: #38bdf8;
}

QLabel#metric_label {
    font-size: 11px;
    color: #94a3b8;
    text-transform: uppercase;
}

QLabel#hashrate_huge {
    font-size: 40px;
    font-weight: bold;
    color: #10b981; /* Emerald Active */
}

/* Mode Selection Buttons */
QPushButton.mode-btn {
    background-color: #1e293b;
    border: 2px solid #334155;
    border-radius: 10px;
    padding: 12px;
    text-align: left;
    color: #e2e8f0;
}

QPushButton.mode-btn:hover {
    background-color: #334155;
    border-color: #64748b;
}

QPushButton.mode-btn[checked="true"] {
    background-color: #1e1b4b;
    border-color: #818cf8;
}

/* Primary Action Button (Start / Stop) */
QPushButton#start_btn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
    color: #ffffff;
    font-size: 18px;
    font-weight: bold;
    border-radius: 12px;
    padding: 14px;
    border: none;
}

QPushButton#start_btn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399, stop:1 #10b981);
}

QPushButton#stop_btn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #dc2626);
    color: #ffffff;
    font-size: 18px;
    font-weight: bold;
    border-radius: 12px;
    padding: 14px;
    border: none;
}

QPushButton#stop_btn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f87171, stop:1 #ef4444);
}

/* Inputs & Form controls */
QLineEdit, QComboBox {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 8px 12px;
    color: #f8fafc;
    font-size: 13px;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #38bdf8;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

/* Terminal Log View */
QTextEdit#log_view {
    background-color: #090d16;
    border: 1px solid #1e293b;
    border-radius: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    color: #cbd5e1;
    padding: 8px;
}

/* Badges */
QLabel#badge_admin_ok {
    background-color: #064e3b;
    color: #34d399;
    border: 1px solid #059669;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: bold;
}

QLabel#badge_admin_no {
    background-color: #3b2806;
    color: #fbbf24;
    border: 1px solid #d97706;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
}

QLabel#badge_rtx {
    background-color: #14532d;
    color: #86efac;
    border: 1px solid #22c55e;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: bold;
}
"""
