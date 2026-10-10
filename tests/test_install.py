"""Runs install.ps1 against a temporary folder and checks the shortcut it creates."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.ps1"


@unittest.skipUnless(os.name == "nt", "install.ps1 targets Windows")
@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is not installed on this machine")
class InstallScriptTests(unittest.TestCase):
    def test_creates_a_shortcut_that_launches_the_app(self) -> None:
        self.assertTrue(INSTALLER.exists(), "install.ps1 is missing")
        with tempfile.TemporaryDirectory() as shortcut_dir:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALLER),
                    "-ShortcutDirectory", shortcut_dir, "-NoLaunch", "-SkipPython", "-SkipFfmpeg",
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
            # The app targets PowerShell 7: Windows PowerShell 5.1 misreads its UTF-8 source.
            self.assertTrue(target.lower().endswith("pwsh.exe"), target)
            self.assertIn("-ExecutionPolicy Bypass", arguments)
            self.assertIn(str(ROOT / "txt.ps1"), arguments)
            self.assertEqual(Path(working_dir), ROOT)


def run_powershell(executable: str, command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-Command", command],
        capture_output=True, timeout=120, encoding="utf-8", errors="replace", env=env,
    )


def ps_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt", "install.ps1 targets Windows")
@unittest.skipUnless(shutil.which("pwsh") and shutil.which("python"), "needs PowerShell 7 and Python")
class PythonDetectionTests(unittest.TestCase):
    """install.ps1 and txt.ps1 must pick the same, working interpreter."""

    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.real_python = Path(shutil.which("python")).resolve()
        # A junction named WindowsApps holds a python.exe that works, so only the path rule can skip it.
        store = self.temp / "WindowsApps"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(store), str(self.real_python.parent)],
                       check=True, capture_output=True)
        self.addCleanup(lambda: os.rmdir(store))
        broken = self.temp / "broken"
        broken.mkdir()
        (broken / "python.exe").write_bytes(b"")
        self.path = ";".join([str(store), str(broken), str(self.real_python.parent), os.environ["SystemRoot"] + r"\System32"])
        self.local_app_data = self.temp / "local"
        self.local_app_data.mkdir()

    def detect(self, setup: str, call: str) -> str:
        command = (
            f"{setup}; "
            f"$env:Path = {ps_quote(Path(self.path))}; $env:LOCALAPPDATA = {ps_quote(self.local_app_data)}; "
            f"'RESULT=' + ({call})"
        )
        result = run_powershell("pwsh", command)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [line for line in result.stdout.splitlines() if line.startswith("RESULT=")][-1][len("RESULT="):]

    def test_installer_and_app_skip_store_stub_and_broken_python(self) -> None:
        from_installer = self.detect(
            f"$env:TXT_PREVIEW_INSTALL_TEST_MODE = '1'; . {ps_quote(ROOT / 'install.ps1')}", "Find-Python")
        from_app = self.detect(
            f"$env:TXT_PREVIEW_TEST_MODE = '1'; . {ps_quote(ROOT / 'txt.ps1')}", "Find-PythonCommand")
        self.assertEqual(Path(from_installer), self.real_python.parent / "python.exe")
        self.assertEqual(from_app, from_installer)


@unittest.skipUnless(os.name == "nt", "install.ps1 targets Windows")
class PortablePwshTests(unittest.TestCase):
    def test_broken_zip_keeps_the_existing_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            target = temp_path / "PowerShell" / "7"
            target.mkdir(parents=True)
            (target / "keep.txt").write_text("ok", encoding="utf-8")
            zip_path = temp_path / "broken.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("pwsh.exe", b"")
            command = (
                f"$env:TXT_PREVIEW_INSTALL_TEST_MODE = '1'; . {ps_quote(INSTALLER)}; "
                f"$portablePwshDirectory = {ps_quote(target)}; "
                f"try {{ Install-PwshFromZip {ps_quote(zip_path)}; 'RESULT=installed' }} catch {{ 'RESULT=refused' }}"
            )
            result = run_powershell("powershell", command)
            self.assertIn("RESULT=refused", result.stdout, result.stdout + result.stderr)
            self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "ok")
            self.assertFalse((target / "pwsh.exe").exists())
            self.assertFalse(Path(str(target) + ".staging").exists())


@unittest.skipUnless(os.name == "nt", "txt.ps1 targets Windows")
class WindowsPowerShellRelaunchTests(unittest.TestCase):
    def test_app_hands_off_to_pwsh_instead_of_running_in_5_1(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            # A stand-in pwsh.exe that exits at once: the app must start it and quit, not open its window.
            fake = temp_path / "local" / "Programs" / "PowerShell" / "7" / "pwsh.exe"
            fake.parent.mkdir(parents=True)
            shutil.copy(Path(os.environ["SystemRoot"]) / "System32" / "hostname.exe", fake)
            env = dict(os.environ)
            env["Path"] = os.environ["SystemRoot"] + r"\System32;" + os.environ["SystemRoot"] + r"\System32\WindowsPowerShell\v1.0"
            env.pop("PATH", None)
            env["LOCALAPPDATA"] = str(temp_path / "local")
            env["ProgramFiles"] = str(temp_path / "pf")
            env.pop("TXT_PREVIEW_TEST_MODE", None)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "txt.ps1")],
                capture_output=True, timeout=60, encoding="utf-8", errors="replace", env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
