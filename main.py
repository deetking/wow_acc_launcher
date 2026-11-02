from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import uuid

# Windowed builds have no console streams; dependency diagnostics still need a writer.
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))
import customtkinter as ctk

ctk.set_appearance_mode("dark")


APP_BASE_NAME = "WoW Nemesis Launcher"
APP_VERSION = "1.12"
APP_AUTHOR = "Bc. Juraj Pekarík"
APP_NAME = f"{APP_BASE_NAME} v{APP_VERSION}"
REALMLIST = "gigafun.project-nemesis.cz"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WoWNemesisLauncher"
CONFIG_FILE = CONFIG_DIR / "config.json"

BG = "#0b0e14"
PANEL = "#111722"
PANEL_ALT = "#1a2230"
GOLD = "#d8b678"
GOLD_HOVER = "#edcd97"
GOLD_DARK = "#8b6b1b"
TEXT = "#eff2f8"
MUTED = "#8995a9"
DANGER = "#9e4d61"

# HWND/HANDLE values are pointer-sized on 64-bit Windows.
if sys.platform == "win32":
    user32 = ctypes.windll.user32
    for name in ("IsWindow", "IsWindowVisible", "BringWindowToTop", "SetForegroundWindow"):
        getattr(user32, name).argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    ctypes.windll.psapi.GetModuleBaseNameW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _mix_color(start: str, end: str, amount: float) -> str:
    start_rgb = _hex_to_rgb(start)
    end_rgb = _hex_to_rgb(end)
    mixed = tuple(round(a + (b - a) * amount) for a, b in zip(start_rgb, end_rgb))
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, object]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_secret(value: str) -> str:
    if sys.platform != "win32":
        raise RuntimeError("Bezpečné uloženie hesla je podporované iba vo Windows.")
    source, source_buffer = _blob(value.encode("utf-8"))
    result = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), APP_NAME, None, None, None, 0, ctypes.byref(result)
    ):
        raise ctypes.WinError()
    try:
        raw = ctypes.string_at(result.pbData, result.cbData)
        return base64.b64encode(raw).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def unprotect_secret(value: str) -> str:
    encrypted = base64.b64decode(value)
    source, source_buffer = _blob(encrypted)
    result = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def default_config() -> dict:
    return {
        "wow_path": "",
        "official_launcher_path": "",
        "wowopenbox_path": "",
        "autoclicker_path": "",
        "background_path": "",
        "autocast_hotkey": "Ctrl+Alt+F8",
        "last_wow_hwnd": "",
        "last_wow_pid": "",
        "last_wow_account_id": "",
        "last_wow_account": "",
        "last_wow_username": "",
        "window_timeout": 30,
        "ready_delay": 3.0,
        "login_click_x": 50,
        "login_click_y": 48,
        "close_after_login": False,
        "multibox_defaults_applied": True,
        "accounts": [],
    }


def load_config() -> dict:
    config = default_config()
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            config.update(saved)
            if not saved.get("multibox_defaults_applied"):
                config["close_after_login"] = False
                config["multibox_defaults_applied"] = True
        if not isinstance(config.get("accounts"), list):
            config["accounts"] = []
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        messagebox.showwarning(APP_NAME, f"Konfiguráciu sa nepodarilo načítať:\n{exc}")
    return config


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, CONFIG_FILE)


def find_window_for_pid(pid: int, timeout: float) -> int | None:
    user32 = ctypes.windll.user32
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    callback = callback_type(visit)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found.clear()
        user32.EnumWindows(callback, 0)
        if found:
            return found[0]
        time.sleep(0.25)
    return None


def find_existing_window_for_pid(pid: int) -> int | None:
    user32 = ctypes.windll.user32
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return found[0] if found else None


def find_visible_window_for_process_name(keywords: tuple[str, ...]) -> tuple[int, int] | None:
    processes = list_named_processes(keywords)
    for process in processes:
        for hwnd in process.get("windows", []):
            return int(hwnd), int(process["pid"])
    return None


def activate_window(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = wintypes.RECT()
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


def parse_hwnd(value: str) -> int | None:
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return None


def visible_window_pid(hwnd_value: str) -> int | None:
    hwnd = parse_hwnd(hwnd_value)
    if not hwnd:
        return None
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return int(process_id.value) if process_id.value else None


def process_exists(pid_value: str) -> bool:
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return False
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def paste_text(pyautogui, value: str) -> None:
    try:
        import pyperclip

        previous = pyperclip.paste()
        pyperclip.copy(value)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.08)
        pyperclip.copy(previous)
    except Exception:
        pyautogui.write(value, interval=0.03)


def autocast_key(value: str) -> int:
    key = value.strip().upper()
    if len(key) == 1 and key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        return ord(key)
    if re.fullmatch(r"F([1-9]|1[0-2])", key):
        return 0x70 + int(key[1:]) - 1
    named = {"SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D,
             "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27}
    if key in named:
        return named[key]
    raise ValueError("Použi jednu klávesu A–Z, 0–9, F1–F12, SPACE, TAB, ENTER alebo šípku UP/DOWN/LEFT/RIGHT.")


def global_autocast_hotkey(value: str) -> tuple[str, tuple[int, ...]]:
    parts = [part.strip().upper() for part in value.split("+")]
    modifiers = {"CTRL": ("Ctrl", 0x11), "ALT": ("Alt", 0x12), "SHIFT": ("Shift", 0x10)}
    if not parts or any(part not in modifiers for part in parts[:-1]) or len(set(parts)) != len(parts):
        raise ValueError("Použi napr. F8, Ctrl+F8 alebo Ctrl+Alt+F8.")
    key = autocast_key(parts[-1])
    ordered = [modifiers[name] for name in modifiers if name in parts[:-1]]
    return "+".join([name for name, _ in ordered] + [parts[-1]]), tuple([code for _, code in ordered] + [key])


def account_autocasts(account: dict) -> list[dict]:
    saved = account.get("autocasts")
    if isinstance(saved, list):
        return [{"key": str(item.get("key", "3")), "interval": str(item.get("interval", 500))}
                for item in saved if isinstance(item, dict)]
    return [{"key": str(account.get("autocast_key", "3")),
             "interval": str(account.get("autocast_interval", 500))}]


def window_identity(hwnd: int) -> tuple[int, int, str] | None:
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    pid = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ctypes.create_unicode_buffer(256)
    if not thread_id or not pid.value or not user32.GetClassNameW(hwnd, name, len(name)):
        return None
    return int(pid.value), int(thread_id), name.value


def post_autocast_key(hwnd: int, key: int, released: bool = False) -> None:
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    scan = user32.MapVirtualKeyW(key, 0)
    flags = 1 | (scan << 16)
    if key in (0x25, 0x26, 0x27, 0x28):
        flags |= 1 << 24
    if released:
        flags |= (1 << 30) | (1 << 31)
    if not user32.PostMessageW(hwnd, 0x0101 if released else 0x0100, key, flags):
        error = ctypes.windll.kernel32.GetLastError()
        if error == 5:
            raise ctypes.WinError(error, "Windows blokuje vstup do WoW okna. Ak hra beží ako správca, spusti ako správca aj launcher.")
        raise ctypes.WinError(error)


def find_wowopenbox_executable(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    preferred_names = ("wob2025", "openmultiboxing", "wowopenbox", "wob")
    matches = [path for path in folder.rglob("*.exe") if path.is_file()]
    for keyword in preferred_names:
        found = next((path for path in matches if keyword in path.name.lower()), None)
        if found:
            return found
    return matches[0] if matches else None


def valid_exe_path(path_value: str) -> bool:
    path = Path(path_value)
    return path.is_file() and path.suffix.lower() == ".exe"


def list_named_processes(keywords: tuple[str, ...]) -> list[dict]:
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    user32 = ctypes.windll.user32
    process_ids = (wintypes.DWORD * 4096)()
    bytes_returned = wintypes.DWORD()
    if not psapi.EnumProcesses(
        ctypes.byref(process_ids), ctypes.sizeof(process_ids), ctypes.byref(bytes_returned)
    ):
        return []
    count = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)
    current_pid = os.getpid()
    matches: list[dict] = []
    access = 0x0400 | 0x0010  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    for index in range(count):
        pid = int(process_ids[index])
        if not pid or pid == current_pid:
            continue
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(260)
            if not psapi.GetModuleBaseNameW(handle, None, buffer, len(buffer)):
                continue
            name = buffer.value
            lower_name = name.lower()
            if any(keyword in lower_name for keyword in keywords):
                path_buffer = ctypes.create_unicode_buffer(1024)
                path_size = wintypes.DWORD(len(path_buffer))
                path = ""
                if kernel32.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(path_size)):
                    path = path_buffer.value
                matches.append({"pid": pid, "name": name, "path": path, "windows": []})
        finally:
            kernel32.CloseHandle(handle)

    if not matches:
        return []

    by_pid = {item["pid"]: item for item in matches}
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value in by_pid and user32.IsWindowVisible(hwnd):
            by_pid[process_id.value]["windows"].append(hwnd)
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return matches


def close_process_windows(processes: list[dict]) -> None:
    user32 = ctypes.windll.user32
    for process in processes:
        for hwnd in process.get("windows", []):
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


def terminate_processes(processes: list[dict]) -> None:
    kernel32 = ctypes.windll.kernel32
    access = 0x0001  # PROCESS_TERMINATE
    for process in processes:
        handle = kernel32.OpenProcess(access, False, int(process["pid"]))
        if not handle:
            continue
        try:
            kernel32.TerminateProcess(handle, 1)
        finally:
            kernel32.CloseHandle(handle)


def describe_processes(processes: list[dict]) -> str:
    return "\n".join(
        f"- {process['name']} (PID {process['pid']})"
        + (f"\n  {process['path']}" if process.get("path") else "")
        for process in processes
    )


