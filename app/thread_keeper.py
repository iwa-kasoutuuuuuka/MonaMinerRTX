"""
Keeps every started QThread alive until its thread has really ended.

PySide destroys the C++ QThread as soon as the last Python reference goes away. If that happens while
the thread still runs (for example a slot or the next timer tick replaces `self._worker` just as
run() is returning), Qt aborts the whole process with
"QThread: Destroyed while thread '' is still running" - the cause of the GUI dying every few days.

start_kept(thread) holds a strong reference in a registry that lives on the GUI thread. The reference
is released only from the GUI thread, after QThread.finished was delivered and wait() returned, so
no caller has to get the lifetime right any more.
"""
from PySide6.QtCore import QObject, QThread, Qt, SIGNAL, SLOT, Slot


class _ThreadKeeper(QObject):
    def __init__(self):
        super().__init__()
        self._alive = set()

    def start(self, thread: QThread):
        if thread not in self._alive:
            self._alive.add(thread)
            # QThread.finished by its C++ name: a subclass may shadow the Python attribute `finished`.
            # Queued: the slot must run on the keeper's (GUI) thread, never on the ending thread.
            QObject.connect(thread, SIGNAL("finished()"), self, SLOT("_on_finished()"), Qt.QueuedConnection)
        thread.start()

    @Slot()
    def _on_finished(self):
        thread = self.sender()
        if thread is None:
            return
        thread.wait()               # finished() is emitted slightly before the OS thread is gone
        self._alive.discard(thread)

    def wait_all(self, timeout_ms: int):
        for thread in list(self._alive):
            if thread.isRunning():
                thread.wait(timeout_ms)

    def count(self) -> int:
        return len(self._alive)


_keeper = None


def _get() -> _ThreadKeeper:
    global _keeper
    if _keeper is None:
        _keeper = _ThreadKeeper()
    return _keeper


def start_kept(thread: QThread):
    """Use instead of thread.start(). Call from the GUI thread."""
    _get().start(thread)


def wait_all(timeout_ms: int = 20000):
    """Blocks until every kept thread has ended (application shutdown)."""
    _get().wait_all(timeout_ms)


def kept_count() -> int:
    return _get().count()
