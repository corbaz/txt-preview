"""Runs install.ps1 against a temporary folder and checks the shortcut it creates."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.ps1"


@unittest.skipUnless(os.name == "nt", "install.ps1 targets Windows")
class InstallScriptTests(unittest.TestCase):
    def test_creates_a_shortcut_that_launches_the_app(self) -> None:
        self.assertTrue(INSTALLER.exists(), "install.ps1 is missing")
        with tempfile.TemporaryDirectory() as shortcut_dir:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALLER),
                    "-ShortcutDirectory", shortcut_dir, "-NoLaunch", "-SkipPython",
                ],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            shortcut = Path(shortcut_dir) / "TXT Preview.lnk"
            self.assertTrue(shortcut.exists())

            read = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}'); "
                    "$s.TargetPath; $s.Arguments; $s.WorkingDirectory",
                ],
                capture_output=True, text=True, timeout=60,
            )
            target, arguments, working_dir = read.stdout.strip().splitlines()
            self.assertTrue(target.lower().endswith("powershell.exe"))
            self.assertIn("-ExecutionPolicy Bypass", arguments)
            self.assertIn(str(ROOT / "txt.ps1"), arguments)
            self.assertEqual(Path(working_dir), ROOT)


if __name__ == "__main__":
    unittest.main()