class RoundedButton(ctk.CTkButton):
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command,
        width: int,
        height: int,
        background: str,
        hover: str,
        foreground: str,
        font: tuple,
        radius: int = 9,
    ):
        super().__init__(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            corner_radius=radius,
            fg_color=background,
            hover_color=hover,
            text_color=foreground,
            border_width=1,
            border_color=_mix_color(background, "#ffffff", 0.14),
            font=font,
        )


class AccountDialog(ctk.CTkToplevel):
    def __init__(self, parent: tk.Misc, account: dict | None = None):
        super().__init__(parent)
        self.title("Účet")
        self.configure(fg_color=PANEL)
        self.resizable(False, False)
        self.result: dict | None = None
        self.account = account or {}
        self.password_visible = False
        self.columnconfigure(1, weight=1)

        for row, label in enumerate(("NÁZOV ÚČTU", "USERNAME", "REGISTROVANÝ E-MAIL", "HESLO")):
            ctk.CTkLabel(self, text=label, text_color=MUTED,
                         font=("Segoe UI", 10, "bold")).grid(row=row, column=0, padx=(22, 14), pady=(16 if row == 0 else 7, 7), sticky="w")
        entry_options = dict(width=300, height=38, corner_radius=9, fg_color=PANEL_ALT,
                             border_color="#355137", border_width=1, text_color=TEXT)
        self.name = ctk.CTkEntry(self, placeholder_text="napr. Warrior", **entry_options)
        self.username = ctk.CTkEntry(self, placeholder_text="prihlasovacie meno", **entry_options)
        self.email = ctk.CTkEntry(self, placeholder_text="voliteľné", **entry_options)
        password_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.password = ctk.CTkEntry(
            password_frame,
            placeholder_text="heslo",
            show="•",
            width=204,
            height=38,
            corner_radius=9,
            fg_color=PANEL_ALT,
            border_color="#355137",
            border_width=1,
            text_color=TEXT,
        )
        self.password_toggle = ctk.CTkButton(
            password_frame,
            text="ZOBRAZIŤ",
            command=self.toggle_password_visibility,
            width=88,
            height=38,
            corner_radius=9,
            fg_color="#282b2d",
            hover_color="#373b3e",
            text_color=TEXT,
            font=("Segoe UI", 9, "bold"),
        )
        self.name.grid(row=0, column=1, padx=(0, 22), pady=(16, 7))
        self.username.grid(row=1, column=1, padx=(0, 22), pady=7)
        self.email.grid(row=2, column=1, padx=(0, 22), pady=7)
        password_frame.grid(row=3, column=1, padx=(0, 22), pady=7)
        self.password.pack(side="left")
        self.password_toggle.pack(side="left", padx=(8, 0))
        self.name.insert(0, self.account.get("name", ""))
        self.username.insert(0, self.account.get("username", ""))
        if self.account.get("email"):
            try:
                self.email.insert(0, unprotect_secret(self.account["email"]))
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"E-mail sa nepodarilo odomknúť:\n{exc}", parent=self)
        if self.account.get("password"):
            try:
                self.password.insert(0, unprotect_secret(self.account["password"]))
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Heslo sa nepodarilo odomknúť:\n{exc}", parent=self)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, columnspan=2, padx=22, pady=(14, 22), sticky="e")
        ctk.CTkButton(buttons, text="ZRUŠIŤ", command=self.destroy, width=100, height=38,
                      corner_radius=9, fg_color="#282b2d", hover_color="#373b3e").pack(side="right")
        ctk.CTkButton(buttons, text="ULOŽIŤ ÚČET", command=self.submit, width=145, height=38,
                      corner_radius=9, fg_color="#4a8d50", hover_color="#61b669").pack(side="right", padx=(0, 10))
        self.bind("<Return>", lambda _event: self.submit())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.transient(parent)
        self.grab_set()
        self.name.focus_set()

    def toggle_password_visibility(self) -> None:
        self.password_visible = not self.password_visible
        self.password.configure(show="" if self.password_visible else "•")
        self.password_toggle.configure(text="SKRYŤ" if self.password_visible else "ZOBRAZIŤ")

    def submit(self) -> None:
        name = self.name.get().strip()
        username = self.username.get().strip()
        email = self.email.get().strip()
        password = self.password.get()
        if not name or not username or not password:
            messagebox.showwarning(APP_NAME, "Vyplň názov, username aj heslo.", parent=self)
            return
        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            messagebox.showwarning(APP_NAME, "Zadaj platnú e-mailovú adresu alebo pole nechaj prázdne.", parent=self)
            return
        try:
            encrypted = protect_secret(password)
            encrypted_email = protect_secret(email) if email else ""
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Údaje sa nepodarilo bezpečne uložiť:\n{exc}", parent=self)
            return
        self.result = {
            "id": self.account.get("id", uuid.uuid4().hex),
            "name": name,
            "username": username,
            "email": encrypted_email,
            "password": encrypted,
        }
        self.destroy()


