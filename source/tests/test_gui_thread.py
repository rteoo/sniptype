"""Direct tests for the single-Tk-root marshaling thread (``gui_thread``).

``gui_thread.py`` owns the process's only ``tk.Tk()`` root on a dedicated
thread; worker threads reach it only through ``call`` (blocking, returns the
result, re-raises errors) and ``submit`` (fire-and-forget). These tests hammer
the marshaling contract adversarially: concurrent callers must not cross wires,
a raising callable must re-raise in the *caller* with a usable traceback, a
raising ``submit`` must not kill the pump, and every after-shutdown path must be
a defined refusal rather than a deadlock.

Determinism rules (mirrors the suite): thread coordination uses
``threading.Event``/``join`` with timeouts, never bare sleeps, and every GUI
thread is torn down in ``tearDown`` so a wedged test fails the runner instead of
hanging it. The real-Tk classes are skipped where no display is available and on
macOS, where the worker-thread root is not something AppKit permits (issue #24),
exactly as ``test_manager_gui_smoke`` decides it.
"""

import os
import sys
import threading
import traceback
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui_thread as gt
from gui_thread import GuiThread
from platform_support import IS_MAC


TK_AVAILABLE = False
TK_SKIP_REASON = "Tk display not available"

if IS_MAC:
    TK_SKIP_REASON = "macOS requires AppKit on the main thread; the Tk root runs on a worker thread"
else:
    try:
        _probe = GuiThread()
        _probe.ensure_started()
        _probe.stop()
        TK_AVAILABLE = True
    except Exception:
        pass


