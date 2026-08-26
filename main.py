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
APP_VERSION = "1.1.0"
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
        ttk.Label(self, text="Heslo:").grid(row=2, column=0, padx=12, pady=5, sticky="w")
        self.name = ttk.Entry(self, width=35)
        self.username = ttk.Entry(self, width=35)
        self.password = ttk.Entry(self, width=35, show="•")
        self.name.grid(row=0, column=1, padx=(0, 12), pady=(12, 5))
        self.username.grid(row=1, column=1, padx=(0, 12), pady=5)
        self.password.grid(row=2, column=1, padx=(0, 12), pady=5)
        self.name.insert(0, self.account.get("name", ""))
        self.username.insert(0, self.account.get("username", ""))
        if self.account.get("password"):
            try:
                self.password.insert(0, unprotect_secret(self.account["password"]))
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Heslo sa nepodarilo odomknúť:\n{exc}", parent=self)

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(buttons, text="Zrušiť", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Uložiť", command=self.submit).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _event: self.submit())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.transient(parent)
        self.grab_set()
        self.name.focus_set()

    def submit(self) -> None:
        name, username, password = self.name.get().strip(), self.username.get().strip(), self.password.get()
        if not name or not username or not password:
            messagebox.showwarning(APP_NAME, "Vyplň názov, username aj heslo.", parent=self)
            return
        try:
            encrypted = protect_secret(password)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Heslo sa nepodarilo bezpečne uložiť:\n{exc}", parent=self)
            return
        self.result = {
            "id": self.account.get("id", uuid.uuid4().hex),
            "name": name,
            "username": username,
            "password": encrypted,
        }
        self.destroy()


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("900x650")
        self.minsize(720, 520)
        self.configure(bg=BG)
        self.config_data = load_config()
        self.busy = False
        self._configure_styles()

        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        try:
            self.background_image = tk.PhotoImage(file=str(resource_path("assets/nemesis_background.png")))
            self.background_id = self.canvas.create_image(0, 0, image=self.background_image, anchor="center")
        except tk.TclError:
            self.background_image = None
            self.background_id = None
        self.canvas.bind("<Configure>", self._resize_background)

        shell = tk.Frame(self.canvas, bg=PANEL, highlightbackground=GOLD_DARK, highlightthickness=1)
        self.shell_window = self.canvas.create_window(450, 330, window=shell, width=680, height=540)

        header = tk.Frame(shell, bg=PANEL, padx=28, pady=20)
        header.pack(fill="x")
        brand = tk.Frame(header, bg=PANEL)
        brand.pack(side="left")
        tk.Label(brand, text=f"PROJECT  •  NEMESIS    v{APP_VERSION}", bg=PANEL, fg=GOLD, font=("Georgia", 10, "bold")).pack(anchor="w")
        tk.Label(brand, text="GIGAFUN", bg=PANEL, fg=TEXT, font=("Georgia", 29, "bold")).pack(anchor="w", pady=(2, 0))
        tk.Label(brand, text="WoW TBC 2.4.3  ·  ACCOUNT LAUNCHER", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        self._dark_button(header, "⚙  NASTAVENIA", self.open_settings, width=16).pack(side="right", pady=12)

        tk.Frame(shell, bg=GOLD_DARK, height=1).pack(fill="x")
        section = tk.Frame(shell, bg=PANEL, padx=28, pady=16)
        section.pack(fill="x")
        tk.Label(section, text="VYBER ÚČET", bg=PANEL, fg=GOLD, font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(section, text="Kliknutím spustíš hru a prihlásenie", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="right")

        self.accounts_frame = tk.Frame(shell, bg=PANEL, padx=28)
        self.accounts_frame.pack(fill="both", expand=True)
        footer = tk.Frame(shell, bg=PANEL_ALT, padx=28, pady=14)
        footer.pack(fill="x", side="bottom")
        self._gold_button(footer, "+  PRIDAŤ ÚČET", self.add_account, width=18).pack(side="left")
        self._dark_button(footer, "OFICIÁLNY UPDATER", self.launch_official_updater, width=19).pack(side="left", padx=8)
        footer_meta = tk.Frame(footer, bg=PANEL_ALT)
        footer_meta.pack(side="right")
        self.status = tk.Label(footer_meta, text="●  PRIPRAVENÉ", bg=PANEL_ALT, fg=MUTED, font=("Segoe UI", 9, "bold"))
        self.status.pack(anchor="e")
        tk.Label(footer_meta, text=f"© {APP_AUTHOR}", bg=PANEL_ALT, fg="#5b5a56",
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
        self.canvas.coords(self.shell_window, event.width / 2, event.height / 2)

    def _gold_button(self, parent: tk.Misc, text: str, command, width: int = 22) -> tk.Button:
        return tk.Button(parent, text=text, command=command, width=width, bg=GOLD, fg=BG,
                         activebackground=GOLD_HOVER, activeforeground=BG, relief="flat",
                         bd=0, cursor="hand2", font=("Segoe UI", 10, "bold"), padx=12, pady=10)

    def _dark_button(self, parent: tk.Misc, text: str, command, width: int = 10, danger: bool = False) -> tk.Button:
        color = DANGER if danger else PANEL_ALT
        return tk.Button(parent, text=text, command=command, width=width, bg=color, fg=TEXT,
                         activebackground=GOLD_DARK if not danger else "#b94b42", activeforeground=TEXT,
                         highlightbackground=GOLD_DARK, highlightthickness=1, relief="flat",
                         bd=0, cursor="hand2", font=("Segoe UI", 8, "bold"), padx=8, pady=8)

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