class Launcher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x760")
        self.minsize(800, 580)
        self.configure(fg_color=BG)
        self.config_data = load_config()
        self.busy = False
        self.open_order_account_id = ""
        self.autocast_sessions = {}
        self.wow_processes = {}
        self.autocast_drafts = {}
        self.autocast_hotkey_down = False
        self.autocast_hotkey_timer = None
        try:
            hotkey_label, self.autocast_hotkey_keys = global_autocast_hotkey(self.config_data.get("autocast_hotkey", "Ctrl+Alt+F8"))
        except ValueError:
            hotkey_label, self.autocast_hotkey_keys = global_autocast_hotkey("Ctrl+Alt+F8")
        self.account_widgets = {}
        self.accounts_signature = None
        self.background_resize_timer = None
        self.background_size = None
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(500, self.resume_anti_afk)

        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        try:
            from PIL import Image, ImageTk

            self.background_source = self.load_background_source()
            artwork = self.background_source.resize((1100, 680), Image.Resampling.LANCZOS)
            self.background_image = ImageTk.PhotoImage(artwork)
            self.background_id = self.canvas.create_image(0, 0, image=self.background_image, anchor="center")
        except (ImportError, OSError, tk.TclError):
            self.background_source = None
            self.background_image = None
            self.background_id = None
        topbar = ctk.CTkFrame(self.canvas, fg_color="#0c0c0b", corner_radius=0,
                              border_color="#263b25", border_width=1)
        self.topbar_window = self.canvas.create_window(0, 0, window=topbar, anchor="nw", width=1100, height=80)
        nav = ctk.CTkFrame(topbar, fg_color="transparent")
        nav.pack(side="left", padx=12, fill="y")
        for text, command, width in (
            ("ÚČTY", lambda: self.accounts_canvas.yview_moveto(0), 64),
            ("UPDATER", self.launch_official_updater, 78),
            ("WOB", self.launch_wowopenbox, 58),
            ("STOP WOB", self.stop_wowopenbox, 84),
            ("CLICK", lambda: self.launch_external_tool("autoclicker_path", "AUTOCLICKER"), 62),
            ("NÁSTROJE", self.open_tools, 84),
            ("SETTINGS", self.open_settings, 80),
        ):
            ctk.CTkButton(nav, text=text, command=command, width=width, height=36,
                          corner_radius=7, fg_color="transparent", hover_color="#172019",
                          text_color="#f2eadc", font=("Segoe UI", 10, "bold")).pack(side="left", padx=2, pady=20)
        brand_box = ctk.CTkFrame(topbar, fg_color="transparent")
        brand_box.pack(side="right", padx=20, pady=14)
        ctk.CTkLabel(brand_box, text="N E M E S I S", text_color=GOLD,
                     font=("Segoe UI", 15, "bold")).pack(anchor="e")
        ctk.CTkLabel(brand_box, text="GIGAFUN • ACCOUNT MANAGER", text_color="#5db965",
                     font=("Segoe UI", 9, "bold")).pack(anchor="e")
        self.notice_id = self.canvas.create_text(38, 126, text="Tvoje účty", fill=TEXT,
                                                  anchor="w", font=("Segoe UI", 29, "bold"))
        self.brand_id = self.canvas.create_text(38, 161, text="Tvoja zostava. Pripravená na ďalší login.",
                                                fill=MUTED, anchor="w", font=("Segoe UI", 12))
        self.brand_subtitle_id = self.canvas.create_text(1060, 130, text="", fill=GOLD,
                                                         anchor="e", font=("Segoe UI", 12))
        accounts_panel = ctk.CTkFrame(self.canvas, fg_color=PANEL, corner_radius=20,
                                      border_width=0)
        self.accounts_panel_window = self.canvas.create_window(550, 195, window=accounts_panel,
                                                                anchor="n", width=1028, height=465)
        accounts_area = ctk.CTkFrame(accounts_panel, fg_color=PANEL, corner_radius=16)
        accounts_area.pack(fill="both", expand=True, padx=8, pady=10)
        self.accounts_canvas = tk.Canvas(accounts_area, bg=PANEL, highlightthickness=0, bd=0)
        accounts_scrollbar = ctk.CTkScrollbar(
            accounts_area, orientation="vertical", command=self.accounts_canvas.yview,
            width=8, fg_color=PANEL, button_color="#293448", button_hover_color="#53617a",
        )
        self.accounts_canvas.configure(yscrollcommand=accounts_scrollbar.set)
        accounts_scrollbar.pack(side="right", fill="y", padx=(0, 12), pady=12)
        self.accounts_canvas.pack(side="left", fill="both", expand=True)
        self.accounts_frame = ctk.CTkFrame(self.accounts_canvas, fg_color=PANEL, corner_radius=0)
        self.accounts_window = self.accounts_canvas.create_window((0, 0), window=self.accounts_frame, anchor="nw")
        self.accounts_frame.bind(
            "<Configure>",
            lambda _event: self.accounts_canvas.configure(scrollregion=self.accounts_canvas.bbox("all")),
        )
        self.accounts_canvas.bind(
            "<Configure>",
            lambda event: self.accounts_canvas.itemconfigure(self.accounts_window, width=event.width),
        )
        self.bind_all("<MouseWheel>", self._scroll_accounts, add="+")
        footer = ctk.CTkFrame(self.canvas, fg_color="#0a0b09", corner_radius=0,
                              border_color="#394322", border_width=1)
        self.footer_window = self.canvas.create_window(0, 680, window=footer, anchor="sw", width=1100, height=80)
        self._gold_button(footer, "+  Pridať účet", self.add_account, width=17).pack(side="left", padx=24, pady=18)
        self.all_autocasts_button = ctk.CTkButton(footer, text=f"Autocasty · {hotkey_label}", command=self.toggle_all_autocasts,
                      width=205, height=36, corner_radius=8, fg_color="#264b40",
                      hover_color="#326653", font=("Segoe UI", 11, "bold"))
        self.all_autocasts_button.pack(side="left", padx=4)
        footer_meta = ctk.CTkFrame(footer, fg_color="transparent")
        footer_meta.pack(side="right", padx=24, pady=16)
        self.status = ctk.CTkLabel(
            footer_meta, text="●  PRIPRAVENÉ", text_color="#c7c2b6",
            font=("Segoe UI", 10, "bold"), wraplength=260,
        )
        self.status.pack(anchor="e")
        ctk.CTkLabel(footer_meta, text=f"v{APP_VERSION}  ·  {APP_AUTHOR}", text_color="#5b5a56",
                     font=("Segoe UI", 9)).pack(anchor="e")
        self.canvas.bind("<Configure>", self._resize_background)
        self.render_accounts()
        self.after(100, self.first_run)
        self.after(500, self.refresh_wob_status)
        self.after(1500, self.watch_last_wow_window)
        self.autocast_hotkey_timer = self.after(50, self.poll_autocast_hotkey)

    def load_background_source(self):
        from PIL import Image

        custom_path = Path(self.config_data.get("background_path", ""))
        if custom_path.is_file():
            try:
                return Image.open(custom_path).convert("RGB")
            except (OSError, ValueError):
                pass
        return Image.open(resource_path("assets/nemesis_background_v2.png")).convert("RGB")

    def reload_background(self) -> None:
        if not self.background_id:
            return
        try:
            self.background_source = self.load_background_source()
            self._fit_background(max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
        except (ImportError, OSError, tk.TclError):
            pass

    def _resize_background(self, event: tk.Event) -> None:
        if "accounts_panel_window" not in self.__dict__:
            return
        width, height = event.width, event.height
        self.canvas.itemconfigure(self.topbar_window, width=width)
        self.canvas.coords(self.accounts_panel_window, width / 2, 195)
        self.canvas.itemconfigure(self.accounts_panel_window, width=max(400, width - 72),
                                  height=max(220, height - 195 - 100))
        self.canvas.coords(self.footer_window, 0, height)
        self.canvas.itemconfigure(self.footer_window, width=width)
        self.canvas.coords(self.brand_subtitle_id, width - 38, 130)
        if self.background_id and (width, height) != self.background_size:
            if self.background_resize_timer:
                self.after_cancel(self.background_resize_timer)
            self.background_resize_timer = self.after(100, lambda: self._fit_background(width, height))

    def _fit_background(self, width: int, height: int) -> None:
        if not self.background_source or width < 1 or height < 1:
            return
        try:
            from PIL import Image, ImageTk

            source_width, source_height = self.background_source.size
            scale = max(width / source_width, height / source_height)
            target_size = (max(1, int(source_width * scale)), max(1, int(source_height * scale)))
            image = self.background_source.resize(target_size, Image.Resampling.LANCZOS)
            left = max(0, (target_size[0] - width) // 2)
            top = max(0, (target_size[1] - height) // 2)
            image = image.crop((left, top, left + width, top + height))
            self.background_image = ImageTk.PhotoImage(image)
            self.background_size = (width, height)
            self.background_resize_timer = None
            self.canvas.itemconfigure(self.background_id, image=self.background_image)
            self.canvas.coords(self.background_id, width / 2, height / 2)
        except (ImportError, OSError, tk.TclError):
            pass

    def _scroll_accounts(self, event: tk.Event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not self.accounts_canvas:
            widget = getattr(widget, "master", None)
        if widget is not self.accounts_canvas:
            return
        direction = -1 if event.delta > 0 else 1
        self.accounts_canvas.yview_scroll(direction * 3, "units")

    def _gold_button(self, parent: tk.Misc, text: str, command, width: int = 22) -> RoundedButton:
        return RoundedButton(parent, text, command, max(120, width * 10), 42, GOLD, GOLD_HOVER,
                             BG, ("Segoe UI", 11, "bold"), radius=14)

    def _dark_button(self, parent: tk.Misc, text: str, command, width: int = 10, danger: bool = False) -> RoundedButton:
        color = DANGER if danger else "#151a17"
        hover = "#b94b42" if danger else "#263b25"
        return RoundedButton(parent, text, command, max(36, width * 9), 34, color, hover,
                             TEXT, ("Segoe UI", 9, "bold"), radius=12)

    def refresh_wob_status(self) -> None:
        if list_named_processes(("wob2025", "openmultiboxing", "wowopenbox")):
            self.status.configure(text="●  WOWOPENBOX BEŽÍ", text_color=GOLD)

    def set_account_window(self, account_id: str, pid: str, hwnd: str) -> None:
        for account in self.config_data.get("accounts", []):
            if str(account.get("id", "")) == str(account_id):
                account["wow_pid"] = pid
                account["wow_hwnd"] = hwnd
                return

    def clear_account_window(self, account: dict) -> None:
        account.pop("wow_pid", None)
        account.pop("wow_hwnd", None)

    def clear_last_wow_window(self) -> None:
        self.config_data["last_wow_hwnd"] = ""
        self.config_data["last_wow_pid"] = ""
        self.config_data["last_wow_account_id"] = ""
        self.config_data["last_wow_account"] = ""
        self.config_data["last_wow_username"] = ""
        self.persist()
        self.render_accounts()

    def watch_last_wow_window(self) -> None:
        changed = False
        for account in self.config_data.get("accounts", []):
            account_pid = str(account.get("wow_pid", ""))
            account_hwnd = str(account.get("wow_hwnd", ""))
            if not account_pid and not account_hwnd:
                continue
            window_pid = visible_window_pid(account_hwnd)
            if window_pid and (not account_pid or str(window_pid) == account_pid):
                window_pid_text = str(window_pid)
                if window_pid_text != account_pid:
                    account["wow_pid"] = window_pid_text
                    changed = True
            elif account_pid and process_exists(account_pid):
                try:
                    current_hwnd = find_existing_window_for_pid(int(account_pid))
                except ValueError:
                    current_hwnd = None
                if current_hwnd:
                    current_hwnd_hex = f"0x{current_hwnd:08X}"
                    if current_hwnd_hex != account_hwnd:
                        account["wow_hwnd"] = current_hwnd_hex
                        changed = True
                else:
                    self.clear_account_window(account)
                    changed = True
            else:
                self.clear_account_window(account)
                changed = True

        pid = str(self.config_data.get("last_wow_pid", ""))
        hwnd = str(self.config_data.get("last_wow_hwnd", ""))
        if pid or hwnd:
            window_pid = visible_window_pid(hwnd)
            if window_pid:
                window_pid_text = str(window_pid)
                if window_pid_text != pid:
                    self.config_data["last_wow_pid"] = window_pid_text
                    self.persist()
                    self.render_accounts()
            elif not process_exists(pid):
                self.clear_last_wow_window()
                self.status.configure(text="●  WOW OKNO ZATVORENÉ", text_color=MUTED)
            else:
                try:
                    current_hwnd = find_existing_window_for_pid(int(pid))
                except ValueError:
                    current_hwnd = None
                if current_hwnd:
                    current_hwnd_hex = f"0x{current_hwnd:08X}"
                    if current_hwnd_hex != hwnd:
                        self.config_data["last_wow_hwnd"] = current_hwnd_hex
                        changed = True
        if changed:
            self.persist()
            self.render_accounts()
        self.after(2000, self.watch_last_wow_window)

    def first_run(self) -> None:
        self.auto_discover_paths()
        if not self.valid_wow_path():
            messagebox.showinfo(APP_NAME, "Najprv vyber cestu k súboru WoW.exe.", parent=self)
            self.choose_wow_path()

    def valid_wow_path(self) -> bool:
        path = Path(self.config_data.get("wow_path", ""))
        return path.is_file() and path.name.lower() == "wow.exe"

    def auto_discover_paths(self) -> bool:
        """Find a nearby WoW installation without recursively scanning whole disks."""
        candidates: list[Path] = []
        configured_launcher = Path(self.config_data.get("official_launcher_path", ""))
        if configured_launcher.is_file():
            candidates.append(configured_launcher.parent / "Wow.exe")
        app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        roots = [app_dir, Path.cwd(), app_dir.parent, Path("C:/Games"), Path("D:/Games"), Path("C:/Program Files"), Path("C:/Program Files (x86)")]
        candidates.extend(root / "Wow.exe" for root in roots)
        for root in roots:
            if not root.is_dir():
                continue
            for pattern in ("World of Warcraft*", "WoW*", "GigaFun*", "Nemesis*"):
                try:
                    candidates.extend(folder / "Wow.exe" for folder in root.glob(pattern) if folder.is_dir())
                except OSError:
                    pass
        found = next((path for path in candidates if path.is_file()), None)
        changed = False
        if found and not self.valid_wow_path():
            self.config_data["wow_path"] = str(found.resolve())
            changed = True
        wow_path = Path(self.config_data.get("wow_path", ""))
        if wow_path.is_file():
            nearby = wow_path.parent / "GigaFun_Launcher.exe"
            if nearby.is_file() and not configured_launcher.is_file():
                self.config_data["official_launcher_path"] = str(nearby.resolve())
                changed = True
        if not find_wowopenbox_executable(Path(self.config_data.get("wowopenbox_path", ""))):
            app_base = Path(__file__).resolve().parent
            wob_folder = next(
                (
                    path
                    for path in (
                        app_base / "WOB2025",
                    )
                    if find_wowopenbox_executable(path)
                ),
                None,
            )
            if wob_folder:
                self.config_data["wowopenbox_path"] = str(wob_folder.resolve())
                changed = True
        if changed:
            self.persist()
        return self.valid_wow_path()

    def choose_wow_path(self) -> None:
        selected = filedialog.askopenfilename(
            title="Vyber WoW.exe", filetypes=[("World of Warcraft", "WoW.exe"), ("EXE súbory", "*.exe")]
        )
        if selected:
            if Path(selected).name.lower() != "wow.exe":
                messagebox.showwarning(APP_NAME, "Vybraný súbor sa musí volať WoW.exe.", parent=self)
                return
            self.config_data["wow_path"] = selected
            nearby = Path(selected).parent / "GigaFun_Launcher.exe"
            if nearby.is_file():
                self.config_data["official_launcher_path"] = str(nearby)
            self.persist()

    def choose_official_launcher(self) -> None:
        selected = filedialog.askopenfilename(
            title="Vyber GigaFun_Launcher.exe",
            filetypes=[("GigaFun Launcher", "GigaFun_Launcher.exe"), ("EXE súbory", "*.exe")],
        )
        if selected:
            self.config_data["official_launcher_path"] = selected
            self.persist()

    def launch_official_updater(self) -> None:
        configured = Path(self.config_data.get("official_launcher_path", ""))
        if not configured.is_file():
            self.auto_discover_paths()
            configured = Path(self.config_data.get("official_launcher_path", ""))
        if not configured.is_file():
            messagebox.showinfo(APP_NAME, "Vyber cestu k oficiálnemu GigaFun launcheru.", parent=self)
            self.choose_official_launcher()
            configured = Path(self.config_data.get("official_launcher_path", ""))
        if configured.is_file():
            try:
                subprocess.Popen([str(configured)], cwd=str(configured.parent))
                self.status.configure(text="●  OFICIÁLNY UPDATER SPUSTENÝ", text_color=GOLD)
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"Updater sa nepodarilo spustiť:\n{exc}", parent=self)

    def choose_wowopenbox_path(self) -> None:
        selected = filedialog.askdirectory(title="Vyber priečinok WowOpenBox")
        if selected:
            self.config_data["wowopenbox_path"] = selected
            self.persist()

    def choose_external_tool_path(self, config_key: str, title: str) -> None:
        selected = filedialog.askopenfilename(
            title=f"Vyber {title} .exe",
            filetypes=[("EXE súbory", "*.exe")],
        )
        if selected:
            self.config_data[config_key] = selected
            self.persist()

    def choose_background_path(self) -> None:
        selected = filedialog.askopenfilename(
            title="Vyber pozadie launcheru",
            filetypes=[
                ("Obrázky", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("Všetky súbory", "*.*"),
            ],
        )
        if selected:
            self.config_data["background_path"] = selected
            self.persist()
            self.reload_background()

    def reset_background_path(self) -> None:
        self.config_data["background_path"] = ""
        self.persist()
        self.reload_background()

    def _account_window_context(self, account: dict) -> dict[str, str] | None:
        account_pid = str(account.get("wow_pid", ""))
        account_hwnd = str(account.get("wow_hwnd", ""))
        if account_hwnd:
            visible_pid = visible_window_pid(account_hwnd)
            if visible_pid and (not account_pid or str(visible_pid) == account_pid):
                account_pid = str(visible_pid)
                account["wow_pid"] = account_pid
            else:
                account_hwnd = ""

        if not account_hwnd and account_pid and process_exists(account_pid):
            try:
                current_hwnd = find_existing_window_for_pid(int(account_pid))
            except ValueError:
                current_hwnd = None
            if current_hwnd:
                account_hwnd = f"0x{current_hwnd:08X}"
                account["wow_hwnd"] = account_hwnd

        if not account_pid or not account_hwnd:
            return None

        self.config_data["last_wow_hwnd"] = account_hwnd
        self.config_data["last_wow_pid"] = account_pid
        self.config_data["last_wow_account_id"] = str(account.get("id", ""))
        self.config_data["last_wow_account"] = str(account.get("name", ""))
        self.config_data["last_wow_username"] = str(account.get("username", ""))
        self.persist()
        self.render_accounts()
        return {
            "hwnd": account_hwnd,
            "pid": account_pid,
            "account": str(account.get("name", "")),
            "username": str(account.get("username", "")),
        }

    def launch_external_tool(self, config_key: str, title: str, account: dict | None = None) -> None:
        configured = Path(self.config_data.get(config_key, ""))
        if not valid_exe_path(str(configured)):
            messagebox.showinfo(APP_NAME, f"Najprv namapuj {title} .exe v Nastaveniach.", parent=self)
            self.choose_external_tool_path(config_key, title)
            configured = Path(self.config_data.get(config_key, ""))
        if not valid_exe_path(str(configured)):
            return
        context = None
        if account is not None:
            context = self._account_window_context(account)
            if context is None:
                messagebox.showinfo(
                    APP_NAME,
                    f"Účet „{account.get('name', '')}“ ešte nemá aktívne WoW okno.\n\n"
                    "Najprv ho spusti cez veľké tlačidlo účtu, potom bude autocast automaticky vedieť jeho PID/HWND.",
                    parent=self,
                )
                return
        try:
            env = os.environ.copy()
            hwnd = context["hwnd"] if context else str(self.config_data.get("last_wow_hwnd", ""))
            pid = context["pid"] if context else str(self.config_data.get("last_wow_pid", ""))
            account_name = context["account"] if context else str(self.config_data.get("last_wow_account", ""))
            username = context["username"] if context else str(self.config_data.get("last_wow_username", ""))
            env.update(
                {
                    "WOW_NEMESIS_LAST_HWND": hwnd,
                    "WOW_NEMESIS_LAST_PID": pid,
                    "WOW_NEMESIS_LAST_ACCOUNT": account_name,
                    "WOW_NEMESIS_LAST_USERNAME": username,
                    "WOW_NEMESIS_TARGET_HWND": hwnd,
                    "WOW_NEMESIS_TARGET_PID": pid,
                    "WOW_NEMESIS_TARGET_ACCOUNT": account_name,
                    "WOW_NEMESIS_TARGET_USERNAME": username,
                    "WOW_NEMESIS_CONFIG": str(CONFIG_FILE),
                }
            )
            subprocess.Popen([str(configured)], cwd=str(configured.parent), env=env)
            suffix = f" PRE {account_name.upper()}" if account_name else ""
            self.status.configure(text=f"●  {title} SPUSTENÝ{suffix}", text_color=GOLD)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"{title} sa nepodarilo spustiť:\n{exc}", parent=self)

    def launch_wowopenbox(self) -> None:
        self.auto_discover_paths()
        configured = Path(self.config_data.get("wowopenbox_path", ""))
        if not configured.is_dir():
            messagebox.showinfo(APP_NAME, "Vyber priečinok WOB2025.", parent=self)
            self.choose_wowopenbox_path()
            configured = Path(self.config_data.get("wowopenbox_path", ""))
        if not configured.is_dir():
            return

        running = list_named_processes(("wob2025", "openmultiboxing", "wowopenbox"))
        if running:
            if not messagebox.askyesno(
                APP_NAME,
                "WowOpenBox už beží a nová kópia by mala konflikt hotkeyov.\n\n"
                f"{describe_processes(running)}\n\n"
                "Chceš bežiaci WowOpenBox ukončiť a spustiť znova?",
                parent=self,
            ):
                self.status.configure(text="●  WOWOPENBOX UŽ BEŽÍ", text_color=MUTED)
                return
            close_process_windows(running)
            time.sleep(1.2)
            remaining = list_named_processes(("wob2025", "openmultiboxing", "wowopenbox"))
            if remaining:
                if not messagebox.askyesno(
                    APP_NAME,
                    "WowOpenBox sa nezavrel normálne.\n\n"
                    f"{describe_processes(remaining)}\n\n"
                    "Chceš ho ukončiť natvrdo?",
                    parent=self,
                ):
                    self.status.configure(text="●  WOWOPENBOX OSTAL SPUSTENÝ", text_color=MUTED)
                    return
                terminate_processes(remaining)
                time.sleep(0.5)

        executable = find_wowopenbox_executable(configured)
        try:
            if executable:
                subprocess.Popen([str(executable)], cwd=str(executable.parent))
            else:
                messagebox.showerror(
                    APP_NAME,
                    "V priečinku WOB2025 nevidím spustiteľný WOB EXE súbor.\n\n"
                    "Skontroluj, že tam je napríklad WOB2025-v4.8.3.exe.",
                    parent=self,
                )
                return
            self.status.configure(text="●  WOWOPENBOX SPUSTENÝ", text_color=GOLD)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"WowOpenBox sa nepodarilo spustiť:\n{exc}", parent=self)

    def stop_wowopenbox(self) -> None:
        running = list_named_processes(("wob2025", "openmultiboxing", "wowopenbox"))
        if not running:
            self.status.configure(text="●  WOWOPENBOX NEBEŽÍ", text_color=MUTED)
            messagebox.showinfo(APP_NAME, "Nenašiel som bežiaci WowOpenBox/WOB2025 proces.", parent=self)
            return
        if not messagebox.askyesno(
            APP_NAME,
            "Ukončiť bežiaci WowOpenBox?\n\n"
            f"{describe_processes(running)}",
            parent=self,
        ):
            return
        close_process_windows(running)
        time.sleep(1.2)
        remaining = list_named_processes(("wob2025", "openmultiboxing", "wowopenbox"))
        if remaining:
            if not messagebox.askyesno(
                APP_NAME,
                "WowOpenBox sa nezavrel normálne.\n\n"
                f"{describe_processes(remaining)}\n\n"
                "Chceš ho ukončiť natvrdo?",
                parent=self,
            ):
                return
            terminate_processes(remaining)
        self.status.configure(text="●  WOWOPENBOX UKONČENÝ", text_color=MUTED)

    def ensure_realmlist(self) -> bool:
        wow_dir = Path(self.config_data["wow_path"]).parent
        target = wow_dir / "realmlist.wtf"
        desired = f"set realmlist {REALMLIST}\n"
        current = ""
        try:
            if target.is_file():
                current = target.read_text(encoding="utf-8", errors="ignore")
            if REALMLIST.lower() in current.lower():
                return True
            if not messagebox.askyesno(
                APP_NAME,
                f"Realmlist nie je nastavený na {REALMLIST}.\nChceš ho teraz opraviť?",
                parent=self,
            ):
                return False
            if target.is_file():
                backup = target.with_suffix(".wtf.launcher-backup")
                if not backup.exists():
                    backup.write_bytes(target.read_bytes())
            target.write_text(desired, encoding="ascii")

            config_wtf = wow_dir / "WTF" / "Config.wtf"
            if config_wtf.is_file():
                text = config_wtf.read_text(encoding="utf-8", errors="ignore")
                pattern = r'(?im)^\s*SET\s+realmList\s+.*$'
                replacement = f'SET realmList "{REALMLIST}"'
                updated, count = re.subn(pattern, replacement, text)
                if count:
                    config_wtf.write_text(updated, encoding="utf-8")
            return True
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Realmlist sa nepodarilo nastaviť:\n{exc}", parent=self)
            return False

    def open_tools(self) -> None:
        window = ctk.CTkToplevel(self)
        window.title("Nástroje")
        window.geometry("360x350")
        window.resizable(False, False)
        window.configure(fg_color=PANEL)
        window.transient(self)
        ctk.CTkLabel(window, text="Nástroje", text_color=TEXT,
                     font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=24, pady=(24, 16))
        for title, action in (("Aktualizovať hru", self.launch_official_updater),
                              ("Spustiť WowOpenBox", self.launch_wowopenbox),
                              ("Zastaviť WowOpenBox", self.stop_wowopenbox),
                              ("Spustiť autoclicker", lambda: self.launch_external_tool("autoclicker_path", "AUTOCLICKER"))):
            ctk.CTkButton(window, text=title, command=lambda fn=action: (window.destroy(), fn()),
                          height=42, corner_radius=10, fg_color=PANEL_ALT, hover_color="#293448",
                          text_color=TEXT, anchor="w").pack(fill="x", padx=24, pady=5)

    def render_accounts(self) -> None:
        accounts = self.config_data["accounts"]
        # Live status updates change existing widgets; cards are rebuilt only when their structure changes.
        signature = tuple((str(a.get("id", "")), a.get("name", ""), a.get("username", "")) for a in accounts)
        count = len(accounts)
        count_label = "účet" if count == 1 else "účty" if 2 <= count <= 4 else "účtov"
        self.canvas.itemconfigure(self.brand_subtitle_id, text=f"{count} {count_label}")
        if signature == self.accounts_signature:
            self.update_account_status()
            return
        scroll = self.accounts_canvas.yview()[0]
        self.accounts_signature = signature
        for widgets in self.account_widgets.values():
            if widgets.get("animation"):
                self.after_cancel(widgets["animation"])
        self.account_widgets = {}
        for child in self.accounts_frame.winfo_children():
            child.destroy()
        if not accounts:
            ctk.CTkLabel(self.accounts_frame, text="Tvoja zostava začína tu", text_color=TEXT,
                         font=("Segoe UI", 22, "bold")).pack(pady=(80, 8))
            ctk.CTkLabel(self.accounts_frame, text="Pridaj prvý účet a priprav sa na hru.",
                         text_color=MUTED, font=("Segoe UI", 12)).pack(pady=(0, 60))
            return
        for index, account in enumerate(accounts):
            account_id = str(account["id"])
            expanded = self.open_order_account_id == account_id
            card = ctk.CTkFrame(self.accounts_frame, fg_color="#171f2d", corner_radius=14,
                               border_width=0)
            card.pack(fill="x", padx=14, pady=(6, 6))
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=(12, 6))
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=f"{index + 1:02d}", width=38, height=38,
                         corner_radius=11, fg_color="#253044", text_color=GOLD,
                         font=("Segoe UI", 12, "bold")).grid(row=0, column=0, padx=(0, 14))
            ctk.CTkLabel(row, text=account["name"], text_color=TEXT, anchor="w",
                         font=("Segoe UI", 18, "bold")).grid(row=0, column=1, sticky="ew")
            game_status = ctk.CTkLabel(row, text="", font=("Segoe UI", 11), width=85)
            game_status.grid(row=0, column=2, padx=10)
            ctk.CTkButton(row, text="Spustiť hru", command=lambda a=account: self.launch(a),
                          width=118, height=36, corner_radius=10, fg_color=GOLD,
                          hover_color=GOLD_HOVER, text_color=BG, font=("Segoe UI", 12, "bold")).grid(row=0, column=3)
            menu = ctk.CTkButton(row, text="▴" if expanded else "⋯", width=34, height=36,
                          corner_radius=10, fg_color="transparent", hover_color="#293448",
                          text_color=MUTED, command=lambda a=account: self.toggle_order_menu(a))
            menu.grid(row=0, column=4, padx=(8, 0))
            self.account_widgets[account_id] = {"game_status": game_status, "card": card, "menu": menu}
            self.render_autocast(card, account)
            if expanded:
                self.create_account_details(account)
                self.account_widgets[account_id]["details"].configure(height=self.account_widgets[account_id]["detail_height"])
        self.update_account_status()
        self.accounts_canvas.update_idletasks()
        self.accounts_canvas.configure(scrollregion=self.accounts_canvas.bbox("all"))
        self.accounts_canvas.yview_moveto(scroll)

    def update_account_status(self) -> None:
        for account in self.config_data["accounts"]:
            account_id = str(account["id"])
            widgets = self.account_widgets.get(account_id)
            if not widgets:
                continue
            active = bool(account.get("wow_pid") or account.get("wow_hwnd"))
            running = account_id in self.autocast_sessions
            def change(widget, **options):
                changed = {k: v for k, v in options.items() if widget.cget(k) != v}
                if changed:
                    widget.configure(**changed)
            change(widgets["game_status"], text="● Spustený" if active else "Vypnutý",
                   text_color="#7dceb0" if active else MUTED)
            change(widgets["start"], text="■  Stop" if running else "▶  Štart",
                   fg_color="#713e4c" if running else "#264b40",
                   hover_color="#8c4b5c" if running else "#326653")
            casts = self.autocast_drafts[account_id]
            summary = f"{casts[0]['key']}  /  {casts[0]['interval']} ms" if len(casts) == 1 else f"{len(casts)} " + ("autocasty" if 2 <= len(casts) <= 4 else "autocastov")
            change(widgets["summary"], text=summary,
                   text_color="#7dceb0" if running else MUTED)
            for entry in widgets.get("entries", []) + widgets.get("cast_buttons", []):
                change(entry, state="disabled" if running else "normal")
            if "technical" in widgets:
                change(widgets["technical"], text=f"PID  {account.get('wow_pid') or '—'}     HWND  {account.get('wow_hwnd') or '—'}")

    def render_autocast(self, card, account: dict) -> None:
        account_id = str(account["id"])
        self.autocast_drafts.setdefault(account_id, account_autocasts(account))
        widgets = self.account_widgets[account_id]
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(bar, text="Autocast", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(52, 12))
        widgets["summary"] = ctk.CTkLabel(bar, text="", text_color=MUTED, font=("Segoe UI", 12))
        widgets["summary"].pack(side="left")
        anti_var = tk.BooleanVar(value=bool(account.get("anti_afk", False)))
        widgets["anti_afk_var"] = anti_var
        ctk.CTkCheckBox(bar, text="Anti-AFK · 5 min", variable=anti_var,
                        command=lambda: self.set_anti_afk(account, anti_var.get()),
                        width=140, height=24, checkbox_width=18, checkbox_height=18,
                        font=("Segoe UI", 11), fg_color="#326653", text_color=MUTED).pack(side="left", padx=16)
        widgets["start"] = ctk.CTkButton(bar, text="", command=lambda: self.toggle_autocast(account),
                                        width=118, height=32, corner_radius=9, font=("Segoe UI", 12, "bold"))
        widgets["start"].pack(side="right", padx=(0, 42))
        ctk.CTkButton(bar, text="Nastaviť", width=78, height=30, fg_color="transparent",
                      hover_color="#293448", text_color=MUTED, corner_radius=8,
                      command=lambda: self.toggle_order_menu(account)).pack(side="right", padx=10)
    def create_account_details(self, account: dict) -> None:
        account_id = str(account["id"])
        widgets = self.account_widgets[account_id]
        if "details" in widgets:
            return
        container = ctk.CTkFrame(widgets["card"], fg_color="transparent", height=1)
        container.pack(fill="x", padx=18, pady=(0, 6))
        container.pack_propagate(False)
        widgets["details"] = container
        editor = ctk.CTkFrame(container, fg_color="transparent")
        editor.pack(fill="x", pady=(0, 12))
        widgets["cast_editor"] = editor
        self.render_cast_editor(account)
        details = ctk.CTkFrame(container, fg_color="#121925", corner_radius=10)
        details.pack(fill="x")
        ctk.CTkLabel(details, text=f"Prihlasovacie meno  ·  {account.get('username', '')}",
                     text_color=MUTED, anchor="w", font=("Segoe UI", 11)).pack(fill="x", padx=14, pady=(10, 0))
        technical = ctk.CTkLabel(details, text="", text_color=MUTED, anchor="w", font=("Consolas", 10))
        technical.pack(fill="x", padx=14, pady=(0, 8))
        widgets["technical"] = technical
        actions = ctk.CTkFrame(details, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 12))
        index = self.config_data["accounts"].index(account)
        for text, action, disabled in (
            ("Upraviť účet", lambda: self.edit_account(account), False),
            ("Posunúť ↑", lambda: self.move_account(index, -1), index == 0),
            ("Posunúť ↓", lambda: self.move_account(index, 1), index == len(self.config_data["accounts"]) - 1),
            ("Odstrániť", lambda: self.delete_account(account), False),
        ):
            button = ctk.CTkButton(actions, text=text, command=action, width=110, height=30,
                                  corner_radius=8, fg_color=PANEL_ALT, hover_color="#293448",
                                  text_color="#dc8f9d" if text == "Odstrániť" else TEXT,
                                  font=("Segoe UI", 11))
            button.pack(side="left", padx=(0, 8))
            if disabled:
                button.configure(state="disabled")

    def render_cast_editor(self, account: dict) -> None:
        account_id = str(account["id"])
        widgets = self.account_widgets[account_id]
        editor = widgets["cast_editor"]
        for child in editor.winfo_children():
            child.destroy()
        widgets["entries"], widgets["cast_buttons"] = [], []
        casts = self.autocast_drafts[account_id]
        for index, draft in enumerate(casts):
            row = ctk.CTkFrame(editor, fg_color="transparent", height=32)
            row.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(row, text=f"{index + 1:02d}", width=28, text_color=MUTED,
                         font=("Segoe UI", 10)).pack(side="left", padx=(4, 8))
            for label, field, width in (("Klávesa", "key", 62), ("ms", "interval", 80)):
                if field == "key":
                    ctk.CTkLabel(row, text=label, text_color=MUTED, font=("Segoe UI", 11)).pack(side="left", padx=(0, 8))
                variable = tk.StringVar(value=draft[field])
                variable.trace_add("write", lambda *_args, v=variable, d=draft, f=field: d.__setitem__(f, v.get()))
                entry = ctk.CTkEntry(row, textvariable=variable, width=width, height=28,
                                     corner_radius=7, fg_color=BG, border_color="#303d52")
                entry.pack(side="left", padx=(0, 8))
                entry.bind("<FocusOut>", lambda _event, item=account: (self.save_autocast_settings(item), self.update_account_status()))
                entry.bind("<Return>", lambda _event, item=account: (self.save_autocast_settings(item, report=True), self.update_account_status()))
                widgets["entries"].append(entry)
            ctk.CTkLabel(row, text="ms", text_color=MUTED, font=("Segoe UI", 11)).pack(side="left")
            remove = ctk.CTkButton(row, text="×", width=28, height=28, corner_radius=7,
                                   fg_color="transparent", hover_color="#713e4c", text_color="#dc8f9d",
                                   command=lambda i=index: self.remove_autocast_slot(account, i))
            remove.pack(side="left", padx=12)
            widgets["cast_buttons"].append(remove)
        add = ctk.CTkButton(editor, text="+  Pridať autocast", width=150, height=28,
                            fg_color=PANEL_ALT, hover_color="#293448", corner_radius=8,
                            command=lambda: self.add_autocast_slot(account))
        add.pack(anchor="w", padx=40, pady=(4, 4))
        widgets["cast_buttons"].append(add)
        widgets["detail_height"] = 160 + 36 * len(casts)

    def add_autocast_slot(self, account: dict) -> None:
        account_id = str(account["id"])
        if account_id in self.autocast_sessions:
            return
        self.autocast_drafts[account_id].append({"key": "3", "interval": "500"})
        self.render_cast_editor(account)
        self.save_autocast_settings(account)
        self.update_account_status()
        self.animate_account_details(account_id, True)

    def remove_autocast_slot(self, account: dict, index: int) -> None:
        account_id = str(account["id"])
        if account_id in self.autocast_sessions:
            return
        casts = self.autocast_drafts[account_id]
        if 0 <= index < len(casts):
            casts.pop(index)
            self.render_cast_editor(account)
            self.save_autocast_settings(account)
            self.update_account_status()
            self.animate_account_details(account_id, True)

    def animate_account_details(self, account_id: str, opened: bool) -> None:
        widgets = self.account_widgets.get(account_id)
        if not widgets or "details" not in widgets:
            return
        if widgets.get("animation"):
            self.after_cancel(widgets["animation"])
        frame = widgets["details"]
        if opened:
            frame.pack(fill="x", padx=18, pady=(0, 6))
        start = float(frame.cget("height"))
        target = widgets["detail_height"] if opened else 1
        started = time.monotonic()
        def step():
            progress = min(1.0, (time.monotonic() - started) / 0.18)
            eased = 1 - (1 - progress) ** 3
            frame.configure(height=max(1, round(start + (target - start) * eased)))
            if progress < 1:
                widgets["animation"] = self.after(16, step)
            else:
                widgets["animation"] = None
                if not opened:
                    frame.pack_forget()
        step()

    def save_autocast_settings(self, account: dict, report: bool = False) -> bool:
        draft = self.autocast_drafts.get(str(account["id"]))
        if draft is None:
            return False
        normalized = []
        try:
            for index, item in enumerate(draft):
                autocast_key(item["key"])
                interval = int(item["interval"])
                if not 100 <= interval <= 3600000:
                    raise ValueError(f"Autocast {index + 1}: interval musí byť od 100 do 3600000 ms.")
                normalized.append({"key": item["key"].strip().upper(), "interval": interval})
        except ValueError as exc:
            if report:
                messagebox.showwarning(APP_NAME, str(exc), parent=self)
            return False
        account["autocasts"] = normalized
        if normalized:
            account["autocast_key"] = normalized[0]["key"]
            account["autocast_interval"] = normalized[0]["interval"]
        self.persist()
        return True

    def set_anti_afk(self, account: dict, enabled: bool) -> None:
        account["anti_afk"] = enabled
        self.persist()
        session_id = "anti:" + str(account["id"])
        if enabled:
            if session_id not in self.autocast_sessions:
                self.toggle_autocast(account, anti_afk=True)
        else:
            self.stop_autocast(session_id)

    def resume_anti_afk(self) -> None:
        for account in self.config_data["accounts"]:
            if account.get("anti_afk") and "anti:" + str(account["id"]) not in self.autocast_sessions:
                self.toggle_autocast(account, anti_afk=True)

    def poll_autocast_hotkey(self) -> None:
        # Edge-triggered: holding the combination must never toggle repeatedly.
        down = all(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000
                   for key in self.autocast_hotkey_keys)
        triggered = down and not self.autocast_hotkey_down
        self.autocast_hotkey_down = down
        try:
            if triggered and not getattr(self, "hotkey_settings_open", False):
                self.toggle_all_autocasts()
        finally:
            self.autocast_hotkey_timer = self.after(50, self.poll_autocast_hotkey)

    def toggle_all_autocasts(self) -> None:
        running = [key for key in self.autocast_sessions if not key.startswith("anti:")]
        if running:
            for account_id in running:
                self.stop_autocast(account_id)
            self.update_account_status()
            self.status.configure(text="● AUTOCASTY VYPNUTÉ · VŠETKY ÚČTY", text_color=MUTED)
            return
        if self.busy:
            self.status.configure(text="● POČKAJ NA DOKONČENIE PRIHLASOVANIA", text_color=GOLD)
            return
        for account in self.config_data["accounts"]:
            if account.get("wow_pid") or account.get("wow_hwnd"):
                self.toggle_autocast(account, quiet=True)
        self.update_account_status()
        count = sum(not key.startswith("anti:") for key in self.autocast_sessions)
        self.status.configure(text=f"● AUTOCASTY ZAPNUTÉ: {count} ÚČTOV" if count else
                              "● ŽIADNY DOSTUPNÝ ÚČET S PLATNÝM AUTOCASTOM", text_color=GOLD if count else MUTED)

    def toggle_autocast(self, account: dict, anti_afk: bool = False, quiet: bool = False) -> None:
        owner_id = str(account["id"])
        account_id = "anti:" + owner_id if anti_afk else owner_id
        if account_id in self.autocast_sessions:
            self.stop_autocast(account_id)
            self.render_accounts()
            return
        if self.busy:
            if anti_afk:
                return
            messagebox.showinfo(APP_NAME, "Počkaj na dokončenie prihlasovania.", parent=self)
            return
        if not anti_afk and not self.save_autocast_settings(account, report=not quiet):
            return
        casts = [{"key": "W", "interval": 300000}] if anti_afk else account_autocasts(account)
        if not casts:
            if quiet:
                return
            messagebox.showinfo(APP_NAME, "Najprv pridaj aspoň jeden autocast cez Nastaviť.", parent=self)
            return
        context = self._account_window_context(account)
        if not context:
            if anti_afk or quiet:
                return  # Saved checkbox will take effect after this account logs in.
            messagebox.showinfo(APP_NAME, "Najprv spusti WoW cez tento účet.", parent=self)
            return
        pid, hwnd = int(context["pid"]), int(context["hwnd"], 16)
        identity = window_identity(hwnd)
        if not identity or identity[0] != pid:
            if anti_afk or quiet:
                return
            messagebox.showinfo(APP_NAME, "WoW okno sa zatvorilo. Spusti účet znova.", parent=self)
            return
        process = self.wow_processes.get(owner_id)
        if process is not None and (process.pid != pid or process.poll() is not None):
            process = None
        kernel32 = ctypes.windll.kernel32
        # Popen already owns a process handle; reopening a protected WoW process can be denied.
        handle = None if process is not None else kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            image_path = ctypes.create_unicode_buffer(32768)
            image_size = wintypes.DWORD(len(image_path))
            if (kernel32.QueryFullProcessImageNameW(handle, 0, image_path, ctypes.byref(image_size))
                    and Path(image_path.value).name.lower() != "wow.exe"):
                kernel32.CloseHandle(handle)
                if not quiet:
                    messagebox.showerror(APP_NAME, "Priradený proces nie je WoW.exe. Spusti účet znova cez launcher.", parent=self)
                return
        self.autocast_sessions[account_id] = {
            "handle": handle, "process": process, "identity": identity, "pid": pid, "hwnd": hwnd,
            "slots": [{"key": autocast_key(item["key"]), "interval": int(item["interval"]),
                       "timer": None, "release_timer": None, "pressed": False,
                       "hold_ms": 60 if anti_afk else 40} for item in casts],
        }
        for index in range(len(casts)):
            if anti_afk:
                self.autocast_sessions[account_id]["slots"][index]["timer"] = self.after(
                    300000, lambda aid=account_id, i=index: self.autocast_tick(aid, i))
            else:
                self.autocast_tick(account_id, index)
        if not quiet:
            self.render_accounts()

    def autocast_tick(self, account_id: str, slot_index: int = 0) -> None:
        session = self.autocast_sessions.get(account_id)
        if not session:
            return
        slot = session["slots"][slot_index]
        code = wintypes.DWORD()
        process = session.get("process")
        if process is not None:
            alive = process.poll() is None
        elif session["handle"]:
            alive = ctypes.windll.kernel32.GetExitCodeProcess(session["handle"], ctypes.byref(code)) and code.value == 259
        else:
            # Without process access stay pinned to the exact original window/thread/class.
            alive = window_identity(session["hwnd"]) == session["identity"]
        if not alive:
            self.stop_autocast(account_id)
            self.render_accounts()
            return
        if visible_window_pid(hex(session["hwnd"])) != session["pid"]:
            hwnd = find_existing_window_for_pid(session["pid"])
            if not hwnd:
                self.stop_autocast(account_id)
                self.render_accounts()
                return
            session["hwnd"] = hwnd
            session["identity"] = window_identity(hwnd)
        try:
            if not self.busy:
                post_autocast_key(session["hwnd"], slot["key"])
                slot["pressed"] = True
                slot["release_timer"] = self.after(slot.get("hold_ms", 40), lambda: self.release_autocast_key(account_id, slot_index))
            slot["timer"] = self.after(slot["interval"], lambda: self.autocast_tick(account_id, slot_index))
        except OSError as exc:
            self.stop_autocast(account_id)
            self.render_accounts()
            self.status.configure(text=f"● AUTOCAST ZASTAVENÝ: {exc}", text_color=DANGER)

    def release_autocast_key(self, account_id: str, slot_index: int = 0) -> None:
        session = self.autocast_sessions.get(account_id)
        if not session:
            return
        slot = session["slots"][slot_index]
        if slot["pressed"]:
            slot["pressed"] = False
            if (visible_window_pid(hex(session["hwnd"])) == session["pid"]
                    and (not session.get("identity") or window_identity(session["hwnd"]) == session["identity"])):
                try:
                    post_autocast_key(session["hwnd"], slot["key"], released=True)
                except OSError as exc:
                    self.stop_autocast(account_id)
                    self.render_accounts()
                    self.status.configure(text=f"● AUTOCAST ZASTAVENÝ: {exc}", text_color=DANGER)

    def stop_autocast(self, account_id: str) -> None:
        session = self.autocast_sessions.get(account_id)
        if not session:
            return
        for index, slot in enumerate(session["slots"]):
            for name in ("timer", "release_timer"):
                if slot[name]:
                    self.after_cancel(slot[name])
            self.release_autocast_key(account_id, index)
        if account_id not in self.autocast_sessions:
            return
        self.autocast_sessions.pop(account_id, None)
        if session["handle"]:
            ctypes.windll.kernel32.CloseHandle(session["handle"])

    def destroy(self) -> None:
        if getattr(self, "autocast_hotkey_timer", None):
            self.after_cancel(self.autocast_hotkey_timer)
        if getattr(self, "background_resize_timer", None):
            self.after_cancel(self.background_resize_timer)
        for widgets in getattr(self, "account_widgets", {}).values():
            if widgets.get("animation"):
                self.after_cancel(widgets["animation"])
        for account_id in list(getattr(self, "autocast_sessions", {})):
            self.stop_autocast(account_id)
        for account in getattr(self, "config_data", {}).get("accounts", []):
            if str(account.get("id", "")) in getattr(self, "autocast_drafts", {}):
                self.save_autocast_settings(account)
        super().destroy()

    def add_account(self) -> None:
        dialog = AccountDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.config_data["accounts"].append(dialog.result)
            self.persist()
            self.render_accounts()

    def edit_account(self, account: dict) -> None:
        dialog = AccountDialog(self, account)
        self.wait_window(dialog)
        if dialog.result:
            index = self.config_data["accounts"].index(account)
            account.update(dialog.result)
            self.persist()
            self.render_accounts()

    def delete_account(self, account: dict) -> None:
        if messagebox.askyesno(APP_NAME, f"Odstrániť účet „{account['name']}“?", parent=self):
            self.stop_autocast(str(account["id"]))
            self.stop_autocast("anti:" + str(account["id"]))
            self.autocast_drafts.pop(str(account["id"]), None)
            self.wow_processes.pop(str(account["id"]), None)
            self.config_data["accounts"].remove(account)
            self.persist()
            self.render_accounts()

    def move_account(self, index: int, direction: int) -> None:
        accounts = self.config_data["accounts"]
        new_index = index + direction
        if new_index < 0 or new_index >= len(accounts):
            return
        accounts[index], accounts[new_index] = accounts[new_index], accounts[index]
        self.persist()
        self.render_accounts()

    def toggle_order_menu(self, account: dict) -> None:
        account_id = str(account["id"])
        previous = self.open_order_account_id
        if previous and previous in self.account_widgets:
            self.account_widgets[previous]["menu"].configure(text="⋯")
            self.animate_account_details(previous, False)
            previous_account = next((a for a in self.config_data["accounts"] if str(a["id"]) == previous), None)
            if previous_account:
                self.save_autocast_settings(previous_account)
        self.open_order_account_id = "" if previous == account_id else account_id
        if self.open_order_account_id:
            self.create_account_details(account)
            self.account_widgets[account_id]["menu"].configure(text="▴")
            self.animate_account_details(account_id, True)
        self.update_account_status()

    def open_settings(self) -> None:
        window = ctk.CTkToplevel(self)
        self.hotkey_settings_open = True
        window.bind("<Destroy>", lambda event: setattr(self, "hotkey_settings_open", False)
                    if event.widget is window else None, add="+")
        window.title(f"Nastavenia • {APP_NAME}")
        window.configure(fg_color=PANEL)
        window.geometry("700x720")
        window.resizable(False, False)
        window.transient(self)
        window.grid_columnconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(window, fg_color=PANEL, corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text="NASTAVENIA LAUNCHERU", text_color=TEXT,
                     font=("Segoe UI", 19, "bold")).grid(row=0, column=0, columnspan=2, padx=24, pady=(22, 4), sticky="w")
        ctk.CTkLabel(body, text="Cesty k hre a správanie automatického prihlásenia",
                     text_color=MUTED, font=("Segoe UI", 11)).grid(row=1, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="w")

        ctk.CTkLabel(body, text="CESTA K WOW.EXE", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=2, column=0, padx=24, pady=(0, 6), sticky="w")
        path_text = tk.StringVar(value=self.config_data.get("wow_path", "Nenastavená"))
        ctk.CTkEntry(body, textvariable=path_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=3, column=0, padx=(24, 10), sticky="ew")
        ctk.CTkButton(body, text="VYBRAŤ", width=100, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_wow_path(), path_text.set(self.config_data.get("wow_path", "")))).grid(row=3, column=1, padx=(0, 24))

        ctk.CTkLabel(body, text="OFICIÁLNY GIGAFUN LAUNCHER", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=4, column=0, padx=24, pady=(18, 6), sticky="w")
        official_text = tk.StringVar(value=self.config_data.get("official_launcher_path", "Nenastavená"))
        ctk.CTkEntry(body, textvariable=official_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=5, column=0, padx=(24, 10), sticky="ew")
        ctk.CTkButton(body, text="VYBRAŤ", width=100, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_official_launcher(), official_text.set(self.config_data.get("official_launcher_path", "")))).grid(row=5, column=1, padx=(0, 24))

        ctk.CTkLabel(body, text="WOWOPENBOX PRIEČINOK", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=6, column=0, padx=24, pady=(18, 6), sticky="w")
        wob_text = tk.StringVar(value=self.config_data.get("wowopenbox_path", "Nenastavený"))
        ctk.CTkEntry(body, textvariable=wob_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=7, column=0, padx=(24, 10), sticky="ew")
        ctk.CTkButton(body, text="VYBRAŤ", width=100, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_wowopenbox_path(), wob_text.set(self.config_data.get("wowopenbox_path", "")))).grid(row=7, column=1, padx=(0, 24))

        ctk.CTkLabel(body, text="AUTOCLICKER EXE", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=8, column=0, padx=24, pady=(18, 6), sticky="w")
        clicker_text = tk.StringVar(value=self.config_data.get("autoclicker_path", "Nenastavený"))
        ctk.CTkEntry(body, textvariable=clicker_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=9, column=0, padx=(24, 10), sticky="ew")
        ctk.CTkButton(body, text="VYBRAŤ", width=100, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_external_tool_path("autoclicker_path", "AUTOCLICKER"), clicker_text.set(self.config_data.get("autoclicker_path", "")))).grid(row=9, column=1, padx=(0, 24))

        ctk.CTkLabel(body, text="POZADIE LAUNCHERU", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=12, column=0, padx=24, pady=(18, 6), sticky="w")
        background_text = tk.StringVar(value=self.config_data.get("background_path", "") or "Default Nemesis pozadie")
        ctk.CTkEntry(body, textvariable=background_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=13, column=0, padx=(24, 10), sticky="ew")
        background_buttons = ctk.CTkFrame(body, fg_color="transparent")
        background_buttons.grid(row=13, column=1, padx=(0, 24), sticky="ew")
        ctk.CTkButton(background_buttons, text="VYBRAŤ", width=72, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_background_path(), background_text.set(self.config_data.get("background_path", "") or "Default Nemesis pozadie"))).pack(side="left")
        ctk.CTkButton(background_buttons, text="RESET", width=66, height=38, corner_radius=8,
                      fg_color="#282b2d", hover_color="#373b3e",
                      command=lambda: (self.reset_background_path(), background_text.set("Default Nemesis pozadie"))).pack(side="left", padx=(6, 0))

        ctk.CTkLabel(body, text="POSLEDNÉ WOW OKNO", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=14, column=0, padx=24, pady=(18, 6), sticky="w")
        last_window = (
            f"HWND {self.config_data.get('last_wow_hwnd') or '-'}"
            f"   PID {self.config_data.get('last_wow_pid') or '-'}"
            f"   Účet {self.config_data.get('last_wow_account') or '-'}"
        )
        ctk.CTkEntry(body, textvariable=tk.StringVar(value=last_window), height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=15, column=0, columnspan=2, padx=24, sticky="ew")

        timing = ctk.CTkFrame(body, fg_color="#151816", corner_radius=10)
        timing.grid(row=16, column=0, columnspan=2, padx=24, pady=20, sticky="ew")
        timing.grid_columnconfigure((0, 1), weight=1)
        timeout = tk.StringVar(value=str(int(self.config_data.get("window_timeout", 30))))
        delay = tk.StringVar(value=str(float(self.config_data.get("ready_delay", 3))))
        click_x = tk.StringVar(value=str(int(self.config_data.get("login_click_x", 50))))
        click_y = tk.StringVar(value=str(int(self.config_data.get("login_click_y", 48))))
        ctk.CTkLabel(timing, text="TIMEOUT OKNA (s)", text_color=MUTED,
                     font=("Segoe UI", 8, "bold")).grid(row=0, column=0, padx=16, pady=(14, 5), sticky="w")
        ctk.CTkLabel(timing, text="ONESKORENIE LOGINU (s)", text_color=MUTED,
                     font=("Segoe UI", 8, "bold")).grid(row=0, column=1, padx=16, pady=(14, 5), sticky="w")
        ctk.CTkEntry(timing, textvariable=timeout, height=36, corner_radius=8,
                     fg_color="#0d0f0e", border_color="#354237").grid(row=1, column=0, padx=16, pady=(0, 14), sticky="ew")
        ctk.CTkEntry(timing, textvariable=delay, height=36, corner_radius=8,
                     fg_color="#0d0f0e", border_color="#354237").grid(row=1, column=1, padx=16, pady=(0, 14), sticky="ew")
        ctk.CTkLabel(timing, text="LOGIN X (%)", text_color=MUTED,
                     font=("Segoe UI", 8, "bold")).grid(row=2, column=0, padx=16, pady=(4, 5), sticky="w")
        ctk.CTkLabel(timing, text="LOGIN Y (%)", text_color=MUTED,
                     font=("Segoe UI", 8, "bold")).grid(row=2, column=1, padx=16, pady=(4, 5), sticky="w")
        ctk.CTkEntry(timing, textvariable=click_x, height=36, corner_radius=8,
                     fg_color="#0d0f0e", border_color="#354237").grid(row=3, column=0, padx=16, pady=(0, 14), sticky="ew")
        ctk.CTkEntry(timing, textvariable=click_y, height=36, corner_radius=8,
                     fg_color="#0d0f0e", border_color="#354237").grid(row=3, column=1, padx=16, pady=(0, 14), sticky="ew")
        close_after = tk.BooleanVar(value=bool(self.config_data.get("close_after_login", False)))
        ctk.CTkSwitch(body, text="Po odoslaní prihlásenia zavrieť launcher", variable=close_after,
                      progress_color="#4b9a53", button_color="#e0b326").grid(row=17, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="w")

        hotkey_text = tk.StringVar(value=self.config_data.get("autocast_hotkey", "Ctrl+Alt+F8"))
        ctk.CTkLabel(body, text="SKRATKA PRE AUTOCASTY SPUSTENÝCH ÚČTOV", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=18, column=0, columnspan=2, padx=24, pady=(0, 6), sticky="w")
        ctk.CTkEntry(body, textvariable=hotkey_text, height=36, corner_radius=8,
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=19, column=0, columnspan=2, padx=24, sticky="ew")
        ctk.CTkLabel(body, text="Napr. F8 alebo Ctrl+Alt+F8 · stlačenie zapne, ďalšie vypne.",
                     text_color=MUTED, font=("Segoe UI", 11)).grid(row=20, column=0, columnspan=2, padx=24, pady=(4, 18), sticky="w")

        def save() -> None:
            try:
                hotkey_label, hotkey_keys = global_autocast_hotkey(hotkey_text.get())
            except ValueError as exc:
                messagebox.showwarning(APP_NAME, str(exc), parent=window)
                return
            try:
                self.config_data["window_timeout"] = max(5, int(timeout.get()))
                self.config_data["ready_delay"] = max(0.5, float(delay.get()))
                self.config_data["login_click_x"] = min(95, max(5, int(click_x.get())))
                self.config_data["login_click_y"] = min(95, max(5, int(click_y.get())))
            except (ValueError, tk.TclError):
                messagebox.showwarning(APP_NAME, "Zadaj platné číselné hodnoty.", parent=window)
                return
            self.config_data["close_after_login"] = close_after.get()
            self.config_data["autocast_hotkey"] = hotkey_label
            self.autocast_hotkey_keys = hotkey_keys
            self.autocast_hotkey_down = True
            self.all_autocasts_button.configure(text=f"Autocasty · {hotkey_label}")
            self.persist()
            window.destroy()

        ctk.CTkButton(body, text="ULOŽIŤ NASTAVENIA", command=save, width=190, height=42,
                      corner_radius=10, fg_color="#d6a91d", hover_color="#f0c532",
                      text_color="#090b09", font=("Segoe UI", 10, "bold")).grid(row=21, column=0, columnspan=2, padx=24, pady=(0, 22), sticky="e")

    def persist(self) -> None:
        try:
            save_config(self.config_data)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Konfiguráciu sa nepodarilo uložiť:\n{exc}", parent=self)

    def launch(self, account: dict) -> None:
        if self.busy:
            return
        self.stop_autocast("anti:" + str(account["id"]))
        if str(account["id"]) in self.autocast_sessions:
            self.stop_autocast(str(account["id"]))
            self.render_accounts()
        try:
            import pyautogui  # noqa: F401
        except ImportError as exc:
            messagebox.showerror(
                APP_NAME,
                "Chýba knižnica PyAutoGUI, preto launcher nevie automaticky vyplniť login.\n\n"
                "Ak appku spúšťaš zo zdrojového kódu, spusti:\n"
                "python -m pip install -r requirements.txt\n\n"
                "Ak používaš EXE, pregeneruj ho cez build.bat.",
                parent=self,
            )
            return
        if not self.valid_wow_path():
            messagebox.showwarning(APP_NAME, "Nastav platnú cestu k WoW.exe.", parent=self)
            self.choose_wow_path()
            return
        if not self.ensure_realmlist():
            return
        try:
            password = unprotect_secret(account["password"])
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Heslo sa nepodarilo odomknúť:\n{exc}", parent=self)
            return
        self.busy = True
        self.status.configure(text=f"●  SPÚŠŤAM {account['name'].upper()}…", text_color=GOLD)
        threading.Thread(
            target=self._login_worker,
            args=(account.get("id", ""), account["name"], account["username"], password),
            daemon=True,
        ).start()

    def _login_worker(self, account_id: str, account_name: str, username: str, password: str) -> None:
        try:
            import pyautogui

            wow_path = Path(self.config_data["wow_path"])
            process = subprocess.Popen([str(wow_path)], cwd=str(wow_path.parent))
            self.wow_processes[account_id] = process
            hwnd = find_window_for_pid(process.pid, float(self.config_data.get("window_timeout", 30)))
            if not hwnd:
                raise TimeoutError("Okno World of Warcraft sa v nastavenom čase nezobrazilo.")
            hwnd_hex = f"0x{hwnd:08X}"
            self.config_data["last_wow_hwnd"] = hwnd_hex
            self.config_data["last_wow_pid"] = str(process.pid)
            self.config_data["last_wow_account_id"] = account_id
            self.config_data["last_wow_account"] = account_name
            self.config_data["last_wow_username"] = username
            self.set_account_window(account_id, str(process.pid), hwnd_hex)
            self.persist()
            self.after(0, self.render_accounts)
            self.after(0, lambda: self.status.configure(text="●  ČAKÁM NA WOW…", text_color=GOLD))
            time.sleep(float(self.config_data.get("ready_delay", 3)))
            activate_window(hwnd)
            time.sleep(0.8)
            rect = get_window_rect(hwnd)
            if rect:
                left, top, right, bottom = rect
                x_ratio = min(95, max(5, int(self.config_data.get("login_click_x", 50)))) / 100
                y_ratio = min(95, max(5, int(self.config_data.get("login_click_y", 48)))) / 100
                pyautogui.click(left + int((right - left) * x_ratio), top + int((bottom - top) * y_ratio))
                time.sleep(0.15)
            activate_window(hwnd)
            time.sleep(0.15)
            pyautogui.hotkey("ctrl", "a")
            paste_text(pyautogui, username)
            pyautogui.press("tab")
            paste_text(pyautogui, password)
            pyautogui.press("enter")
            if self.config_data.get("close_after_login", False):
                self.after(0, self.destroy)
            else:
                self.after(0, lambda: self._finish_login(f"Login odoslaný • HWND {hwnd_hex} • PID {process.pid}"))
        except Exception as exc:
            self.after(0, lambda error=exc: self._login_failed(error))
        finally:
            password = ""

    def _finish_login(self, text: str) -> None:
        self.busy = False
        self.resume_anti_afk()
        self.status.configure(text=f"●  {text.upper()}", text_color=MUTED)
        self.render_accounts()

    def _login_failed(self, error: Exception) -> None:
        self._finish_login("Prihlásenie zlyhalo")
        messagebox.showerror(APP_NAME, str(error), parent=self)


if __name__ == "__main__":
    Launcher().mainloop()