def run_in_daemon(target, timeout=5.0):
    """Run ``target`` in a daemon thread and join with a timeout.

    Returns ``(thread, holder)`` where ``holder`` has ``"result"`` or ``"error"``.
    A still-alive thread after the join is the observable signature of a deadlock,
    which the caller asserts against so a hang becomes a failure, never a wedge.
    """
    holder = {}

    def runner():
        try:
            holder["result"] = target()
        except BaseException as exc:  # noqa: BLE001 - record everything a caller might see
            holder["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout)
    return thread, holder


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class GuiThreadCallTests(unittest.TestCase):
    def setUp(self):
        self.gui = GuiThread()
        self.gui.ensure_started()
        # Events a test uses to occupy the single GUI thread; always released in
        # tearDown so a blocked pump can drain the teardown sentinel and join.
        self._release_events = []

    def tearDown(self):
        for event in self._release_events:
            event.set()
        self.gui.stop()

    def _blocker(self):
        event = threading.Event()
        self._release_events.append(event)
        return event

    # -- lifecycle --------------------------------------------------------
    def test_ensure_started_is_idempotent(self):
        self.assertTrue(self.gui.running)
        self.assertIsNotNone(self.gui.root)
        first_thread = self.gui._thread
        self.assertTrue(self.gui.ensure_started())
        self.assertIs(self.gui._thread, first_thread, "a second start must not spawn a new thread")

    # -- call -------------------------------------------------------------
    def test_call_runs_on_the_gui_thread_and_returns_the_value(self):
        caller = threading.current_thread()
        ran_on = self.gui.call(lambda _root: threading.current_thread(), timeout=10)
        self.assertIsNot(ran_on, caller)
        self.assertIs(ran_on, self.gui._thread)

    def test_call_receives_the_shared_root(self):
        self.assertIs(self.gui.call(lambda root: root, timeout=10), self.gui.root)

    def test_call_propagates_the_exception_with_a_usable_traceback(self):
        def boom(_root):
            raise ValueError("kaboom-from-gui")

        with self.assertRaises(ValueError) as ctx:
            self.gui.call(boom, timeout=10)

        self.assertIn("kaboom-from-gui", str(ctx.exception))
        rendered = "".join(
            traceback.format_exception(type(ctx.exception), ctx.exception, ctx.exception.__traceback__)
        )
        # The traceback must still point at the frame that actually raised, on the
        # GUI thread, not merely at the re-raise site in call().
        self.assertIn("boom", rendered)
        self.assertIn("kaboom-from-gui", rendered)

    def test_call_error_does_not_kill_the_pump(self):
        with self.assertRaises(RuntimeError):
            self.gui.call(self._raise_runtime, timeout=10)
        # The very next call must still be served.
        self.assertEqual(self.gui.call(lambda _root: "alive", timeout=10), "alive")

    @staticmethod
    def _raise_runtime(_root):
        raise RuntimeError("boom")

    def test_concurrent_calls_do_not_cross_wires(self):
        """Each caller owns a private result box; results must never swap."""
        worker_count = 24
        start = threading.Barrier(worker_count + 1)
        results = {}
        errors = {}

        def worker(index):
            start.wait(10)
            try:
                # A distinct transform per caller: a shared box would return
                # some other worker's doubled value.
                results[index] = self.gui.call(lambda _root, n=index: (n, n * 7), timeout=15)
            except BaseException as exc:  # noqa: BLE001
                errors[index] = exc

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(worker_count)]
        for thread in threads:
            thread.start()
        start.wait(10)
        for thread in threads:
            thread.join(15)

        self.assertEqual(errors, {})
        self.assertEqual(results, {index: (index, index * 7) for index in range(worker_count)})

    def test_call_times_out_when_the_gui_thread_is_busy(self):
        blocker_running = threading.Event()
        release = self._blocker()

        def occupy(_root):
            blocker_running.set()
            release.wait(10)

        # Occupy the single GUI thread, then a call with a short timeout must
        # raise rather than block the caller forever.
        self.gui.submit(occupy)
        self.assertTrue(blocker_running.wait(10), "blocker never started")

        with self.assertRaises(TimeoutError):
            self.gui.call(lambda _root: "unreachable", timeout=0.2)

        # Freeing the pump lets it recover and serve the next call.
        release.set()
        self.assertEqual(self.gui.call(lambda _root: "recovered", timeout=10), "recovered")

    # -- submit -----------------------------------------------------------
    def test_submit_does_not_block_and_runs(self):
        done = threading.Event()
        self.gui.submit(lambda _root: done.set())
        self.assertTrue(done.wait(10))

    def test_submit_error_does_not_kill_the_pump(self):
        def boom(_root):
            raise RuntimeError("swallowed")

        self.gui.submit(boom)
        # A second submit and a call must both still run after the failure.
        done = threading.Event()
        self.gui.submit(lambda _root: done.set())
        self.assertTrue(done.wait(10), "pump stopped serving submit after a raising task")
        self.assertEqual(self.gui.call(lambda _root: "alive", timeout=10), "alive")

    def test_submit_error_is_logged_when_a_logger_is_present(self):
        logger = mock.Mock()
        gui = GuiThread(logger=logger)
        gui.ensure_started()
        self.addCleanup(gui.stop)

        def boom(_root):
            raise RuntimeError("logged-please")

        gui.submit(boom)
        # Serialize behind the failing task: once this returns the submit ran.
        self.assertEqual(gui.call(lambda _root: "sync", timeout=10), "sync")
        logger.error.assert_called()

    # -- reentrancy -------------------------------------------------------
    def test_call_from_the_gui_thread_runs_inline_without_deadlock(self):
        def outer(_root):
            return self.gui.call(lambda _inner: "inner-value", timeout=10)

        thread, holder = run_in_daemon(lambda: self.gui.call(outer, timeout=10))
        self.assertFalse(thread.is_alive(), "reentrant call deadlocked")
        self.assertEqual(holder.get("result"), "inner-value")

    def test_submit_from_the_gui_thread_runs_inline(self):
        marker = threading.Event()

        def outer(_root):
            self.gui.submit(lambda _inner: marker.set())
            # submit from the GUI thread runs synchronously, so the marker is
            # already set by the time outer returns.
            return marker.is_set()

        self.assertTrue(self.gui.call(outer, timeout=10))


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class GuiThreadShutdownTests(unittest.TestCase):
    def setUp(self):
        self.gui = GuiThread()
        self.gui.ensure_started()

    def tearDown(self):
        self.gui.stop()

    def test_stop_joins_and_marks_not_running(self):
        self.gui.stop()
        self.assertFalse(self.gui.running)

    def test_stop_wakes_a_caller_whose_work_never_ran(self):
        """A call still queued when the loop exits must fail its caller instead
        of leaving it blocked forever on ``done``."""
        self.gui.stop()

        box = {}
        done = threading.Event()
        self.gui._queue.put((lambda _root: "never runs", box, done))

        self.gui.stop()  # second stop drains and fails the stranded item
        self.assertTrue(done.is_set(), "stranded caller was never woken")
        self.assertIsInstance(box.get("error"), RuntimeError)

    def test_abnormal_loop_exit_fails_stranded_callers(self):
        """A GUI loop that dies without stop() must also wake queued callers: a
        stranded one blocks forever in ``call(timeout=None)`` while holding the
        dialog lock, refusing every later dialog."""
        gui = GuiThread(logger=mock.Mock())
        box = {}
        done = threading.Event()
        gui._queue.put((lambda _root: "never runs", box, done))

        with mock.patch.object(gui, "_pump", side_effect=RuntimeError("boom")):
            gui.ensure_started()
            gui._thread.join(10)

        self.assertFalse(gui._thread.is_alive())
        self.assertTrue(done.is_set(), "stranded caller was never woken")
        self.assertIsInstance(box.get("error"), RuntimeError)

    def test_call_after_stop_refuses_instead_of_deadlocking(self):
        self.gui.stop()
        thread, holder = run_in_daemon(lambda: self.gui.call(lambda _root: "x", timeout=10))
        self.assertFalse(thread.is_alive(), "call after stop deadlocked")
        self.assertIsInstance(holder.get("error"), RuntimeError)

    def test_submit_after_stop_refuses_instead_of_deadlocking(self):
        self.gui.stop()
        thread, holder = run_in_daemon(lambda: self.gui.submit(lambda _root: None))
        self.assertFalse(thread.is_alive(), "submit after stop deadlocked")
        self.assertIsInstance(holder.get("error"), RuntimeError)


