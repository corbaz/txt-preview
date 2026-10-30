"""The Edge voice selector survives transient catalog failures."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "txt.ps1"
CATALOG = """Name                               Gender    ContentCategories      VoicePersonalities
---------------------------------  --------  ---------------------  ------------------
es-AR-ElenaNeural                  Female    General                Friendly
es-AR-TomasNeural                  Male      General                Friendly
"""


def ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_catalog_snippet(snippet: str, cache_path: Path) -> list[str]:
    command = (
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
        "$env:TXT_PREVIEW_TEST_MODE = '1'; "
        "$env:TXT_PREVIEW_EDGE_VOICE_CACHE = ''; "
        f". {ps_quote(APP)}; "
        f"$env:TXT_PREVIEW_EDGE_VOICE_CACHE = {ps_quote(cache_path)}; {snippet}"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-STA", "-Command", command],
        capture_output=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return [line.removeprefix("RESULT=") for line in result.stdout.splitlines() if line.startswith("RESULT=")]


def function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    next_function = source.find("\nfunction ", start + 1)
    return source[start:] if next_function < 0 else source[start:next_function]


class PythonDetectionContractTests(unittest.TestCase):
    def test_app_checks_the_process_exit_code_instead_of_shell_global_state(self) -> None:
        body = function_body(APP.read_text(encoding="utf-8-sig"), "Test-PythonCandidate")
        self.assertIn("[Diagnostics.Process]::Start", body)
        self.assertIn(".ExitCode", body)
        self.assertNotIn("$LASTEXITCODE", function_body(APP.read_text(encoding="utf-8-sig"), "Find-PythonCommand"))

    def test_startup_surfaces_catalog_degradation_in_the_status_bar(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        self.assertIn("$script:edgeVoiceCatalogMessage = $edgeVoiceCatalog.Message", source)
        self.assertIn(
            "Show-Message $script:edgeVoiceCatalogMessage -Level $script:edgeVoiceCatalogMessageLevel",
            source,
        )


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class EdgeVoiceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "edge-voices.json"

    def test_online_catalog_is_parsed_and_cached(self) -> None:
        output = CATALOG.replace("'", "''")
        results = run_catalog_snippet(
            "$fake = { param($python) [pscustomobject]@{ ExitCode = 0; Output = '" + output + "'; Error = '' } }; "
            "$r = Get-EdgeVoiceCatalog -PythonCommand 'python.exe' -CachePath $env:TXT_PREVIEW_EDGE_VOICE_CACHE "
            "-CatalogInvoker $fake -RetryDelayMilliseconds 0; "
            "'RESULT=' + $r.Source + '|' + $r.Voices.Count + '|' + (Test-Path $env:TXT_PREVIEW_EDGE_VOICE_CACHE)",
            self.cache,
        )
        self.assertEqual(results[-1], "Online|2|True")

    def test_failed_first_attempt_retries_and_refreshes_cache(self) -> None:
        output = CATALOG.replace("'", "''")
        results = run_catalog_snippet(
            "$script:calls = 0; $fake = { param($python) $script:calls++; if ($script:calls -eq 1) { "
            "[pscustomobject]@{ ExitCode = 1; Output = ''; Error = 'red temporal' } } else { "
            "[pscustomobject]@{ ExitCode = 0; Output = '" + output + "'; Error = '' } } }; "
            "$r = Get-EdgeVoiceCatalog -PythonCommand 'python.exe' -CachePath $env:TXT_PREVIEW_EDGE_VOICE_CACHE "
            "-CatalogInvoker $fake -RetryDelayMilliseconds 0; "
            "'RESULT=' + $r.Source + '|' + $r.Voices.Count + '|' + $script:calls + '|' + $r.Message",
            self.cache,
        )
        self.assertEqual(results[-1], "Online|2|2|")

    def test_transient_failure_uses_last_valid_catalog(self) -> None:
        output = CATALOG.replace("'", "''")
        results = run_catalog_snippet(
            "$online = { param($python) [pscustomobject]@{ ExitCode = 0; Output = '" + output + "'; Error = '' } }; "
            "$null = Get-EdgeVoiceCatalog -PythonCommand 'python.exe' -CachePath $env:TXT_PREVIEW_EDGE_VOICE_CACHE "
            "-CatalogInvoker $online -RetryDelayMilliseconds 0; "
            "$script:calls = 0; $offline = { param($python) $script:calls++; "
            "[pscustomobject]@{ ExitCode = 1; Output = ''; Error = 'sin red' } }; "
            "$r = Get-EdgeVoiceCatalog -PythonCommand 'python.exe' -CachePath $env:TXT_PREVIEW_EDGE_VOICE_CACHE "
            "-CatalogInvoker $offline -RetryDelayMilliseconds 0; "
            "'RESULT=' + $r.Source + '|' + $r.Voices.Count + '|' + $script:calls + '|' + ($r.Message -like '*último catálogo*')",
            self.cache,
        )
        self.assertEqual(results[-1], "Cache|2|2|True")

    def test_missing_module_never_uses_cached_voices(self) -> None:
        output = CATALOG.replace("'", "''")
        results = run_catalog_snippet(
            "$online = { param($python) [pscustomobject]@{ ExitCode = 0; Output = '" + output + "'; Error = '' } }; "
            "$null = Get-EdgeVoiceCatalog -PythonCommand 'python.exe' -CachePath $env:TXT_PREVIEW_EDGE_VOICE_CACHE "
            "-CatalogInvoker $online -RetryDelayMilliseconds 0; "
            "$missing = { param($python) [pscustomobject]@{ ExitCode = 1; Output = ''; Error = 'No module named edge_tts' } }; "
            "$r = Get-EdgeVoiceCatalog -PythonCommand 'python.exe' -CachePath $env:TXT_PREVIEW_EDGE_VOICE_CACHE "
            "-CatalogInvoker $missing -RetryDelayMilliseconds 0; "
            "'RESULT=' + $r.Source + '|' + $r.Voices.Count + '|' + ($r.Message -like '*edge-tts*')",
            self.cache,
        )
        self.assertEqual(results[-1], "None|0|True")

    def test_corrupt_cache_is_ignored(self) -> None:
        self.cache.write_text("{", encoding="utf-8")
        results = run_catalog_snippet(
            "$offline = { param($python) [pscustomobject]@{ ExitCode = 1; Output = ''; Error = 'sin red' } }; "
            "$r = Get-EdgeVoiceCatalog -PythonCommand 'python.exe' -CachePath $env:TXT_PREVIEW_EDGE_VOICE_CACHE "
            "-CatalogInvoker $offline -RetryDelayMilliseconds 0; "
            "'RESULT=' + $r.Source + '|' + $r.Voices.Count + '|' + $r.Level",
            self.cache,
        )
        self.assertEqual(results[-1], "None|0|Error")


if __name__ == "__main__":
    unittest.main()
