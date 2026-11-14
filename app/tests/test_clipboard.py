"""Cross-platform clipboard helper (T25/S18): Pegar/Copiar must work on macOS
WKWebView, which does not expose navigator.clipboard to the page.

The helper runs native OS commands with a test-injectable runner/platform:
macOS uses pbpaste/pbcopy; Windows drives PowerShell with a FIXED command and
passes the text through stdin (UTF-8), so arbitrary Unicode and multiline text
work without shell=True and without ever embedding the text in the command
line. Every failure raises/returns a controlled Spanish message; the Api
methods expose the {ok,...} bridge contract and never crash pywebview.
"""
import base64
import inspect
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import clipboard


class _Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def fake_runner(stdout="", stderr="", returncode=0, error=None):
    """A subprocess.run stand-in that records every call."""
    calls = []

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if error is not None:
            raise error
        return _Completed(stdout=stdout, stderr=stderr, returncode=returncode)

    return run, calls


def sequence_runner(*outcomes):
    """A subprocess.run stand-in with one _Completed per queued call."""
    calls = []
    queue = list(outcomes)

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if queue:
            return queue.pop(0)
        return _Completed()

    return run, calls


TEXT = "línea uno áéíóú 😃\nlínea «dos» — con $dollars `backticks` & \"quotes\""