class GuiThreadHeadlessTests(unittest.TestCase):
    """Paths that never need a real display, so they run even on headless CI."""

    def test_start_error_is_reraised_and_thread_dies(self):
        gui = GuiThread()
        self.addCleanup(gui.stop)
        with mock.patch.object(gt.tk, "Tk", side_effect=RuntimeError("no display")):
            with self.assertRaises(RuntimeError) as ctx:
                gui.ensure_started()
        self.assertIn("no display", str(ctx.exception))
        # A failed start must not leave a live thread pretending to be a root.
        if gui._thread is not None:
            gui._thread.join(5)
            self.assertFalse(gui._thread.is_alive())
        self.assertFalse(gui.running)

    def test_calls_are_refused_once_shutting_down_without_a_root(self):
        """stop() before any start sets the shutdown flag; later call/submit must
        refuse promptly (no Tk ever created), not hang."""
        gui = GuiThread()
        gui.stop()  # no thread yet: just flips _stopping and drains

        call_thread, call_holder = run_in_daemon(lambda: gui.call(lambda _root: "x", timeout=5))
        submit_thread, submit_holder = run_in_daemon(lambda: gui.submit(lambda _root: None))

        self.assertFalse(call_thread.is_alive(), "call after shutdown deadlocked")
        self.assertFalse(submit_thread.is_alive(), "submit after shutdown deadlocked")
        self.assertIsInstance(call_holder.get("error"), RuntimeError)
        self.assertIsInstance(submit_holder.get("error"), RuntimeError)
        self.assertFalse(gui.running)

    def test_stop_with_no_thread_wakes_a_manually_queued_caller(self):
        gui = GuiThread()
        box = {}
        done = threading.Event()
        gui._queue.put((lambda _root: "never", box, done))
        gui.stop()
        self.assertTrue(done.is_set())
        self.assertIsInstance(box.get("error"), RuntimeError)


if __name__ == "__main__":
    unittest.main()
