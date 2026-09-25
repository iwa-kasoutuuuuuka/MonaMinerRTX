import sys
import time
import ctypes
from PySide6.QtCore import QObject, Signal, QTimer


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


class IdleTracker(QObject):
    """
    Tracks user keyboard and mouse idle time on Windows using GetLastInputInfo.
    Emits idle_changed(True) when idle threshold is reached, and idle_changed(False)
    when user resumes activity.
    """
    idle_changed = Signal(bool)
    idle_seconds_updated = Signal(int)

    def __init__(self, check_interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.idle_threshold_seconds = 300  # Default 5 minutes
        self.is_idle = False

        self._timer = QTimer(self)
        self._timer.setInterval(check_interval_ms)
        self._timer.timeout.connect(self._check_idle)

    def set_threshold_minutes(self, minutes: int):
        self.idle_threshold_seconds = max(30, int(minutes * 60))

    def start(self):
        self.enabled = True
        self.is_idle = False
        self._timer.start()

    def stop(self):
        self.enabled = False
        self._timer.stop()

    def get_idle_seconds(self) -> float:
        if sys.platform != "win32":
            return 0.0
        try:
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                # GetTickCount() returns milliseconds since system startup
                millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
                return max(0.0, millis / 1000.0)
        except Exception:
            pass
        return 0.0

    def _check_idle(self):
        if not self.enabled:
            return

        idle_sec = int(self.get_idle_seconds())
        self.idle_seconds_updated.emit(idle_sec)

        should_be_idle = idle_sec >= self.idle_threshold_seconds

        if should_be_idle != self.is_idle:
            self.is_idle = should_be_idle
            self.idle_changed.emit(self.is_idle)
