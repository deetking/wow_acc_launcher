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
from tkinter import filedialog, messagebox, ttk
import uuid


APP_BASE_NAME = "WoW Nemesis Launcher"
APP_VERSION = "1.3.1"
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


class RoundedButton(tk.Canvas):
    """Small themed button with real rounded corners and hover feedback."""

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
        parent_bg = parent.cget("bg")
        super().__init__(parent, width=width, height=height, bg=parent_bg, bd=0,
                         highlightthickness=0, cursor="hand2", takefocus=1)
        self.command = command
        self.normal_color = background
        self.hover_color = hover
        self.radius = radius
        self.shape = self._rounded_rectangle(1, 1, width - 1, height - 1, radius, fill=background)
        self.caption = self.create_text(width / 2, height / 2, text=text, fill=foreground, font=font)
        for tag in (self.shape, self.caption):
            self.tag_bind(tag, "<Button-1>", lambda _event: self.command())
            self.tag_bind(tag, "<Enter>", self._enter)
            self.tag_bind(tag, "<Leave>", self._leave)
        self.bind("<Return>", lambda _event: self.command())
        self.bind("<space>", lambda _event: self.command())
        self.bind("<Configure>", self._resize_shape)

    @staticmethod
    def _shape_points(x1: int, y1: int, x2: int, y2: int, radius: int) -> tuple:
        return (
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        )

    def _rounded_rectangle(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs):
        return self.create_polygon(self._shape_points(x1, y1, x2, y2, radius),
                                   smooth=True, splinesteps=20, **kwargs)

    def _resize_shape(self, event: tk.Event) -> None:
        self.coords(self.shape, *self._shape_points(1, 1, event.width - 1, event.height - 1, self.radius))
        self.coords(self.caption, event.width / 2, event.height / 2)

    def _enter(self, _event=None) -> None:
        self.itemconfigure(self.shape, fill=self.hover_color)

    def _leave(self, _event=None) -> None:
        self.itemconfigure(self.shape, fill=self.normal_color)


class AccountDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, account: dict | None = None):
        super().__init__(parent)
        self.title("Účet")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.result: dict | None = None
        self.account = account or {}
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Názov:").grid(row=0, column=0, padx=12, pady=(12, 5), sticky="w")
        ttk.Label(self, text="Username:").grid(row=1, column=0, padx=12, pady=5, sticky="w")
        ttk.Label(self, text="Registrovaný e-mail:").grid(row=2, column=0, padx=12, pady=5, sticky="w")
        ttk.Label(self, text="Heslo:").grid(row=3, column=0, padx=12, pady=5, sticky="w")
        self.name = ttk.Entry(self, width=35)
        self.username = ttk.Entry(self, width=35)
        self.email = ttk.Entry(self, width=35)
        self.password = ttk.Entry(self, width=35, show="•")
        self.name.grid(row=0, column=1, padx=(0, 12), pady=(12, 5))
        self.username.grid(row=1, column=1, padx=(0, 12), pady=5)
        self.email.grid(row=2, column=1, padx=(0, 12), pady=5)
        self.password.grid(row=3, column=1, padx=(0, 12), pady=5)
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

        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(buttons, text="Zrušiť", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Uložiť", command=self.submit).pack(side="right", padx=(0, 8))
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


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x680")
        self.minsize(900, 600)
        self.configure(bg=BG)
        self.config_data = load_config()
        self.busy = False
        self._configure_styles()

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
        self.canvas.bind("<Configure>", self._resize_background)

        topbar = tk.Frame(self.canvas, bg="#0c0c0b", highlightbackground="#263b25", highlightthickness=1)
        self.topbar_window = self.canvas.create_window(0, 0, window=topbar, anchor="nw", width=1100, height=75)
        nav = tk.Frame(topbar, bg="#0c0c0b")
        nav.pack(side="left", padx=14, fill="y")
        for text, command in (
            ("ÚČTY", lambda: self.accounts_canvas.yview_moveto(0)),
            ("OFICIÁLNY UPDATER", self.launch_official_updater),
            ("NASTAVENIA", self.open_settings),
        ):
            tk.Button(nav, text=text, command=command, bg="#0c0c0b", fg="#9e998d",
                      activebackground="#151914", activeforeground="#6fd276", relief="flat",
                      bd=0, cursor="hand2", font=("Segoe UI", 8, "bold"), padx=12).pack(side="left", fill="y")
        tk.Label(topbar, text=APP_NAME, bg="#0c0c0b", fg="#aaa397",
                 font=("Segoe UI", 9, "bold")).place(relx=.5, rely=.3, anchor="center")
        tk.Label(topbar, text="GIGAFUN • ACCOUNT MANAGER", bg="#0c0c0b", fg="#4d8050",
                 font=("Segoe UI", 7)).place(relx=.5, rely=.67, anchor="center")

        self.notice_id = self.canvas.create_text(18, 98, text=f"Launcher • Version {APP_VERSION}",
                                                  fill="#d3cec2", anchor="w",
                                                  font=("Segoe UI", 9, "bold"))
        self.notice_line = self.canvas.create_line(14, 86, 14, 112, fill="#63c66b", width=2)
        self.brand_id = self.canvas.create_text(550, 150, text="GIGAFUN", fill="#d5a51d",
                                                 font=("Georgia", 30, "bold"))
        self.brand_subtitle_id = self.canvas.create_text(550, 181, text="NEMESIS ACCOUNT LAUNCHER",
                                                          fill="#71b975", font=("Segoe UI", 8, "bold"))

        accounts_panel = tk.Frame(self.canvas, bg="#0c0e0c", highlightbackground="#30452f", highlightthickness=1)
        self.accounts_panel_window = self.canvas.create_window(550, 205, window=accounts_panel,
                                                                anchor="n", width=690, height=365)
        section = tk.Frame(accounts_panel, bg="#0c0e0c", padx=22, pady=12)
        section.pack(fill="x")
        tk.Label(section, text="MOJE ÚČTY", bg="#0c0e0c", fg="#74c97a",
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(section, text="Vyber účet a spusti hru", bg="#0c0e0c", fg="#6f6c64",
                 font=("Segoe UI", 8)).pack(side="right")
        tk.Frame(accounts_panel, bg="#263b25", height=1).pack(fill="x")
        accounts_area = tk.Frame(accounts_panel, bg="#0c0e0c")
        accounts_area.pack(fill="both", expand=True)
        self.accounts_canvas = tk.Canvas(accounts_area, bg=PANEL, highlightthickness=0, bd=0)
        accounts_scrollbar = tk.Scrollbar(
            accounts_area, orient="vertical", command=self.accounts_canvas.yview,
            bg=PANEL_ALT, troughcolor=PANEL, activebackground=GOLD_DARK,
            highlightthickness=0, bd=0, width=10,
        )
        self.accounts_canvas.configure(yscrollcommand=accounts_scrollbar.set)
        accounts_scrollbar.pack(side="right", fill="y", padx=(0, 8))
        self.accounts_canvas.pack(side="left", fill="both", expand=True)
        self.accounts_frame = tk.Frame(self.accounts_canvas, bg=PANEL, padx=28)
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
        footer = tk.Frame(self.canvas, bg="#0a0b09", padx=24, pady=11,
                          highlightbackground="#394322", highlightthickness=1)
        self.footer_window = self.canvas.create_window(0, 680, window=footer, anchor="sw", width=1100, height=76)
        self._gold_button(footer, "+  PRIDAŤ ÚČET", self.add_account, width=18).pack(side="left")
        footer_meta = tk.Frame(footer, bg="#0a0b09")
        footer_meta.pack(side="right")
        self.status = tk.Label(footer_meta, text="●  PRIPRAVENÉ", bg="#0a0b09", fg=MUTED, font=("Segoe UI", 9, "bold"))
        self.status.pack(anchor="e")
        tk.Label(footer_meta, text=f"© {APP_AUTHOR}", bg="#0a0b09", fg="#5b5a56",
                 font=("Segoe UI", 7)).pack(anchor="e", pady=(3, 0))
        self.render_accounts()
        self.after(100, self.first_run)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TButton", background=GOLD, foreground=BG, padding=(12, 7), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("TButton", background=[("active", GOLD_HOVER)])
        style.configure("TEntry", fieldbackground=PANEL_ALT, foreground=TEXT, insertcolor=TEXT, bordercolor=GOLD_DARK)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.configure("TSpinbox", fieldbackground=PANEL_ALT, foreground=TEXT, arrowcolor=GOLD)

    def _resize_background(self, event: tk.Event) -> None:
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
                             BG, ("Segoe UI", 9, "bold"), radius=10)

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
                self.status.config(text="●  OFICIÁLNY UPDATER SPUSTENÝ", fg=GOLD)
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
            tk.Label(
                self.accounts_frame,
                text="Zatiaľ nemáš uložený žiadny účet.\nKlikni na „Pridať účet“.",
                justify="center",
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 11),
            ).pack(expand=True)
            return
        for account in accounts:
            row = tk.Frame(self.accounts_frame, bg=PANEL_ALT, highlightbackground="#292b30", highlightthickness=1)
            row.pack(fill="x", pady=5)
            launch = self._gold_button(row, f"▶   {account['name'].upper()}", lambda item=account: self.launch(item), width=28)
            launch.pack(side="left", fill="x", expand=True)
            tk.Label(row, text=account.get("username", ""), bg=PANEL_ALT, fg=MUTED,
                     font=("Segoe UI", 9), width=18, anchor="w", padx=12).pack(side="left", fill="y")
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
        window = tk.Toplevel(self)
        window.title("Nastavenia")
        window.configure(bg=PANEL)
        window.resizable(False, False)
        window.transient(self)
        ttk.Label(window, text="Cesta k WoW.exe:").grid(row=0, column=0, padx=12, pady=(12, 5), sticky="w")
        path_text = tk.StringVar(value=self.config_data.get("wow_path", "Nenastavená"))
        ttk.Entry(window, textvariable=path_text, width=52, state="readonly").grid(row=1, column=0, padx=12)
        ttk.Button(window, text="Vybrať…", command=lambda: (self.choose_wow_path(), path_text.set(self.config_data.get("wow_path", "")))).grid(row=1, column=1, padx=(0, 12))

        ttk.Label(window, text="Oficiálny GigaFun launcher:").grid(row=2, column=0, padx=12, pady=(12, 5), sticky="w")
        official_text = tk.StringVar(value=self.config_data.get("official_launcher_path", "Nenastavená"))
        ttk.Entry(window, textvariable=official_text, width=52, state="readonly").grid(row=3, column=0, padx=12)
        ttk.Button(window, text="Vybrať…", command=lambda: (self.choose_official_launcher(), official_text.set(self.config_data.get("official_launcher_path", "")))).grid(row=3, column=1, padx=(0, 12))

        ttk.Label(window, text="Timeout čakania na okno (sekundy):").grid(row=4, column=0, padx=12, pady=(12, 5), sticky="w")
        timeout = tk.IntVar(value=int(self.config_data.get("window_timeout", 30)))
        ttk.Spinbox(window, from_=5, to=120, textvariable=timeout, width=8).grid(row=5, column=0, padx=12, sticky="w")
        ttk.Label(window, text="Oneskorenie po zobrazení okna (sekundy):").grid(row=6, column=0, padx=12, pady=(12, 5), sticky="w")
        delay = tk.DoubleVar(value=float(self.config_data.get("ready_delay", 3)))
        ttk.Spinbox(window, from_=0.5, to=20, increment=0.5, textvariable=delay, width=8).grid(row=7, column=0, padx=12, sticky="w")
        close_after = tk.BooleanVar(value=bool(self.config_data.get("close_after_login", True)))
        ttk.Checkbutton(window, text="Po odoslaní prihlásenia zavrieť launcher", variable=close_after).grid(row=8, column=0, padx=12, pady=12, sticky="w")

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

        ttk.Button(window, text="Uložiť", command=save).grid(row=9, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="e")

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
        self.status.config(text=f"●  SPÚŠŤAM {account['name'].upper()}…", fg=GOLD)
        threading.Thread(target=self._login_worker, args=(account["username"], password), daemon=True).start()

    def _login_worker(self, username: str, password: str) -> None:
        try:
            import pyautogui

            wow_path = Path(self.config_data["wow_path"])
            process = subprocess.Popen([str(wow_path)], cwd=str(wow_path.parent))
            hwnd = find_window_for_pid(process.pid, float(self.config_data.get("window_timeout", 30)))
            if not hwnd:
                raise TimeoutError("Okno World of Warcraft sa v nastavenom čase nezobrazilo.")
            self.after(0, lambda: self.status.config(text="●  ČAKÁM NA WOW…", fg=GOLD))
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
        self.status.config(text=f"●  {text.upper()}", fg=MUTED)

    def _login_failed(self, error: Exception) -> None:
        self._finish_login("Prihlásenie zlyhalo")
        messagebox.showerror(APP_NAME, str(error), parent=self)


if __name__ == "__main__":
    Launcher().mainloop()
