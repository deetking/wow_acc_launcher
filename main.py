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

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))
import customtkinter as ctk

ctk.set_appearance_mode("dark")


APP_BASE_NAME = "WoW Nemesis Launcher"
APP_VERSION = "1.7.6"
APP_AUTHOR = "Bc. Juraj Pekarík"
APP_NAME = f"{APP_BASE_NAME} v{APP_VERSION}"
REALMLIST = "gigafun.project-nemesis.cz"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WoWNemesisLauncher"
CONFIG_FILE = CONFIG_DIR / "config.json"

BG = "#090b0e"
PANEL = "#111318"
PANEL_ALT = "#17191e"
GOLD = "#d9a51d"
GOLD_HOVER = "#efbd32"
GOLD_DARK = "#7f641d"
TEXT = "#f4f1e8"
MUTED = "#a7a39a"
DANGER = "#9d4038"


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
        "autocast_path": "",
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
            border_width=0,
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
        self.columnconfigure(1, weight=1)

        for row, label in enumerate(("NÁZOV ÚČTU", "USERNAME", "REGISTROVANÝ E-MAIL", "HESLO")):
            ctk.CTkLabel(self, text=label, text_color=MUTED,
                         font=("Segoe UI", 10, "bold")).grid(row=row, column=0, padx=(22, 14), pady=(16 if row == 0 else 7, 7), sticky="w")
        entry_options = dict(width=300, height=38, corner_radius=9, fg_color=PANEL_ALT,
                             border_color="#355137", border_width=1, text_color=TEXT)
        self.name = ctk.CTkEntry(self, placeholder_text="napr. Warrior", **entry_options)
        self.username = ctk.CTkEntry(self, placeholder_text="prihlasovacie meno", **entry_options)
        self.email = ctk.CTkEntry(self, placeholder_text="voliteľné", **entry_options)
        self.password = ctk.CTkEntry(self, placeholder_text="heslo", show="•", **entry_options)
        self.name.grid(row=0, column=1, padx=(0, 22), pady=(16, 7))
        self.username.grid(row=1, column=1, padx=(0, 22), pady=7)
        self.email.grid(row=2, column=1, padx=(0, 22), pady=7)
        self.password.grid(row=3, column=1, padx=(0, 22), pady=7)
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
        self.geometry("1100x680")
        self.minsize(900, 600)
        self.configure(fg_color=BG)
        self.config_data = load_config()
        self.busy = False

        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        try:
            from PIL import Image, ImageTk

            self.background_source = Image.open(resource_path("assets/nemesis_background_v2.png")).convert("RGB")
            artwork = self.background_source.resize((1100, 680), Image.Resampling.LANCZOS)
            self.background_image = ImageTk.PhotoImage(artwork)
            self.background_id = self.canvas.create_image(0, 0, image=self.background_image, anchor="center")
        except (ImportError, OSError, tk.TclError):
            self.background_source = None
            self.background_image = None
            self.background_id = None
        topbar = ctk.CTkFrame(self.canvas, fg_color="#0c0c0b", corner_radius=0,
                              border_color="#263b25", border_width=1)
        self.topbar_window = self.canvas.create_window(0, 0, window=topbar, anchor="nw", width=1100, height=78)
        nav = ctk.CTkFrame(topbar, fg_color="transparent")
        nav.pack(side="left", padx=12, fill="y")
        for text, command in (
            ("ÚČTY", lambda: self.accounts_canvas.yview_moveto(0)),
            ("UPDATER", self.launch_official_updater),
            ("WOB", self.launch_wowopenbox),
            ("STOP WOB", self.stop_wowopenbox),
            ("CLICK", lambda: self.launch_external_tool("autoclicker_path", "AUTOCLICKER")),
            ("CAST", lambda: self.launch_external_tool("autocast_path", "AUTOCAST")),
            ("SETTINGS", self.open_settings),
        ):
            nav_width = 86 if text == "STOP WOB" else 68 if text in {"WOB", "CLICK", "CAST"} else 78
            ctk.CTkButton(nav, text=text, command=command, width=nav_width,
                          height=36, corner_radius=7, fg_color="transparent", hover_color="#172019",
                          text_color="#f2eadc", font=("Segoe UI", 10, "bold")).pack(side="left", padx=2, pady=20)
        brand_box = ctk.CTkFrame(topbar, fg_color="transparent")
        brand_box.pack(side="right", padx=24, pady=14)
        ctk.CTkLabel(brand_box, text=APP_NAME, fg_color="transparent", text_color="#d7cfbd",
                     font=("Segoe UI", 12, "bold")).pack(anchor="e")
        ctk.CTkLabel(brand_box, text="GIGAFUN • ACCOUNT MANAGER", fg_color="transparent", text_color="#5db965",
                     font=("Segoe UI", 9, "bold")).pack(anchor="e")

        self.notice_id = self.canvas.create_text(24, 104, text=f"Launcher • Version {APP_VERSION}",
                                                  fill="#d3cec2", anchor="w",
                                                  font=("Segoe UI", 11, "bold"))
        self.notice_line = self.canvas.create_line(20, 91, 20, 117, fill="#63c66b", width=2)
        self.brand_id = self.canvas.create_text(550, 150, text="GIGAFUN", fill="#d5a51d",
                                                 font=("Georgia", 38, "bold"))
        self.brand_subtitle_id = self.canvas.create_text(550, 181, text="NEMESIS ACCOUNT LAUNCHER",
                                                          fill="#9bef9f", font=("Segoe UI", 10, "bold"))

        accounts_panel = ctk.CTkFrame(self.canvas, fg_color="#0c0e0c", corner_radius=12,
                                      border_color="#30452f", border_width=1)
        self.accounts_panel_window = self.canvas.create_window(550, 205, window=accounts_panel,
                                                                anchor="n", width=690, height=365)
        section = ctk.CTkFrame(accounts_panel, fg_color="transparent", corner_radius=0)
        section.pack(fill="x", padx=22, pady=12)
        ctk.CTkLabel(section, text="MOJE ÚČTY", text_color="#74c97a",
                     font=("Segoe UI", 11, "bold")).pack(side="left")
        ctk.CTkLabel(section, text="Vyber účet a spusti hru", text_color="#6f6c64",
                     font=("Segoe UI", 10, "bold")).pack(side="right")
        ctk.CTkFrame(accounts_panel, fg_color="#263b25", height=1, corner_radius=0).pack(fill="x")
        accounts_area = ctk.CTkFrame(accounts_panel, fg_color="#0c0e0c", corner_radius=0)
        accounts_area.pack(fill="both", expand=True)
        self.accounts_canvas = tk.Canvas(accounts_area, bg=PANEL, highlightthickness=0, bd=0)
        accounts_scrollbar = ctk.CTkScrollbar(
            accounts_area, orientation="vertical", command=self.accounts_canvas.yview,
            width=10, fg_color="#0c0e0c", button_color="#355137", button_hover_color="#5b8f60",
        )
        self.accounts_canvas.configure(yscrollcommand=accounts_scrollbar.set)
        accounts_scrollbar.pack(side="right", fill="y", padx=(0, 8))
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
        self.footer_window = self.canvas.create_window(0, 680, window=footer, anchor="sw", width=1100, height=76)
        self._gold_button(footer, "+  PRIDAŤ ÚČET", self.add_account, width=18).pack(side="left", padx=24, pady=16)
        footer_meta = ctk.CTkFrame(footer, fg_color="transparent")
        footer_meta.pack(side="right", padx=24, pady=12)
        self.status = ctk.CTkLabel(
            footer_meta, text="●  PRIPRAVENÉ", text_color="#c7c2b6",
            font=("Segoe UI", 10, "bold"), wraplength=340,
        )
        self.status.pack(anchor="e")
        ctk.CTkLabel(footer_meta, text=f"© {APP_AUTHOR}", text_color="#5b5a56",
                     font=("Segoe UI", 7)).pack(anchor="e")
        self.canvas.bind("<Configure>", self._resize_background)
        self.render_accounts()
        self.after(100, self.first_run)
        self.after(500, self.refresh_wob_status)
        self.after(1500, self.watch_last_wow_window)

    def _resize_background(self, event: tk.Event) -> None:
        required = ("topbar_window", "accounts_panel_window", "footer_window", "brand_id", "brand_subtitle_id")
        if not all(attribute in self.__dict__ for attribute in required):
            return
        if self.background_id:
            self._fit_background(event.width, event.height)
        self.canvas.itemconfigure(self.topbar_window, width=event.width)
        compact = event.height < 650
        brand_y = 136 if compact else 150
        subtitle_y = 164 if compact else 181
        panel_y = 188 if compact else 205
        footer_height = 76
        panel_width = max(620, min(690, event.width - 110))
        panel_height = max(230, min(365, event.height - panel_y - footer_height - 28))
        self.canvas.coords(self.accounts_panel_window, event.width / 2, panel_y)
        self.canvas.itemconfigure(self.accounts_panel_window, width=panel_width, height=panel_height)
        self.canvas.coords(self.footer_window, 0, event.height)
        self.canvas.itemconfigure(self.footer_window, width=event.width)
        self.canvas.coords(self.brand_id, event.width / 2, brand_y)
        self.canvas.coords(self.brand_subtitle_id, event.width / 2, subtitle_y)

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
        return RoundedButton(parent, text, command, max(120, width * 10), 44, GOLD, GOLD_HOVER,
                             BG, ("Segoe UI", 11, "bold"), radius=10)

    def _dark_button(self, parent: tk.Misc, text: str, command, width: int = 10, danger: bool = False) -> RoundedButton:
        color = DANGER if danger else PANEL_ALT
        hover = "#b94b42" if danger else "#263b25"
        return RoundedButton(parent, text, command, max(38, width * 9), 36, color, hover,
                             TEXT, ("Segoe UI", 9, "bold"), radius=8)

    def refresh_wob_status(self) -> None:
        if list_named_processes(("wob2025", "openmultiboxing", "wowopenbox")):
            self.status.configure(text="●  WOWOPENBOX BEŽÍ", text_color=GOLD)

    def clear_last_wow_window(self) -> None:
        self.config_data["last_wow_hwnd"] = ""
        self.config_data["last_wow_pid"] = ""
        self.config_data["last_wow_account_id"] = ""
        self.config_data["last_wow_account"] = ""
        self.config_data["last_wow_username"] = ""
        self.persist()
        self.render_accounts()

    def watch_last_wow_window(self) -> None:
        pid = str(self.config_data.get("last_wow_pid", ""))
        hwnd = str(self.config_data.get("last_wow_hwnd", ""))
        if pid or hwnd:
            if not process_exists(pid):
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

    def launch_external_tool(self, config_key: str, title: str) -> None:
        configured = Path(self.config_data.get(config_key, ""))
        if not valid_exe_path(str(configured)):
            messagebox.showinfo(APP_NAME, f"Najprv namapuj {title} .exe v Nastaveniach.", parent=self)
            self.choose_external_tool_path(config_key, title)
            configured = Path(self.config_data.get(config_key, ""))
        if not valid_exe_path(str(configured)):
            return
        try:
            env = os.environ.copy()
            env.update(
                {
                    "WOW_NEMESIS_LAST_HWND": str(self.config_data.get("last_wow_hwnd", "")),
                    "WOW_NEMESIS_LAST_PID": str(self.config_data.get("last_wow_pid", "")),
                    "WOW_NEMESIS_LAST_ACCOUNT": str(self.config_data.get("last_wow_account", "")),
                    "WOW_NEMESIS_LAST_USERNAME": str(self.config_data.get("last_wow_username", "")),
                    "WOW_NEMESIS_CONFIG": str(CONFIG_FILE),
                }
            )
            subprocess.Popen([str(configured)], cwd=str(configured.parent), env=env)
            self.status.configure(text=f"●  {title} SPUSTENÝ", text_color=GOLD)
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

    def render_accounts(self) -> None:
        for child in self.accounts_frame.winfo_children():
            child.destroy()
        accounts = self.config_data["accounts"]
        if not accounts:
            ctk.CTkLabel(
                self.accounts_frame,
                text="Zatiaľ nemáš uložený žiadny účet.\nKlikni na „Pridať účet“.",
                justify="center",
                fg_color=PANEL,
                text_color=MUTED,
                font=("Segoe UI", 11),
            ).pack(expand=True, pady=70)
            return
        for account in accounts:
            row = ctk.CTkFrame(self.accounts_frame, fg_color=PANEL_ALT, corner_radius=10,
                               border_color="#303833", border_width=1)
            row.pack(fill="x", padx=22, pady=5)
            launch_text = f"▶   {account['name'].upper()}"
            last_account_id = str(self.config_data.get("last_wow_account_id", ""))
            last_account_name = str(self.config_data.get("last_wow_account", ""))
            last_username = str(self.config_data.get("last_wow_username", ""))
            is_last_account = (
                (last_account_id and str(account.get("id", "")) == last_account_id)
                or (not last_account_id and account.get("name") == last_account_name)
                or (not last_account_id and last_username and account.get("username") == last_username)
            )
            if is_last_account:
                last_pid = self.config_data.get("last_wow_pid")
                last_hwnd = self.config_data.get("last_wow_hwnd")
                if last_pid:
                    launch_text = f"{launch_text}   |   PID {last_pid}"
                if last_hwnd:
                    launch_text = f"{launch_text}   |   {last_hwnd}"
            launch = self._gold_button(row, launch_text, lambda item=account: self.launch(item), width=36)
            launch.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=account.get("username", ""), text_color=MUTED,
                         font=("Segoe UI", 11, "bold"), width=135, anchor="w").pack(side="left", padx=12, fill="y")
            self._dark_button(row, "UPRAVIŤ", lambda item=account: self.edit_account(item), width=9).pack(side="left", padx=4, pady=5)
            self._dark_button(row, "×", lambda item=account: self.delete_account(item), width=3, danger=True).pack(side="left", padx=(0, 5), pady=5)
        self.accounts_canvas.yview_moveto(0)

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
            self.config_data["accounts"][index] = dialog.result
            self.persist()
            self.render_accounts()

    def delete_account(self, account: dict) -> None:
        if messagebox.askyesno(APP_NAME, f"Odstrániť účet „{account['name']}“?", parent=self):
            self.config_data["accounts"].remove(account)
            self.persist()
            self.render_accounts()

    def open_settings(self) -> None:
        window = ctk.CTkToplevel(self)
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
                     text_color=MUTED, font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="w")

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

        ctk.CTkLabel(body, text="AUTOCAST EXE", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=10, column=0, padx=24, pady=(18, 6), sticky="w")
        autocast_text = tk.StringVar(value=self.config_data.get("autocast_path", "Nenastavený"))
        ctk.CTkEntry(body, textvariable=autocast_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=11, column=0, padx=(24, 10), sticky="ew")
        ctk.CTkButton(body, text="VYBRAŤ", width=100, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_external_tool_path("autocast_path", "AUTOCAST"), autocast_text.set(self.config_data.get("autocast_path", "")))).grid(row=11, column=1, padx=(0, 24))

        ctk.CTkLabel(body, text="POSLEDNÉ WOW OKNO", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=12, column=0, padx=24, pady=(18, 6), sticky="w")
        last_window = (
            f"HWND {self.config_data.get('last_wow_hwnd') or '-'}"
            f"   PID {self.config_data.get('last_wow_pid') or '-'}"
            f"   Účet {self.config_data.get('last_wow_account') or '-'}"
        )
        ctk.CTkEntry(body, textvariable=tk.StringVar(value=last_window), height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=13, column=0, columnspan=2, padx=24, sticky="ew")

        timing = ctk.CTkFrame(body, fg_color="#151816", corner_radius=10)
        timing.grid(row=14, column=0, columnspan=2, padx=24, pady=20, sticky="ew")
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
                      progress_color="#4b9a53", button_color="#e0b326").grid(row=15, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="w")

        def save() -> None:
            try:
                self.config_data["window_timeout"] = max(5, int(timeout.get()))
                self.config_data["ready_delay"] = max(0.5, float(delay.get()))
                self.config_data["login_click_x"] = min(95, max(5, int(click_x.get())))
                self.config_data["login_click_y"] = min(95, max(5, int(click_y.get())))
            except (ValueError, tk.TclError):
                messagebox.showwarning(APP_NAME, "Zadaj platné číselné hodnoty.", parent=window)
                return
            self.config_data["close_after_login"] = close_after.get()
            self.persist()
            window.destroy()

        ctk.CTkButton(body, text="ULOŽIŤ NASTAVENIA", command=save, width=190, height=42,
                      corner_radius=10, fg_color="#d6a91d", hover_color="#f0c532",
                      text_color="#090b09", font=("Segoe UI", 10, "bold")).grid(row=16, column=0, columnspan=2, padx=24, pady=(0, 22), sticky="e")

    def persist(self) -> None:
        try:
            save_config(self.config_data)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Konfiguráciu sa nepodarilo uložiť:\n{exc}", parent=self)

    def launch(self, account: dict) -> None:
        if self.busy:
            return
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
            hwnd = find_window_for_pid(process.pid, float(self.config_data.get("window_timeout", 30)))
            if not hwnd:
                raise TimeoutError("Okno World of Warcraft sa v nastavenom čase nezobrazilo.")
            hwnd_hex = f"0x{hwnd:08X}"
            self.config_data["last_wow_hwnd"] = hwnd_hex
            self.config_data["last_wow_pid"] = str(process.pid)
            self.config_data["last_wow_account_id"] = account_id
            self.config_data["last_wow_account"] = account_name
            self.config_data["last_wow_username"] = username
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
        self.status.configure(text=f"●  {text.upper()}", text_color=MUTED)

    def _login_failed(self, error: Exception) -> None:
        self._finish_login("Prihlásenie zlyhalo")
        messagebox.showerror(APP_NAME, str(error), parent=self)


if __name__ == "__main__":
    Launcher().mainloop()
