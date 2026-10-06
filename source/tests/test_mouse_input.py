"""Click counters, native packet parsing and resource ownership; no live clicks."""

import ctypes
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import mouse_input as mi


class MouseActivityMonitorTests(unittest.TestCase):
    def setUp(self):
        self.monitor = mi.MouseActivityMonitor()

    def test_construction_does_not_start_input_capture(self):
        self.assertEqual(0, self.monitor.generation)
        self.assertIsNone(self.monitor._thread)
        self.assertIsNone(self.monitor._listener)

    def test_only_button_down_counts(self):
        self.monitor._on_click(0, 0, object(), False)
        self.assertEqual(0, self.monitor.generation)
        self.monitor._on_click(0, 0, object(), True)
        self.assertEqual(1, self.monitor.generation)

    def test_observer_failure_cannot_report_a_valid_generation(self):
        self.monitor._error = OSError("unavailable")
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            _ = self.monitor.generation

    def test_off_windows_uses_the_existing_pynput_click_listener(self):
        from pynput import mouse

        listener = mock.Mock()
        listener.is_alive.return_value = True
        with mock.patch.object(mi, "IS_WINDOWS", False), \
                mock.patch.object(mouse, "Listener", return_value=listener) as factory, \
                mock.patch.object(mi, "_windows_api") as api:
            try:
                self.monitor.start()
                factory.assert_called_once_with(on_click=self.monitor._on_click)
                listener.start.assert_called_once_with()
                api.assert_not_called()
                listener.is_alive.return_value = False
                with self.assertRaisesRegex(RuntimeError, "capture stopped"):
                    _ = self.monitor.generation
            finally:
                self.monitor.stop()
        listener.stop.assert_called_once_with()
        listener.join.assert_called_once_with(3)

    def test_stop_before_start_is_safe(self):
        self.monitor.stop()
        self.monitor.stop()


@unittest.skipUnless(mi.IS_WINDOWS, "Win32 native packet layout")
class WindowsMouseInputTests(unittest.TestCase):
    def setUp(self):
        self.monitor = mi.MouseActivityMonitor()
        self.user32 = mock.Mock()
        self.monitor._user32 = self.user32

    def _deliver_packet(self, flags, packet_type=0):
        def read(_handle, command, buffer, size, header_size):
            self.assertEqual(mi.RID_INPUT, command)
            self.assertEqual(ctypes.sizeof(mi.RAWINPUTHEADER), header_size)
            packet = ctypes.cast(buffer, ctypes.POINTER(mi.RAWMOUSEINPUT)).contents
            packet.header.dwType = packet_type
            packet.header.dwSize = ctypes.sizeof(mi.RAWMOUSEINPUT)
            packet.mouse.buttonUnion.buttons.flags = flags
            return ctypes.sizeof(mi.RAWMOUSEINPUT)

        self.user32.GetRawInputData.side_effect = read
        self.monitor._window_proc(100, mi.WM_INPUT, 0, 200)

    def test_each_mouse_button_down_invalidates_the_target(self):
        for index, flag in enumerate((0x0001, 0x0004, 0x0010, 0x0040, 0x0100), 1):
            with self.subTest(flag=flag):
                self._deliver_packet(flag)
                self.assertEqual(index, self.monitor.generation)
        self.assertEqual(5, self.user32.DefWindowProcW.call_count)

    def test_mouse_movement_release_and_wheel_do_not_invalidate(self):
        for flag in (0, 0x0002, 0x0008, 0x0020, 0x0080, 0x0200, 0x0400, 0x0800):
            with self.subTest(flag=flag):
                self._deliver_packet(flag)
                self.assertEqual(0, self.monitor.generation)

    def test_bad_packet_fails_closed_and_still_runs_native_cleanup(self):
        self._deliver_packet(1, packet_type=1)
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            _ = self.monitor.generation
        self.user32.DefWindowProcW.assert_called_once_with(100, mi.WM_INPUT, 0, 200)

    def test_read_failure_fails_closed_and_still_runs_native_cleanup(self):
        self.user32.GetRawInputData.return_value = 0xFFFFFFFF
        self.monitor._window_proc(100, mi.WM_INPUT, 0, 200)
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            _ = self.monitor.generation
        self.user32.DefWindowProcW.assert_called_once_with(100, mi.WM_INPUT, 0, 200)

    def test_message_window_shutdown_releases_the_message_loop(self):
        self.monitor._hwnd = 100
        self.monitor._window_proc(100, mi.WM_CLOSE, 0, 0)
        self.user32.DestroyWindow.assert_called_once_with(100)
        self.monitor._window_proc(100, mi.WM_DESTROY, 0, 0)
        self.assertIsNone(self.monitor._hwnd)
        self.user32.PostQuitMessage.assert_called_once_with(0)

    def _run_native_loop(self, registration_ok=True, message_error=False):
        registrations = []

        def register(pointer, count, size):
            device = ctypes.cast(pointer, ctypes.POINTER(mi.RAWINPUTDEVICE)).contents
            registrations.append((device.usUsagePage, device.usUsage,
                                  device.dwFlags, device.hwndTarget))
            self.assertEqual(1, count)
            self.assertEqual(ctypes.sizeof(mi.RAWINPUTDEVICE), size)
            return registration_ok or device.dwFlags == mi.RIDEV_REMOVE

        def message(*_args):
            if message_error:
                return -1
            self.monitor._stopping.set()
            return 0

        self.user32.CreateWindowExW.return_value = 100
        self.user32.RegisterRawInputDevices.side_effect = register
        self.user32.GetMessageW.side_effect = message
        kernel32 = mock.Mock()
        kernel32.GetModuleHandleW.return_value = 200
        with mock.patch.object(mi, "_windows_api", return_value=(self.user32, kernel32)):
            self.monitor._run_windows()
        return registrations

    def test_registration_uses_background_mouse_input_and_is_removed_on_stop(self):
        registrations = self._run_native_loop()

        self.assertEqual([(1, 2, mi.RIDEV_INPUTSINK, 100),
                          (1, 2, mi.RIDEV_REMOVE, None)], registrations)
        self.assertEqual(-3, self.user32.CreateWindowExW.call_args.args[8])
        self.user32.DestroyWindow.assert_called_once_with(100)
        self.user32.UnregisterClassW.assert_called_once()
        self.assertTrue(self.monitor._ready.is_set())
        self.assertEqual(0, self.monitor.generation)

    def test_failed_registration_cleans_up_the_window_and_class(self):
        self._run_native_loop(registration_ok=False)

        self.user32.GetMessageW.assert_not_called()
        self.user32.DestroyWindow.assert_called_once_with(100)
        self.user32.UnregisterClassW.assert_called_once()
        self.assertTrue(self.monitor._ready.is_set())
        with self.assertRaises(RuntimeError):
            _ = self.monitor.generation

    def test_message_loop_failure_removes_registration_and_fails_closed(self):
        registrations = self._run_native_loop(message_error=True)

        self.assertEqual(mi.RIDEV_REMOVE, registrations[-1][2])
        self.user32.DestroyWindow.assert_called_once_with(100)
        self.user32.UnregisterClassW.assert_called_once()
        with self.assertRaises(RuntimeError):
            _ = self.monitor.generation


if __name__ == "__main__":
    unittest.main()
