"""Start the packaged launcher with isolated test config; never launches a game."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

workspace = Path(__file__).resolve().parent.parent
smoke = workspace / ".local/runtime_smoke"
smoke.mkdir(parents=True, exist_ok=True)
fake = smoke / "Wow.exe"
fake.write_bytes(b"")
folder = smoke / "WoWNemesisLauncher"
folder.mkdir(exist_ok=True)
(folder / "config.json").write_text(json.dumps({"wow_path": str(fake), "accounts": [],
                                               "multibox_defaults_applied": True}), encoding="utf-8")
from build_release import version
release_name = f"WoW_Nemesis_Launcher_v{version()}"
exe = workspace / "dist" / release_name / f"{release_name}.exe"
if len(sys.argv) > 1:
    exe = Path(sys.argv[1]).resolve()
env = os.environ.copy()
for variable in ("PYTHONPATH", "PYTHONHOME", "TCL_LIBRARY", "TK_LIBRARY"):
    env.pop(variable, None)
env["APPDATA"] = str(smoke)
process = subprocess.Popen([str(exe)], env=env, cwd=exe.parent)
try:
    time.sleep(3)
    assert process.poll() is None, "EXE exited during startup"
    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    titles, errors = [], []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def child(hwnd, param):
        value = ctypes.create_unicode_buffer(8192)
        user32.GetWindowTextW(hwnd, value, len(value))
        if value.value:
            errors.append(value.value)
        return True

    child_callback = callback_type(child)

    def visit(hwnd, param):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            value = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, value, len(value))
            titles.append(value.value)
            if "Unhandled" in value.value or value.value == "Error":
                user32.EnumChildWindows(hwnd, child_callback, 0)
        return True

    user32.EnumWindows(callback_type(visit), 0)
    assert not errors, errors
    assert any(f"WoW Nemesis Launcher v{version()}" in value for value in titles), titles
    print("Packaged EXE startup OK; real account config untouched")
finally:
    process.terminate()
    process.wait(timeout=5)
