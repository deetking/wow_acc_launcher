"""Distribution checks use dummy files, never personal account configuration."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.build_release import package


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "Launcher"
        (self.folder / "_internal").mkdir(parents=True)
        (self.folder / "Launcher.exe").write_bytes(b"dummy executable")
        (self.folder / "README.txt").write_text("Instructions")
        (self.folder / "_internal" / "runtime.dll").write_bytes(b"runtime")
        self.archive = self.folder.parent / "release.zip"

    def test_complete_archive_has_one_folder_and_valid_checksum(self):
        (self.folder / "config.json").write_text('{"accounts": []}')
        package(self.folder, self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), {"Launcher/Launcher.exe", "Launcher/README.txt", "Launcher/_internal/runtime.dll"})
        self.assertEqual(self.archive.with_suffix(".zip.sha256").read_text().split()[0],
                         hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_rejects_config_inside_runtime(self):
        (self.folder / "_internal" / "config.json").write_text("{}")
        with self.assertRaises(RuntimeError):
            package(self.folder, self.archive)

    def test_rejects_incomplete_release(self):
        (self.folder / "Launcher.exe").unlink()
        with self.assertRaises(RuntimeError):
            package(self.folder, self.archive)


if __name__ == "__main__":
    unittest.main()