class TestClipboardHelper(unittest.TestCase):
    def test_macos_read_uses_pbpaste(self):
        run, calls = fake_runner(stdout=TEXT)
        text = clipboard.read_clipboard(platform="darwin", runner=run)
        self.assertEqual(text, TEXT)
        self.assertEqual(calls[0][0], ["pbpaste"])
        self.assertNotIn("shell", calls[0][1])

    def test_macos_write_uses_pbcopy_with_stdin_text(self):
        run, calls = fake_runner()
        clipboard.write_clipboard(TEXT, platform="darwin", runner=run)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["pbcopy"])
        self.assertEqual(kwargs.get("input"), TEXT)
        self.assertNotIn("shell", kwargs)

    def test_windows_read_uses_powershell_get_clipboard_raw(self):
        # The console host appends a newline to stdout, so the read command
        # base64-encodes the UTF-8 payload; the helper decodes it byte-exact.
        run, calls = fake_runner(
            stdout=base64.b64encode(TEXT.encode("utf-8")).decode("ascii"))
        text = clipboard.read_clipboard(platform="win32", runner=run)
        self.assertEqual(text, TEXT)
        argv, kwargs = calls[0]
        self.assertEqual(argv[0], "powershell")
        self.assertIn("-NoProfile", argv)
        self.assertIn("-NonInteractive", argv)
        command = argv[-1]
        self.assertIn("Get-Clipboard -Raw", command)
        self.assertIn("ToBase64String", command)
        self.assertIn("UTF8", command)
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertNotIn("shell", kwargs)

    def test_windows_read_survives_a_real_trailing_newline(self):
        payload = TEXT + "\n"
        run, _ = fake_runner(
            stdout=base64.b64encode(payload.encode("utf-8")).decode("ascii"))
        self.assertEqual(clipboard.read_clipboard(platform="win32", runner=run),
                         payload)

    def test_windows_write_passes_text_via_env_never_in_the_command(self):
        run, calls = fake_runner()
        clipboard.write_clipboard(TEXT, platform="win32", runner=run)
        argv, kwargs = calls[0]
        command = argv[-1]
        self.assertIn("Set-Clipboard", command)
        # The text never enters the command line: it travels in an
        # environment variable (UTF-16 native, Unicode safe).
        self.assertNotIn("línea uno", command)
        self.assertNotIn("backticks", command)
        self.assertEqual(kwargs.get("env", {}).get("TXT_CLIPBOARD_TEXT"), TEXT)
        self.assertNotIn("input", kwargs)
        self.assertNotIn("shell", kwargs)

    def test_multiline_unicode_survives_the_helper(self):
        run, calls = fake_runner(
            stdout=base64.b64encode(TEXT.encode("utf-8")).decode("ascii"))
        self.assertEqual(clipboard.read_clipboard(platform="win32", runner=run),
                         TEXT)
        run, calls = fake_runner()
        clipboard.write_clipboard(TEXT, platform="win32", runner=run)
        self.assertEqual(calls[0][1]["env"]["TXT_CLIPBOARD_TEXT"], TEXT)

    def test_empty_read_returns_empty_string(self):
        run, calls = fake_runner(stdout="")
        self.assertEqual(clipboard.read_clipboard(platform="darwin", runner=run),
                         "")

    def test_windows_empty_read_returns_empty_string(self):
        run, calls = fake_runner(stdout=base64.b64encode(b"").decode("ascii"))
        self.assertEqual(clipboard.read_clipboard(platform="win32", runner=run),
                         "")

    def test_unsupported_platform_raises_controlled_spanish_message(self):
        run, _ = fake_runner()
        with self.assertRaises(RuntimeError) as ctx:
            clipboard.read_clipboard(platform="linux", runner=run)
        self.assertIn("portapapeles no está disponible", str(ctx.exception))

    def test_read_command_failure_raises_controlled_message(self):
        run, _ = fake_runner(returncode=1, stderr="boom")
        with self.assertRaises(RuntimeError) as ctx:
            clipboard.read_clipboard(platform="darwin", runner=run)
        self.assertIn("No se pudo leer el portapapeles", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_read_oserror_raises_controlled_message(self):
        run, _ = fake_runner(error=OSError("no pbpaste"))
        with self.assertRaises(RuntimeError) as ctx:
            clipboard.read_clipboard(platform="darwin", runner=run)
        self.assertIn("No se pudo leer el portapapeles", str(ctx.exception))

    def test_read_timeout_raises_controlled_message(self):
        run, _ = fake_runner(error=subprocess.TimeoutExpired(cmd="pbpaste",
                                                            timeout=10))
        with self.assertRaises(RuntimeError) as ctx:
            clipboard.read_clipboard(platform="darwin", runner=run)
        self.assertIn("No se pudo leer el portapapeles", str(ctx.exception))

    def test_write_failure_raises_controlled_message(self):
        run, _ = fake_runner(error=OSError("no pbcopy"))
        with self.assertRaises(RuntimeError) as ctx:
            clipboard.write_clipboard("texto", platform="darwin", runner=run)
        self.assertIn("No se pudo copiar al portapapeles", str(ctx.exception))

    def test_transient_clipboard_lock_failure_is_retried(self):
        run, calls = sequence_runner(
            _Completed(returncode=1, stderr="Error en la operación solicitada"),
            _Completed(),
        )
        with mock.patch.object(clipboard.time, "sleep"):
            clipboard.write_clipboard(TEXT, platform="win32", runner=run)
        self.assertEqual(len(calls), 2)

    def test_persistent_write_failure_raises_after_all_retries(self):
        run, calls = sequence_runner(*[_Completed(returncode=1)] * 9)
        with mock.patch.object(clipboard.time, "sleep"), \
                self.assertRaises(RuntimeError) as ctx:
            clipboard.write_clipboard(TEXT, platform="win32", runner=run)
        self.assertIn("No se pudo copiar al portapapeles", str(ctx.exception))
        self.assertEqual(len(calls), clipboard.CLIPBOARD_RETRIES + 1)

    def test_transient_read_lock_failure_is_retried(self):
        run, calls = sequence_runner(
            _Completed(returncode=1),
            _Completed(stdout=base64.b64encode(TEXT.encode("utf-8")).decode()),
        )
        with mock.patch.object(clipboard.time, "sleep"):
            self.assertEqual(
                clipboard.read_clipboard(platform="win32", runner=run), TEXT)
        self.assertEqual(len(calls), 2)

    def test_empty_write_is_rejected_before_any_process(self):
        run, calls = fake_runner()
        for empty in ("", None):
            with self.subTest(empty=empty):
                with self.assertRaises(RuntimeError) as ctx:
                    clipboard.write_clipboard(empty, platform="win32",
                                              runner=run)
                self.assertIn("No hay texto para copiar", str(ctx.exception))
        self.assertEqual(calls, [])


class TestApiClipboardContract(unittest.TestCase):
    """The bridge methods: {ok,...} contracts, injectable runner/platform,
    zero required arguments (pywebview calls them with none)."""

    def _api(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return main.Api(settings_dir=tmp.name, legacy_dir=tmp.name + "-legacy")

    def test_bridge_methods_take_no_required_arguments(self):
        # read_clipboard is called with no arguments from the page;
        # write_clipboard requires exactly the text to copy.
        def required_of(name):
            method = getattr(main.Api, name)
            return [
                p.name for p in inspect.signature(method).parameters.values()
                if p.default is inspect.Parameter.empty
                   and p.name != "self"
            ]
        self.assertEqual(required_of("read_clipboard"), [])
        self.assertEqual(required_of("write_clipboard"), ["text"])

    def test_read_clipboard_returns_ok_contract(self):
        run, calls = fake_runner(stdout=TEXT)
        result = self._api().read_clipboard(platform="darwin", runner=run)
        self.assertEqual(result, {"ok": True, "text": TEXT})
        self.assertEqual(calls[0][0], ["pbpaste"])

    def test_read_clipboard_error_is_controlled_not_a_crash(self):
        run, _ = fake_runner(error=OSError("no pbpaste"))
        result = self._api().read_clipboard(platform="darwin", runner=run)
        self.assertFalse(result["ok"])
        self.assertIn("No se pudo leer el portapapeles", result["error"])

    def test_write_clipboard_returns_ok_contract(self):
        run, calls = fake_runner()
        result = self._api().write_clipboard(TEXT, platform="win32", runner=run)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0][1]["env"]["TXT_CLIPBOARD_TEXT"], TEXT)
        self.assertNotIn("shell", calls[0][1])

    def test_write_clipboard_error_is_controlled_not_a_crash(self):
        run, _ = fake_runner(returncode=1, stderr="boom")
        result = self._api().write_clipboard("texto", platform="win32",
                                             runner=run)
        self.assertFalse(result["ok"])
        self.assertIn("No se pudo copiar al portapapeles", result["error"])


if __name__ == "__main__":
    unittest.main()
