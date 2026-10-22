"""Run the heavy file work in separate processes so the window never stalls.

pypdf is pure Python and holds the GIL, so a background *thread* would still freeze the UI in
bursts. Worker processes don't share the GIL, and let several files be cleaned in parallel.
Nothing here imports tkinter, which keeps worker start-up fast.
"""

import multiprocessing
import os
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from .core import Result, process_file
from .metadata import MetaReport, inspect_file, make_thumbnail
from .presets import get_preset


def process_job(path, preset_name: str, output_dir) -> Result:
    return process_file(path, get_preset(preset_name), output_dir)


def inspect_job(path):
    """Returns (MetaReport, thumbnail image or None)."""
    report: MetaReport = inspect_file(path)
    return report, make_thumbnail(path)


def default_workers() -> int:
    # Leave a core free for the UI; cap so a big batch doesn't exhaust memory on large PDFs.
    return max(1, min(4, (os.cpu_count() or 2) - 1))


class WorkerPool:
    """A lazily started process pool that recovers if a worker dies."""

    def __init__(self, max_workers=None):
        self.max_workers = max_workers or default_workers()
        self._executor = None
        self._lock = threading.Lock()  # the UI and the dispatcher thread both submit

    def _start(self):
        # "spawn" is the only start method that is safe alongside Tk, and works in frozen apps.
        self._executor = ProcessPoolExecutor(self.max_workers, mp_context=multiprocessing.get_context("spawn"))

    def submit(self, fn, *args) -> Future:
        with self._lock:
            if self._executor is None:
                self._start()
            try:
                return self._executor.submit(fn, *args)
            except (BrokenProcessPool, RuntimeError):
                self._start()
                return self._executor.submit(fn, *args)

    def shutdown(self):
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is None:
            return
        procs = list(getattr(executor, "_processes", {}).values())
        executor.shutdown(wait=False, cancel_futures=True)
        for proc in procs:  # don't leave a half-finished PDF job running after the window closes
            try:
                proc.terminate()
            except Exception:
                pass
