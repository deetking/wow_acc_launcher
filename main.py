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
APP_VERSION = "1.4.1"
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
        "window_timeout": 30,
        "ready_delay": 3.0,
        "close_after_login": True,
        "accounts": [],
    }


def load_config() -> dict:
    config = default_config()
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            config.update(saved)
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


def activate_window(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


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

            artwork = Image.open(resource_path("assets/nemesis_background_v2.png"))
            artwork = artwork.resize((1100, 680), Image.Resampling.LANCZOS)
            self.background_image = ImageTk.PhotoImage(artwork)
            self.background_id = self.canvas.create_image(0, 0, image=self.background_image, anchor="center")
        except (ImportError, OSError, tk.TclError):
            self.background_image = None
            self.background_id = None
        topbar = ctk.CTkFrame(self.canvas, fg_color="#0c0c0b", corner_radius=0,
                              border_color="#263b25", border_width=1)
        self.topbar_window = self.canvas.create_window(0, 0, window=topbar, anchor="nw", width=1100, height=75)
        nav = ctk.CTkFrame(topbar, fg_color="transparent")
        nav.pack(side="left", padx=14, fill="y")
        for text, command in (
            ("ÚČTY", lambda: self.accounts_canvas.yview_moveto(0)),
            ("OFICIÁLNY UPDATER", self.launch_official_updater),
            ("NASTAVENIA", self.open_settings),
        ):
            ctk.CTkButton(nav, text=text, command=command, width=105 if text != "OFICIÁLNY UPDATER" else 155,
                          height=40, corner_radius=7, fg_color="transparent", hover_color="#172019",
                          text_color="#c5c0b5", font=("Segoe UI", 9, "bold")).pack(side="left", padx=3, pady=17)
        ctk.CTkLabel(topbar, text=APP_NAME, fg_color="transparent", text_color="#aaa397",
                     font=("Segoe UI", 11, "bold")).place(relx=.5, rely=.3, anchor="center")
        ctk.CTkLabel(topbar, text="GIGAFUN • ACCOUNT MANAGER", fg_color="transparent", text_color="#4d8050",
                     font=("Segoe UI", 8, "bold")).place(relx=.5, rely=.67, anchor="center")

        self.notice_id = self.canvas.create_text(18, 98, text=f"Launcher • Version {APP_VERSION}",
                                                  fill="#d3cec2", anchor="w",
                                                  font=("Segoe UI", 10, "bold"))
        self.notice_line = self.canvas.create_line(14, 86, 14, 112, fill="#63c66b", width=2)
        self.brand_id = self.canvas.create_text(550, 150, text="GIGAFUN", fill="#d5a51d",
                                                 font=("Georgia", 34, "bold"))
        self.brand_subtitle_id = self.canvas.create_text(550, 181, text="NEMESIS ACCOUNT LAUNCHER",
                                                          fill="#82d287", font=("Segoe UI", 9, "bold"))

        accounts_panel = ctk.CTkFrame(self.canvas, fg_color="#0c0e0c", corner_radius=12,
                                      border_color="#30452f", border_width=1)
        self.accounts_panel_window = self.canvas.create_window(550, 205, window=accounts_panel,
                                                                anchor="n", width=690, height=365)
        section = ctk.CTkFrame(accounts_panel, fg_color="transparent", corner_radius=0)
        section.pack(fill="x", padx=22, pady=12)
        ctk.CTkLabel(section, text="MOJE ÚČTY", text_color="#74c97a",
                     font=("Segoe UI", 10, "bold")).pack(side="left")
        ctk.CTkLabel(section, text="Vyber účet a spusti hru", text_color="#6f6c64",
                     font=("Segoe UI", 9, "bold")).pack(side="right")
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
        self.status = ctk.CTkLabel(footer_meta, text="●  PRIPRAVENÉ", text_color="#c7c2b6", font=("Segoe UI", 10, "bold"))
        self.status.pack(anchor="e")
        ctk.CTkLabel(footer_meta, text=f"© {APP_AUTHOR}", text_color="#5b5a56",
                     font=("Segoe UI", 7)).pack(anchor="e")
        self.canvas.bind("<Configure>", self._resize_background)
        self.render_accounts()
        self.after(100, self.first_run)

    def _resize_background(self, event: tk.Event) -> None:
        required = ("topbar_window", "accounts_panel_window", "footer_window", "brand_id", "brand_subtitle_id")
        if not all(attribute in self.__dict__ for attribute in required):
            return
        if self.background_id:
            self.canvas.coords(self.background_id, event.width / 2, event.height / 2)
        self.canvas.itemconfigure(self.topbar_window, width=event.width)
        self.canvas.coords(self.accounts_panel_window, event.width / 2, 205)
        panel_height = max(270, min(365, event.height - 309))
        self.canvas.itemconfigure(self.accounts_panel_window, width=min(690, event.width - 80), height=panel_height)
        self.canvas.coords(self.footer_window, 0, event.height)
        self.canvas.itemconfigure(self.footer_window, width=event.width)
        self.canvas.coords(self.brand_id, event.width / 2, 150)
        self.canvas.coords(self.brand_subtitle_id, event.width / 2, 181)

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
                             BG, ("Segoe UI", 10, "bold"), radius=10)

    def _dark_button(self, parent: tk.Misc, text: str, command, width: int = 10, danger: bool = False) -> RoundedButton:
        color = DANGER if danger else PANEL_ALT
        hover = "#b94b42" if danger else "#263b25"
        return RoundedButton(parent, text, command, max(38, width * 9), 36, color, hover,
                             TEXT, ("Segoe UI", 8, "bold"), radius=8)

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
            launch = self._gold_button(row, f"▶   {account['name'].upper()}", lambda item=account: self.launch(item), width=28)
            launch.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=account.get("username", ""), text_color=MUTED,
                         font=("Segoe UI", 10, "bold"), width=135, anchor="w").pack(side="left", padx=12, fill="y")
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
        window.geometry("660x500")
        window.resizable(False, False)
        window.transient(self)
        window.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(window, text="NASTAVENIA LAUNCHERU", text_color=TEXT,
                     font=("Segoe UI", 19, "bold")).grid(row=0, column=0, columnspan=2, padx=24, pady=(22, 4), sticky="w")
        ctk.CTkLabel(window, text="Cesty k hre a správanie automatického prihlásenia",
                     text_color=MUTED, font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="w")

        ctk.CTkLabel(window, text="CESTA K WOW.EXE", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=2, column=0, padx=24, pady=(0, 6), sticky="w")
        path_text = tk.StringVar(value=self.config_data.get("wow_path", "Nenastavená"))
        ctk.CTkEntry(window, textvariable=path_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=3, column=0, padx=(24, 10), sticky="ew")
        ctk.CTkButton(window, text="VYBRAŤ", width=100, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_wow_path(), path_text.set(self.config_data.get("wow_path", "")))).grid(row=3, column=1, padx=(0, 24))

        ctk.CTkLabel(window, text="OFICIÁLNY GIGAFUN LAUNCHER", text_color="#75c77a",
                     font=("Segoe UI", 9, "bold")).grid(row=4, column=0, padx=24, pady=(18, 6), sticky="w")
        official_text = tk.StringVar(value=self.config_data.get("official_launcher_path", "Nenastavená"))
        ctk.CTkEntry(window, textvariable=official_text, height=38, corner_radius=8, state="readonly",
                     fg_color=PANEL_ALT, border_color="#355137").grid(row=5, column=0, padx=(24, 10), sticky="ew")
        ctk.CTkButton(window, text="VYBRAŤ", width=100, height=38, corner_radius=8,
                      fg_color="#315f36", hover_color="#477f4c",
                      command=lambda: (self.choose_official_launcher(), official_text.set(self.config_data.get("official_launcher_path", "")))).grid(row=5, column=1, padx=(0, 24))

        timing = ctk.CTkFrame(window, fg_color="#151816", corner_radius=10)
        timing.grid(row=6, column=0, columnspan=2, padx=24, pady=20, sticky="ew")
        timing.grid_columnconfigure((0, 1), weight=1)
        timeout = tk.StringVar(value=str(int(self.config_data.get("window_timeout", 30))))
        delay = tk.StringVar(value=str(float(self.config_data.get("ready_delay", 3))))
        ctk.CTkLabel(timing, text="TIMEOUT OKNA (s)", text_color=MUTED,
                     font=("Segoe UI", 8, "bold")).grid(row=0, column=0, padx=16, pady=(14, 5), sticky="w")
        ctk.CTkLabel(timing, text="ONESKORENIE LOGINU (s)", text_color=MUTED,
                     font=("Segoe UI", 8, "bold")).grid(row=0, column=1, padx=16, pady=(14, 5), sticky="w")
        ctk.CTkEntry(timing, textvariable=timeout, height=36, corner_radius=8,
                     fg_color="#0d0f0e", border_color="#354237").grid(row=1, column=0, padx=16, pady=(0, 14), sticky="ew")
        ctk.CTkEntry(timing, textvariable=delay, height=36, corner_radius=8,
                     fg_color="#0d0f0e", border_color="#354237").grid(row=1, column=1, padx=16, pady=(0, 14), sticky="ew")
        close_after = tk.BooleanVar(value=bool(self.config_data.get("close_after_login", True)))
        ctk.CTkSwitch(window, text="Po odoslaní prihlásenia zavrieť launcher", variable=close_after,
                      progress_color="#4b9a53", button_color="#e0b326").grid(row=7, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="w")

        def save() -> None:
            try:
                self.config_data["window_timeout"] = max(5, int(timeout.get()))
                self.config_data["ready_delay"] = max(0.5, float(delay.get()))
            except (ValueError, tk.TclError):
                messagebox.showwarning(APP_NAME, "Zadaj platné číselné hodnoty.", parent=window)
                return
            self.config_data["close_after_login"] = close_after.get()
            self.persist()
            window.destroy()

        ctk.CTkButton(window, text="ULOŽIŤ NASTAVENIA", command=save, width=190, height=42,
                      corner_radius=10, fg_color="#d6a91d", hover_color="#f0c532",
                      text_color="#090b09", font=("Segoe UI", 10, "bold")).grid(row=8, column=0, columnspan=2, padx=24, pady=(0, 22), sticky="e")

    def persist(self) -> None:
        try:
            save_config(self.config_data)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Konfiguráciu sa nepodarilo uložiť:\n{exc}", parent=self)

    def launch(self, account: dict) -> None:
        if self.busy:
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
        threading.Thread(target=self._login_worker, args=(account["username"], password), daemon=True).start()

    def _login_worker(self, username: str, password: str) -> None:
        try:
            import pyautogui

            wow_path = Path(self.config_data["wow_path"])
            process = subprocess.Popen([str(wow_path)], cwd=str(wow_path.parent))
            hwnd = find_window_for_pid(process.pid, float(self.config_data.get("window_timeout", 30)))
            if not hwnd:
                raise TimeoutError("Okno World of Warcraft sa v nastavenom čase nezobrazilo.")
            self.after(0, lambda: self.status.configure(text="●  ČAKÁM NA WOW…", text_color=GOLD))
            time.sleep(float(self.config_data.get("ready_delay", 3)))
            activate_window(hwnd)
            time.sleep(0.4)
            pyautogui.write(username, interval=0.03)
            pyautogui.press("tab")
            pyautogui.write(password, interval=0.03)
            pyautogui.press("enter")
            if self.config_data.get("close_after_login", True):
                self.after(0, self.destroy)
            else:
                self.after(0, lambda: self._finish_login("Prihlásenie odoslané"))
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
