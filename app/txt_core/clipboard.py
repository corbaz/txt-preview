"""Cross-platform clipboard helper (T25/S18): native OS commands instead of
navigator.clipboard, which macOS WKWebView does not expose to the page.

macOS uses pbpaste/pbcopy with the text on stdin. Windows drives PowerShell
with a FIXED command: the clipboard text never enters the command line nor a
shell — the write carries it in an environment variable (UTF-16 native) and
the read returns it base64-encoded on stdout (pure ASCII, so the console
host's codepage and its appended newline cannot corrupt the payload).
shell=True is never used, so no command injection is possible.

The runner and platform are injectable for tests; every failure raises a
controlled Spanish RuntimeError.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import time
from typing import Any, Callable

CLIPBOARD_TIMEOUT_SECONDS = 15
CLIPBOARD_ENV_VAR = "TXT_CLIPBOARD_TEXT"
# Windows opens the clipboard for every reader/writer; a process that is
# still exiting keeps it briefly locked and Set-/Get-Clipboard fails with
# "Error en la operación solicitada del Portapapeles". A short bounded retry
# absorbs the contention.
CLIPBOARD_RETRIES = 3
CLIPBOARD_RETRY_DELAY_SECONDS = 0.15

MSG_UNSUPPORTED = "El portapapeles no está disponible en esta plataforma."
MSG_TIMEOUT = f"la operación superó {CLIPBOARD_TIMEOUT_SECONDS} segundos."
MSG_READ_FAILED = "No se pudo leer el portapapeles ({detail})."
MSG_WRITE_FAILED = "No se pudo copiar al portapapeles ({detail})."
# Windows PowerShell refuses an empty Set-Clipboard -Value
# (ArgumentNullException); an empty copy is rejected uniformly instead.
MSG_WRITE_EMPTY = "No hay texto para copiar al portapapeles."

# Fixed PowerShell commands: no quoting of user text is ever needed.
POWERSHELL_READ_COMMAND = (
    "$texto=[string](Get-Clipboard -Raw); "
    "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($texto))"
)
POWERSHELL_WRITE_COMMAND = "Set-Clipboard -Value $env:TXT_CLIPBOARD_TEXT"


# Rich copy: the payloads travel in temp files (an environment variable is
# too small for embedded images) and the command itself stays fixed.
HTML_FILE_ENV_VAR = "TXT_CLIPBOARD_HTML_FILE"
TEXT_FILE_ENV_VAR = "TXT_CLIPBOARD_TEXT_FILE"
POWERSHELL_WRITE_HTML_COMMAND = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "$utf8=[Text.UTF8Encoding]::new($false); "
    # The HTML goes in as raw UTF-8 bytes: handed over as a string, Windows
    # PowerShell stores it in the ANSI code page and every accent, arrow or
    # emoji reaches Teams broken.
    "$html=New-Object IO.MemoryStream(,[IO.File]::ReadAllBytes($env:TXT_CLIPBOARD_HTML_FILE)); "
    "$text=[IO.File]::ReadAllText($env:TXT_CLIPBOARD_TEXT_FILE,$utf8); "
    "$data=New-Object Windows.Forms.DataObject; "
    "$data.SetData([Windows.Forms.DataFormats]::Html,$html); "
    "$data.SetData([Windows.Forms.DataFormats]::UnicodeText,$text); "
    "[Windows.Forms.Clipboard]::SetDataObject($data,$true)"
)


def _run(argv: list[str], runner: Callable[..., Any] | None,
         input_text: str | None = None,
         extra_env: dict[str, str] | None = None) -> Any:
    """Fixed argv + UTF-8 text pipes; shell is never used. stderr is decoded
    with errors='replace' so a localized console message can never crash the
    capture thread."""
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": CLIPBOARD_TIMEOUT_SECONDS,
    }
    if input_text is not None:
        kwargs["input"] = input_text
    if extra_env is not None:
        kwargs["env"] = {**os.environ, **extra_env}
    run = runner or subprocess.run
    return run(argv, **kwargs)


def _run_with_retries(argv: list[str], runner: Callable[..., Any] | None,
                      input_text: str | None = None,
                      extra_env: dict[str, str] | None = None) -> Any:
    """Run the fixed command, retrying transient clipboard-lock failures."""
    completed: Any = None
    for attempt in range(CLIPBOARD_RETRIES + 1):
        if attempt:
            time.sleep(CLIPBOARD_RETRY_DELAY_SECONDS)
        completed = _run(argv, runner, input_text=input_text,
                         extra_env=extra_env)
        if (getattr(completed, "returncode", 0) or 0) == 0:
            return completed
    return completed


def _detail(completed: Any) -> str:
    stderr = (getattr(completed, "stderr", None) or "").strip()
    last_line = stderr.splitlines()[-1] if stderr else ""
    return last_line or (f"el proceso terminó con código "
                         f"{getattr(completed, 'returncode', 0)}.")


def _completed_or_raise(completed: Any, message: str) -> None:
    if (getattr(completed, "returncode", 0) or 0) != 0:
        raise RuntimeError(message.format(detail=_detail(completed)))


def read_clipboard(platform: str | None = None,
                   runner: Callable[..., Any] | None = None) -> str:
    """Native clipboard text: '' when the clipboard holds no text."""
    platform = sys.platform if platform is None else platform
    try:
        if platform.startswith("win"):
            completed = _run_with_retries(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-Command", POWERSHELL_READ_COMMAND],
                runner)
            _completed_or_raise(completed, MSG_READ_FAILED)
            # The console host appends a newline to stdout: decode the base64
            # payload so the text is byte-exact (real trailing newlines
            # survive, because they are part of the encoded string).
            stdout = (completed.stdout or "").strip()
            return base64.b64decode(stdout.encode("ascii")).decode("utf-8")
        if platform == "darwin":
            completed = _run_with_retries(["pbpaste"], runner)
            _completed_or_raise(completed, MSG_READ_FAILED)
            return completed.stdout or ""
        raise RuntimeError(MSG_UNSUPPORTED)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(MSG_READ_FAILED.format(detail=MSG_TIMEOUT)) from error
    except OSError as error:
        raise RuntimeError(MSG_READ_FAILED.format(detail=str(error))) from error


def write_clipboard(text: str, platform: str | None = None,
                    runner: Callable[..., Any] | None = None) -> None:
    """Copy text to the native clipboard (Unicode and multiline safe)."""
    if not text:
        raise RuntimeError(MSG_WRITE_EMPTY)
    platform = sys.platform if platform is None else platform
    try:
        if platform.startswith("win"):
            completed = _run_with_retries(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-Command", POWERSHELL_WRITE_COMMAND],
                runner, extra_env={CLIPBOARD_ENV_VAR: text})
        elif platform == "darwin":
            completed = _run_with_retries(["pbcopy"], runner, input_text=text)
        else:
            raise RuntimeError(MSG_UNSUPPORTED)
        _completed_or_raise(completed, MSG_WRITE_FAILED)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(MSG_WRITE_FAILED.format(detail=MSG_TIMEOUT)) from error
    except OSError as error:
        raise RuntimeError(MSG_WRITE_FAILED.format(detail=str(error))) from error


def _write_mac_html(fragment: str, plain_text: str) -> None:
    import AppKit
    pasteboard = AppKit.NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    pasteboard.setString_forType_(fragment, AppKit.NSPasteboardTypeHTML)
    pasteboard.setString_forType_(plain_text, AppKit.NSPasteboardTypeString)


def write_clipboard_html(fragment: str, plain_text: str, platform: str | None = None,
                         runner: Callable[..., Any] | None = None,
                         mac_writer: Callable[[str, str], None] | None = None) -> None:
    """Copy rich text: the HTML fragment plus its plain-text alternative, so
    an app that understands formatting (Teams) pastes the formatted version."""
    if not fragment or not plain_text:
        raise RuntimeError(MSG_WRITE_EMPTY)
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        try:
            (mac_writer or _write_mac_html)(fragment, plain_text)
        except Exception as error:
            raise RuntimeError(MSG_WRITE_FAILED.format(detail=str(error))) from error
        return
    if not platform.startswith("win"):
        raise RuntimeError(MSG_UNSUPPORTED)
    import tempfile
    from .teams import cf_html
    paths = []
    try:
        for content in (cf_html(fragment), plain_text):
            descriptor, path = tempfile.mkstemp(prefix="txt-teams-", suffix=".txt")
            paths.append(path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        completed = _run_with_retries(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA",
             "-Command", POWERSHELL_WRITE_HTML_COMMAND],
            runner, extra_env={HTML_FILE_ENV_VAR: paths[0], TEXT_FILE_ENV_VAR: paths[1]})
        _completed_or_raise(completed, MSG_WRITE_FAILED)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(MSG_WRITE_FAILED.format(detail=MSG_TIMEOUT)) from error
    except OSError as error:
        raise RuntimeError(MSG_WRITE_FAILED.format(detail=str(error))) from error
    finally:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                pass
