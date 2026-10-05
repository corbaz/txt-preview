"""Static contract tests for the PowerShell settings implementation."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = (ROOT / "txt.ps1").read_text(encoding="utf-8")


class SettingsContractTests(unittest.TestCase):
    def test_source_contains_no_groq_secret(self) -> None:
        self.assertIsNone(re.search(r"gsk_[A-Za-z0-9]+", SCRIPT))

    def test_selected_model_drives_requests(self) -> None:
        self.assertIn("model    = $script:selectedGroqModel", SCRIPT)
        self.assertEqual(SCRIPT.count("New-GroqRequestJson $prompt"), 4)

    def test_settings_are_encrypted_for_windows_user(self) -> None:
        self.assertIn("ConvertFrom-SecureString $secureKey", SCRIPT)
        self.assertIn('"TXT Preview"', SCRIPT)

    def test_web_and_vision_payloads_are_supported(self) -> None:
        self.assertIn('type = "browser_search"', SCRIPT)
        self.assertIn('type      = "image_url"', SCRIPT)

    def test_model_selector_is_in_header_and_attachment_is_contextual(self) -> None:
        self.assertIn("$settingsNavHost.Controls.Add($modelCombo)", SCRIPT)
        self.assertIn("$panel.Controls.Add($btnAttachFiles)", SCRIPT)
        self.assertIn("$btnAttachFiles.Visible = $btnAttachFiles.Enabled", SCRIPT)

    def test_version_uses_requested_format(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^v:\d{2}\.\d{2}\.\d{2}-\d{2}\.\d{2}$")


if __name__ == "__main__":
    unittest.main()
