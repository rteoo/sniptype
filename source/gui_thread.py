"""Single Tk root owned by one dedicated GUI thread.

Tkinter is not thread-safe and a Tcl interpreter belongs to the thread that
created it, so the whole app shares one hidden root created here. Worker
threads never touch Tk directly: they hand a callable to ``call`` (blocking,
returns the result) or ``submit`` (fire-and-forget) and an ``after``-driven
pump runs it on the GUI thread.

The keyboard listener thread must never call into this module; dialog
marshaling belongs to the expansion worker path only.
"""

import queue
import threading

import tkinter as tk


# Pump cadence. Low enough that a dialog feels instant, high enough that an
# idle app is not waking the Tcl interpreter constantly.
PUMP_INTERVAL_MS = 40

_START_TIMEOUT_SECONDS = 10.0


class GuiThread:
    """Owns the process-wide Tk root and marshals work onto its thread."""

    def __init__(self, logger=None):
        self._logger = logger
        self._queue = queue.Queue()
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._thread = None
        self._start_error = None
        self._stopping = False
        self.root = None

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def ensure_started(self, timeout=_START_TIMEOUT_SECONDS):
        """Start the GUI thread if needed and block until the root exists."""
        with self._lock:
            if self._stopping:
                raise RuntimeError("GUI thread is shutting down")
            if self._thread is None or not self._thread.is_alive():
                self._ready.clear()
                self._start_error = None
                self._thread = threading.Thread(
                    target=self._run, name="tk-gui", daemon=True
                )
                self._thread.start()

        if not self._ready.wait(timeout):
            raise RuntimeError("Tk GUI thread did not become ready in time")
        if self._start_error is not None:
            raise self._start_error
        return True

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except Exception as exc:
            self._start_error = exc
            self._ready.set()
            return

        self._ready.set()
        try:
            self._pump()
            self.root.mainloop()
        except Exception as exc:
            self._log(f"Loop da thread de GUI encerrado com erro: {exc}")
        finally:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    def stop(self, timeout=5.0):
        """Tear the root down and join the GUI thread."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stopping = True
                self._fail_pending()
                return
            self._stopping = True
            thread = self._thread

        def _teardown(root):
            # destroy(), not quit(): mainloop exits when the window count hits
            # zero, which is deterministic. quit() relies on _tkinter's quit
            # flag, which proved unreliable once the process has had earlier
            # Tk interpreters (observed on 3.14: stop() hung until the join
            # timeout while the pump kept ticking).
            root.destroy()

        # Cannot use call(): ensure_started() refuses once _stopping is set.
        self._queue.put((_teardown, None, None))
        thread.join(timeout)
        self._fail_pending()

    def _fail_pending(self):
        """Wake workers whose queued calls will never run.

        Items still queued after the loop exits would otherwise leave their
        callers blocked forever in ``call(timeout=None)`` — ``done`` is only
        set by the GUI thread that no longer exists.
        """
        while True:
            try:
                _func, box, done = self._queue.get_nowait()
            except queue.Empty:
                return
            if box is not None:
                box["error"] = RuntimeError(
                    "GUI thread stopped before the call could run"
                )
            if done is not None:
                done.set()

    # -----------------------------------------------------------------
    # Marshaling
    # -----------------------------------------------------------------

    def call(self, func, timeout=None):
        """Run ``func(root)`` on the GUI thread and return its result.

        Blocks the calling thread until ``func`` returns, re-raising whatever
        it raised. ``timeout=None`` waits indefinitely, which is what a modal
        dialog needs — the user decides when it closes.
        """
        self.ensure_started()
        if threading.current_thread() is self._thread:
            return func(self.root)

        box = {}
        done = threading.Event()
        self._queue.put((func, box, done))
        if not done.wait(timeout):
            raise TimeoutError("GUI call did not complete in time")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def submit(self, func):
        """Queue ``func(root)`` on the GUI thread without waiting for it."""
        self.ensure_started()
        if threading.current_thread() is self._thread:
            func(self.root)
            return
        self._queue.put((func, None, None))

    def _pump(self):
        if self.root is None:
            return
        # Reschedule before draining, and unconditionally: a queued callable
        # may open a modal dialog and block here inside a nested event loop,
        # and the next tick is what keeps later requests (and the manager
        # window) responsive. Gating this on the stop flag would also risk
        # dropping the quit sentinel itself. The loop dies with the root.
        try:
            self.root.after(PUMP_INTERVAL_MS, self._pump)
        except Exception:
            return

        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            self._invoke(item)

    def _invoke(self, item):
        func, box, done = item
        try:
            value = func(self.root)
            if box is not None:
                box["value"] = value
        except Exception as exc:
            if box is None:
                self._log(f"Erro em tarefa de GUI: {exc}")
            else:
                box["error"] = exc
        finally:
            if done is not None:
                done.set()

    def _log(self, message):
        if self._logger is not None:
            try:
                self._logger.error(message)
                return
            except Exception:
                pass
        print(message)
