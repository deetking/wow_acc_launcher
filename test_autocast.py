import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class Harness:
    toggle_autocast = main.Launcher.toggle_autocast
    autocast_tick = main.Launcher.autocast_tick
    stop_autocast = main.Launcher.stop_autocast
    release_autocast_key = main.Launcher.release_autocast_key
    set_anti_afk = main.Launcher.set_anti_afk
    resume_anti_afk = main.Launcher.resume_anti_afk
    toggle_all_autocasts = main.Launcher.toggle_all_autocasts
    poll_autocast_hotkey = main.Launcher.poll_autocast_hotkey

    def __init__(self):
        self.busy = False
        self.wow_processes = {}
        self.autocast_sessions = {"a": {
            "handle": 900, "pid": 42, "hwnd": 100,
            "slots": [{"key": 51, "interval": 500, "timer": None, "release_timer": None, "pressed": False}],
        }}
        self.after = Mock(side_effect=lambda delay, callback: f"timer-{delay}")
        self.after_cancel = Mock()
        self.render_accounts = Mock()
        self.status = Mock()


class AutocastTests(unittest.TestCase):
    def setUp(self):
        self.app = Harness()
        self.kernel = Mock()
        def exit_code(handle, pointer):
            pointer._obj.value = 259
            return True
        self.kernel.GetExitCodeProcess.side_effect = exit_code
        self.native = patch.object(main.ctypes, "windll", SimpleNamespace(kernel32=self.kernel))
        self.native.start()
        self.addCleanup(self.native.stop)
        self.window = patch.object(main, "visible_window_pid", return_value=42)
        self.window.start()
        self.addCleanup(self.window.stop)
        self.identity = patch.object(main, "window_identity", return_value=(42, 7, "GxWindowClass"))
        self.identity_mock = self.identity.start()
        self.addCleanup(self.identity.stop)
        self.original_post = main.post_autocast_key
        self.post = patch.object(main, "post_autocast_key")
        self.send = self.post.start()
        self.addCleanup(self.post.stop)

    def test_keys_and_rejection(self):
        self.assertEqual(main.autocast_key("3"), 51)
        self.assertEqual(main.autocast_key("f12"), 123)
        with self.assertRaises(ValueError):
            main.autocast_key("ctrl+3")

    def test_native_message_flags_and_pointer_sized_window(self):
        user32 = SimpleNamespace(MapVirtualKeyW=Mock(return_value=0x4B), PostMessageW=Mock(return_value=True))
        hwnd = 0x100000123
        with patch.object(main.ctypes, "windll", SimpleNamespace(user32=user32)):
            self.original_post(hwnd, 0x25)
            self.original_post(hwnd, 0x25, released=True)
        down, up = user32.PostMessageW.call_args_list
        self.assertEqual(down.args, (hwnd, 0x100, 0x25, 1 | (0x4B << 16) | (1 << 24)))
        self.assertEqual(up.args[1], 0x101)
        self.assertEqual(up.args[3], down.args[3] | (1 << 30) | (1 << 31))

    def test_blocked_window_input_explains_administrator_mismatch(self):
        user32 = SimpleNamespace(MapVirtualKeyW=Mock(return_value=4), PostMessageW=Mock(return_value=False))
        kernel32 = SimpleNamespace(GetLastError=Mock(return_value=5))
        with patch.object(main.ctypes, "windll", SimpleNamespace(user32=user32, kernel32=kernel32)):
            with self.assertRaises(OSError) as error:
                self.original_post(100, 51)
        self.assertEqual(error.exception.winerror, 5)
        self.assertIn("správca", str(error.exception))

    def test_repeat_and_release_target_same_window(self):
        self.app.autocast_tick("a")
        self.send.assert_called_once_with(100, 51)
        self.assertEqual([c.args[0] for c in self.app.after.call_args_list], [40, 500])
        self.app.release_autocast_key("a")
        self.send.assert_called_with(100, 51, released=True)

    def test_dead_process_stops_without_input(self):
        self.kernel.GetExitCodeProcess.side_effect = lambda handle, pointer: False
        self.app.autocast_tick("a")
        self.send.assert_not_called()
        self.assertFalse(self.app.autocast_sessions)
        self.kernel.CloseHandle.assert_called_once_with(900)

    def test_reused_window_never_receives_input(self):
        with patch.object(main, "visible_window_pid", return_value=99), patch.object(main, "find_existing_window_for_pid", return_value=None):
            self.app.autocast_tick("a")
        self.send.assert_not_called()
        self.assertFalse(self.app.autocast_sessions)

    def test_login_pauses_casting(self):
        self.app.busy = True
        self.app.autocast_tick("a")
        self.send.assert_not_called()
        self.app.after.assert_called_once()
        self.assertEqual(self.app.after.call_args.args[0], 500)

    def test_stop_cancels_and_releases(self):
        self.app.autocast_tick("a")
        self.app.stop_autocast("a")
        self.assertEqual(self.app.after_cancel.call_count, 2)
        self.send.assert_called_with(100, 51, released=True)
        self.kernel.CloseHandle.assert_called_once_with(900)
        self.assertFalse(self.app.autocast_sessions)

    def test_release_failure_closes_handle_once(self):
        self.app.autocast_tick("a")
        self.send.side_effect = OSError("blocked")
        self.app.stop_autocast("a")
        self.kernel.CloseHandle.assert_called_once_with(900)

    def prepare_start(self):
        self.app.autocast_sessions.clear()
        self.app.save_autocast_settings = Mock(return_value=True)
        self.app._account_window_context = Mock(return_value={"pid": "42", "hwnd": "0x64"})
        return {"id": "a", "autocast_key": "3", "autocast_interval": 500}

    def test_launch_owned_process_does_not_reopen_process(self):
        account = self.prepare_start()
        process = Mock(pid=42)
        process.poll.return_value = None
        self.app.wow_processes["a"] = process
        self.app.toggle_autocast(account)
        self.kernel.OpenProcess.assert_not_called()
        self.send.assert_called_once_with(100, 51)
        process.poll.return_value = 0
        self.app.release_autocast_key("a")
        self.send.reset_mock()
        self.app.autocast_tick("a")
        self.assertFalse(self.app.autocast_sessions)
        self.kernel.CloseHandle.assert_not_called()
        self.send.assert_not_called()

    def test_access_denied_uses_verified_window_and_stops_on_identity_change(self):
        account = self.prepare_start()
        self.kernel.OpenProcess.return_value = None
        with patch.object(main.messagebox, "showerror") as error:
            self.app.toggle_autocast(account)
            error.assert_not_called()
        self.send.assert_called_once_with(100, 51)
        self.kernel.GetExitCodeProcess.assert_not_called()
        self.identity_mock.return_value = (42, 88, "OtherClass")
        self.send.reset_mock()
        self.app.autocast_tick("a")
        self.send.assert_not_called()
        self.assertFalse(self.app.autocast_sessions)
        self.kernel.CloseHandle.assert_not_called()

    def test_dynamic_slots_have_independent_intervals_and_shared_stop(self):
        account = self.prepare_start()
        account["autocasts"] = [{"key": "3", "interval": 500}, {"key": "F2", "interval": 900},
                                {"key": "4", "interval": 1200}, {"key": "5", "interval": 1600}]
        self.kernel.OpenProcess.return_value = None
        self.app.toggle_autocast(account)
        self.assertEqual([call.args for call in self.send.call_args_list], [(100, 51), (100, 113), (100, 52), (100, 53)])
        self.assertEqual([call.args[0] for call in self.app.after.call_args_list], [40, 500, 40, 900, 40, 1200, 40, 1600])
        self.app.stop_autocast("a")
        self.assertEqual(self.app.after_cancel.call_count, 8)
        self.assertFalse(self.app.autocast_sessions)
        self.assertEqual(sum(call.kwargs.get("released", False) for call in self.send.call_args_list), 4)

    def test_legacy_settings_migrate_and_empty_list_stays_empty(self):
        self.assertEqual(main.account_autocasts({"autocast_key": "F3", "autocast_interval": 800}),
                         [{"key": "F3", "interval": "800"}])
        self.assertEqual(main.account_autocasts({"autocasts": [], "autocast_key": "3"}), [])

    def test_empty_cast_list_does_not_open_process(self):
        account = self.prepare_start()
        account["autocasts"] = []
        with patch.object(main.messagebox, "showinfo") as info:
            self.app.toggle_autocast(account)
            info.assert_called_once()
        self.kernel.OpenProcess.assert_not_called()
        self.send.assert_not_called()

    def test_anti_afk_waits_five_minutes_then_releases_micro_movement(self):
        account = self.prepare_start()
        account["autocasts"] = []
        self.kernel.OpenProcess.return_value = None
        self.app.toggle_autocast(account, anti_afk=True)
        self.send.assert_not_called()
        self.app.after.assert_called_once()
        self.assertEqual(self.app.after.call_args.args[0], 300000)
        self.app.after.call_args.args[1]()
        self.send.assert_called_once_with(100, ord("W"))
        self.assertEqual([c.args[0] for c in self.app.after.call_args_list], [300000, 60, 300000])
        self.app.persist = Mock()
        self.app.set_anti_afk(account, False)
        self.send.assert_called_with(100, ord("W"), released=True)
        self.assertNotIn("anti:a", self.app.autocast_sessions)
        self.app.persist.assert_called_once()

    def test_anti_afk_offline_saves_without_input_or_dialog(self):
        account = self.prepare_start()
        self.app._account_window_context.return_value = None
        self.app.persist = Mock()
        with patch.object(main.messagebox, "showinfo") as info:
            self.app.set_anti_afk(account, True)
        self.assertTrue(account["anti_afk"])
        info.assert_not_called()
        self.send.assert_not_called()
        self.assertNotIn("anti:a", self.app.autocast_sessions)

    def test_global_stop_preserves_anti_afk(self):
        self.app.autocast_sessions["anti:a"] = {"slots": []}
        self.app.update_account_status = Mock()
        self.app.toggle_all_autocasts()
        self.assertEqual(list(self.app.autocast_sessions), ["anti:a"])

    def test_global_start_skips_offline_accounts_without_dialogs(self):
        account = self.prepare_start()
        account["wow_pid"] = "42"
        self.app.config_data = {"accounts": [account, {"id": "offline"}]}
        self.app.update_account_status = Mock()
        self.app._account_window_context.side_effect = [{"pid": "42", "hwnd": "0x64"}, None]
        self.kernel.OpenProcess.return_value = None
        with patch.object(main.messagebox, "showinfo") as info:
            self.app.toggle_all_autocasts()
        self.assertIn("a", self.app.autocast_sessions)
        self.assertNotIn("offline", self.app.autocast_sessions)
        info.assert_not_called()

    def test_hotkey_hold_toggles_once_and_rearms_on_release(self):
        self.app.autocast_hotkey_down = False
        self.app.autocast_hotkey_keys = (0x11, 0x12, 0x77)
        self.app.toggle_all_autocasts = Mock()
        user = Mock()
        user.GetAsyncKeyState.return_value = -32768
        with patch.object(main.ctypes, "windll", SimpleNamespace(user32=user)):
            self.app.poll_autocast_hotkey()
            self.app.poll_autocast_hotkey()
            self.app.toggle_all_autocasts.assert_called_once()
            user.GetAsyncKeyState.return_value = 0
            self.app.poll_autocast_hotkey()
            user.GetAsyncKeyState.return_value = -32768
            self.app.poll_autocast_hotkey()
        self.assertEqual(self.app.toggle_all_autocasts.call_count, 2)

    def test_configurable_hotkey_parser(self):
        self.assertEqual(main.global_autocast_hotkey("f9"), ("F9", (0x78,)))
        self.assertEqual(main.global_autocast_hotkey(" alt + ctrl + f8 "), ("Ctrl+Alt+F8", (0x11, 0x12, 0x77)))
        for invalid in ("", "Ctrl", "Ctrl+Ctrl+F8", "F8+F9"):
            with self.assertRaises(ValueError):
                main.global_autocast_hotkey(invalid)


if __name__ == "__main__":
    unittest.main()
