"""Build and validate a complete Windows release without local user data."""
from __future__ import annotations

import ast
import argparse
import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version() -> str:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
                return value
    raise ValueError("APP_VERSION must contain a numeric version")


def package(folder: Path, archive: Path) -> None:
    # Only distribution files may enter the ZIP, never the developer workspace.
    sources = [folder / f"{folder.name}.exe", folder / "README.txt", folder / "_internal"]
    if not all(path.exists() for path in sources):
        raise RuntimeError("Incomplete build: EXE, README.txt and _internal are required")
    sources += [path for path in (folder / "LICENSES", folder / "THIRD_PARTY_NOTICES.txt") if path.exists()]
    files = sorted(path for source in sources for path in
                   (source.rglob("*") if source.is_dir() else [source]) if path.is_file())
    if any(path.name.lower() in {"config.json", ".env"} or path.suffix.lower() in {".pfx", ".p12", ".pem", ".key"} for path in files):
        raise RuntimeError("Local configuration or private key found in release")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(folder.parent).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("ZIP integrity check failed")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")


def copy_licenses(folder: Path) -> None:
    distributions = {dist.metadata["Name"].lower(): dist
                     for dist in importlib.metadata.distributions(path=[str(ROOT / "vendor")])}
    for name in ("Pillow", "PyAutoGUI", "PyGetWindow", "PyRect", "PyScreeze", "PyTweening", "PyMsgBox", "Pyperclip", "MouseInfo", "PyInstaller"):
        try:
            distributions[name.lower()] = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    notices = ["Third-party components and build tooling; license texts are in LICENSES/."]
    for name, dist in sorted(distributions.items()):
        notices.append(f"{dist.metadata['Name']} {dist.version}")
        for file in dist.files or []:
            if file.name.lower().startswith(("license", "copying")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = folder / "LICENSES" / name / Path(*file.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (folder / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    options = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise SystemExit("Build on Windows with 64-bit Python.")
    release_version = version()
    name = f"WoW_Nemesis_Launcher_v{release_version}"
    numeric = tuple(map(int, release_version.split(".")))
    numeric += (0,) * (4 - len(numeric))
    metadata = (ROOT / "version_info.txt").read_text(encoding="utf-8")
    if f"filevers={numeric}" not in metadata or f"{name}.exe" not in metadata:
        raise SystemExit("Update version_info.txt to match APP_VERSION before building.")
    exclusions = ("mouseinfo", "pyscreeze", "pymsgbox", "pytweening", "numpy", "cv2",
                  "charset_normalizer", "requests", "urllib3", "httpx", "httpcore", "certifi",
                  "webbrowser", "urllib.request", "http.client", "http.server", "multiprocessing", "socket", "ssl")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--distpath", str(options.dist_dir.resolve()),
               "--noconsole", "--noupx", "--name", name, "--version-file", "version_info.txt",
               "--paths", "vendor", "--collect-data", "customtkinter", "--hidden-import", "pyautogui",
               "--hidden-import", "pyperclip", "--add-data", "assets/nemesis_background_v2.png;assets"]
    for module in exclusions:
        command.extend(["--exclude-module", module])
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "vendor") + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.run(command + ["main.py"], cwd=ROOT, env=environment, check=True)
    folder = options.dist_dir.resolve() / name
    readme = (ROOT / "release" / "README.txt").read_text(encoding="utf-8")
    readme = re.sub(r"v\d+\.\d+(?:\.\d+)?", f"v{release_version}", readme)
    (folder / "README.txt").write_text(readme, encoding="utf-8")
    copy_licenses(folder)
    archive = folder.parent / f"{name}_release.zip"
    package(folder, archive)
    print(f"Release: {archive}\nSHA-256: {archive.with_suffix('.zip.sha256')}")


if __name__ == "__main__":
    main()
