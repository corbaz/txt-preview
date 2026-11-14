"""Cross-platform safety net (S4): Windows-only calls must be platform-guarded
and app sources must never hardcode drive-letter paths.

Runs identically on Windows and macOS; it is the CI tripwire that keeps
Windows-pushed changes from silently breaking the Mac build.
"""
import ast
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

APP = Path(__file__).resolve().parents[1]

WINDOWS_ONLY_CALLS = {
    "winreg",          # module-level import usage
    "WinDLL",          # ctypes.WinDLL
    "OpenProcess",
    "NtSuspendProcess",
    "NtResumeProcess",
    "CryptProtectData",
    "CryptUnprotectData",
}


def _iter_app_sources():
    for path in sorted(APP.rglob("*.py")):
        if "tests" in path.parts:
            continue
        yield path


def _guarded_functions(tree, lines):
    """Line ranges of functions whose body contains a platform check."""
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = "\n".join(lines[(node.lineno - 1):(node.end_lineno or node.lineno)])
            if ('sys.platform == "win32"' in body or 'sys.platform != "win32"' in body
                    or 'os.name == "nt"' in body or 'os.name != "nt"' in body
                    or 'detect_platform()' in body or '_require_windows()' in body):
                ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def _platform_guarded(node, tree_source_lines, guarded_ranges=()):
    """True when a Windows-only call sits inside a platform-guarded function
    or near a direct platform check."""
    lines = tree_source_lines
    start = getattr(node, "lineno", 0) or 0
    for lo, hi in guarded_ranges:
        if lo <= start <= hi:
            return True
    window = "\n".join(lines[max(0, start - 12):start + 4])
    if 'sys.platform == "win32"' in window or 'sys.platform != "win32"' in window:
        return True
    if "os.name == \"nt\"" in window or "os.name != \"nt\"" in window:
        return True
    return False


class TestWindowsOnlyCallsAreGuarded(unittest.TestCase):
    def test_every_windows_only_call_has_a_platform_guard(self):
        offenders = []
        for path in _iter_app_sources():
            source = path.read_text(encoding="utf-8")
            if "win32" not in source and "nt\"" not in source:
                # No platform awareness at all: Windows-only names must not appear.
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    name = getattr(node, "attr", None) or getattr(node, "id", None)
                    if name in WINDOWS_ONLY_CALLS:
                        offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')} unguarded {name}")
                continue
            lines = source.splitlines()
            tree = ast.parse(source)
            guarded = _guarded_functions(tree, lines)
            for node in ast.walk(tree):
                name = getattr(node, "attr", None) or getattr(node, "id", None)
                if name in WINDOWS_ONLY_CALLS and not _platform_guarded(node, lines, guarded):
                    offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')} unguarded {name}")
        self.assertEqual(offenders, [])


class TestNoDriveLetterPaths(unittest.TestCase):
    def test_app_sources_have_no_drive_letter_path_literals(self):
        import re
        pattern = re.compile(r"[A-Za-z]:\\\\|r\"[A-Za-z]:\\|r'[A-Za-z]:\\")
        offenders = []
        for path in _iter_app_sources():
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and "ProgramFiles(x86)" not in line:
                    offenders.append(f"{path.name}:{i}: {line.strip()[:80]}")
        self.assertEqual(offenders, [])


class TestS17NativeTrustStore(unittest.TestCase):
    """S17/T24: the entrypoint trusts the native system store (macOS Keychain /
    Windows store) before any network or TLS use, and TLS verification is never
    weakened (no verify=False, no VERIFY_X509_STRICT/verify_flags changes)."""

    def test_requirements_pin_truststore(self):
        # truststore>=0.10.5 supports Python 3.14 + the macOS Security framework.
        text = (APP / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("truststore>=0.10.5", text)

    def test_main_imports_and_injects_truststore_before_other_imports(self):
        source = (APP / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        statements = list(tree.body)
        non_future = [(i, n) for i, n in enumerate(statements)
                      if isinstance(n, (ast.Import, ast.ImportFrom))
                      and not (isinstance(n, ast.ImportFrom) and n.module == "__future__")]
        self.assertGreaterEqual(len(non_future), 2)
        first_index, first_import = non_future[0]
        self.assertEqual(
            getattr(first_import, "module", None) or first_import.names[0].name,
            "truststore",
            "the entrypoint must import truststore first (before urllib/network "
            "modules and before txt_core Groq/models imports)")
        inject_index = next(
            (i for i, n in enumerate(statements)
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Attribute)
             and n.value.func.attr == "inject_into_ssl"
             and isinstance(n.value.func.value, ast.Name)
             and n.value.func.value.id == "truststore"),
            None)
        self.assertIsNotNone(
            inject_index,
            "main.py must call truststore.inject_into_ssl() at module level")
        for later_index, _node in non_future[1:]:
            self.assertLess(
                inject_index, later_index,
                "truststore.inject_into_ssl() must run before every other import")

    def test_main_actually_calls_inject_into_ssl_on_import(self):
        stub = types.ModuleType("truststore")
        calls = []
        stub.inject_into_ssl = lambda: calls.append(True)
        real = sys.modules.get("truststore")
        real_main = sys.modules.get("main")
        sys.modules.pop("main", None)
        sys.modules["truststore"] = stub
        try:
            import main  # noqa: F401 — fresh import with the recording stub
        finally:
            if real is not None:
                sys.modules["truststore"] = real
            else:
                sys.modules.pop("truststore", None)
            if real_main is not None:
                sys.modules["main"] = real_main
            else:
                sys.modules.pop("main", None)
        self.assertEqual(calls, [True])

    def test_sources_never_weaken_tls_verification(self):
        offenders = []
        for path in _iter_app_sources():
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if ("verify=False" in code or "verify = False" in code
                        or "verify_flags" in code or "VERIFY_X509_STRICT" in code):
                    offenders.append(f"{path.name}:{i}: {line.strip()[:60]}")
        self.assertEqual(offenders, [])


class TestSuiteImportsEverywhere(unittest.TestCase):
    def test_core_modules_import(self):
        # Imports happen for the whole package via the other tests; this pins it.
        import importlib
        for module in ("txt_core", "txt_core.citations", "txt_core.prompts",
                       "txt_core.groq", "txt_core.bridges", "txt_core.models",
                       "txt_core.markdown", "txt_core.attachments", "txt_core.exports",
                       "txt_core.settings", "txt_core.updater",
                       "txt_core.speech", "txt_core.speech.chunker", "txt_core.speech.marks",
                       "txt_core.speech.alignment", "txt_core.speech.replay",
                       "txt_core.speech.voices", "txt_core.speech.engine"):
            importlib.import_module(module)


if __name__ == "__main__":
    unittest.main()
