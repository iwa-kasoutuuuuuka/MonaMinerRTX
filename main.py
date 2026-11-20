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
        from PySide6.QtCore import QThread
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("not on the GUI thread")   # widgets must not be created from a worker thread
        QMessageBox.critical(
            None,
            "予期しないエラー",
            f"アプリケーションでエラーが発生しました:\n\n{exc_value}\n\n詳細はログまたはコンソールを確認してください。"
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

def _install_fatal_log():
    """Writes hard crashes to logs/fatal.log: Qt fatal messages (which abort the process without a
    Python traceback) and native faults, each with the Python stacks of all threads."""
    import datetime
    import faulthandler
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
            else os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "fatal.log"), "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    faulthandler.enable(file=log_file, all_threads=True)

    def on_qt_message(msg_type, context, message):
        if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            log_file.write(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] Qt {msg_type.name}: {message}\n")
            if msg_type == QtMsgType.QtFatalMsg:
                faulthandler.dump_traceback(file=log_file, all_threads=True)
            log_file.flush()
        if sys.stderr:
            sys.stderr.write(message + "\n")

    qInstallMessageHandler(on_qt_message)
    main._fatal_log = (log_file, on_qt_message)   # keep both alive for the life of the process


def main():
    sys.excepthook = handle_exception
    _install_fatal_log()

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

    # --solo: one-click solo mining (starts the bundled node, waits for sync, starts mining)
    window = MainWindow(solo_autostart="--solo" in sys.argv[1:])
    if os.path.exists(icon_path):
        from PySide6.QtGui import QIcon
        window.setWindowIcon(QIcon(icon_path))
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
