"""
Regression test for the GUI crash "QThread: Destroyed while thread '' is still running":
    python -m unittest tests.test_thread_keeper -v

Each worker announces its result at the very end of run(); the slot then drops the only reference the
caller holds while the thread is still winding down. Without thread_keeper.start_kept() this aborts the
process within a few iterations (Qt fatal, exit code 0xC0000409).
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QThread, Signal

from app import thread_keeper


class _Worker(QThread):
    finished = Signal(int)   # worst case: shadows QThread.finished, like the old WalletFetchWorker

    def __init__(self, n):
        super().__init__()
        self.n = n

    def run(self):
        self.finished.emit(self.n)


class TestThreadKeeper(unittest.TestCase):
    def test_dropping_the_last_reference_in_a_result_slot_is_safe(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        holder = {}
        done = []

        def on_result(n):
            done.append(n)
            holder.pop("worker", None)        # the caller forgets the thread while it is still ending

        total = 1500
        for i in range(total):
            worker = _Worker(i)
            worker.finished.connect(on_result)
            holder["worker"] = worker
            thread_keeper.start_kept(worker)
            del worker
            deadline = time.monotonic() + 10
            while len(done) <= i and time.monotonic() < deadline:
                app.processEvents()
        self.assertEqual(len(done), total)

        deadline = time.monotonic() + 10
        while thread_keeper.kept_count() and time.monotonic() < deadline:
            app.processEvents()
        self.assertEqual(thread_keeper.kept_count(), 0)   # nothing is kept (leaked) after the threads ended


if __name__ == "__main__":
    unittest.main()
