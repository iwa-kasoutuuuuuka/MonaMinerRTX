import sys
import os

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure current directory is on PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from app.ui.main_window import MainWindow

def handle_exception(exc_type, exc_value, exc_traceback):
    import traceback
    err_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    sys.stderr.write(f"[FATAL ERROR]\n{err_str}\n")
    try:
        QMessageBox.critical(
            None,
            "予期しないエラー",
            f"アプリケーションでエラーが発生しました:\n\n{exc_value}\n\n詳細はログまたはコンソールを確認してください。"
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

def main():
    sys.excepthook = handle_exception

    # Enable high-DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("MonaMiner RTX")
    app.setOrganizationName("MonaCoinCommunity")

    # Set application icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
    if os.path.exists(icon_path):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    if os.path.exists(icon_path):
        from PySide6.QtGui import QIcon
        window.setWindowIcon(QIcon(icon_path))
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
