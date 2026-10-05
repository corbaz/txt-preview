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

    def test_editor_shows_the_context_sent_to_groq(self) -> None:
        self.assertIn("$contextPanel.Controls.Add($checkWebSearch)", SCRIPT)
        self.assertIn("$contextPanel.Controls.Add($lblAttachments)", SCRIPT)
        self.assertIn("$contextPanel.Controls.Add($btnClearAttachments)", SCRIPT)
        self.assertIn('"Se enviarán a Groq ($($names.Count)): "', SCRIPT)

    def test_attachment_can_be_the_only_input(self) -> None:
        self.assertIn("$script:attachedFiles.Count -gt 0", SCRIPT)
        self.assertEqual(SCRIPT.count("if (-not (Test-GroqInputAvailable))"), 4)

    def test_toolbar_is_recentered_when_the_form_is_shown(self) -> None:
        shown_handler = re.search(r"\$form\.Add_Shown\(\{(?P<body>.*?)\n\}\)", SCRIPT, re.DOTALL)
        self.assertIsNotNone(shown_handler)
        self.assertIn("Update-ToolbarLayout", shown_handler.group("body"))

    def test_clear_chat_also_removes_attachments(self) -> None:
        clear_handler = re.search(r"\$btnLimpiar\.Add_Click\(\{(?P<body>.*?)\n\}\)", SCRIPT, re.DOTALL)
        self.assertIsNotNone(clear_handler)
        self.assertIn("$script:attachedFiles.Clear()", clear_handler.group("body"))
        self.assertIn("Update-AttachmentSummary", clear_handler.group("body"))

    def test_notices_use_a_theme_aware_color(self) -> None:
        self.assertEqual(SCRIPT.count('Notice = "#'), 2)
        style_helper = re.search(r"function Set-InfoStyle \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL)
        self.assertIsNotNone(style_helper)
        self.assertIn('default { "Notice" }', style_helper.group("body"))
        self.assertIn("$infoFontSize", style_helper.group("body"))

    def test_every_informational_message_shares_the_info_style(self) -> None:
        info_controls = re.search(r"\$infoControls = @\((?P<body>[^)]*)\)", SCRIPT)
        self.assertIsNotNone(info_controls)
        for control in (
            "$msgBox", "$settingsHint", "$settingsStatus", "$lblAppVersion",
            "$lblUpdateStatus", "$lblAttachments", "$versionLabel",
        ):
            self.assertIn(control, info_controls.group("body"))
        self.assertIn("Set-InfoStyle $control", SCRIPT)
        self.assertNotIn('$lblUpdateStatus.ForeColor = Get-ThemeColor "Muted"', SCRIPT)
        self.assertNotIn('$lblAttachments.ForeColor = Get-ThemeColor "Muted"', SCRIPT)

    def test_errors_are_red_and_warnings_are_yellow_in_both_themes(self) -> None:
        self.assertEqual(SCRIPT.count('Danger = "#'), 2)
        self.assertEqual(SCRIPT.count('Warning = "#'), 2)
        style_helper = re.search(r"function Set-InfoStyle \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL)
        self.assertIn('"Error" { "Danger" }', style_helper.group("body"))
        self.assertIn('"Warning" { "Warning" }', style_helper.group("body"))
        self.assertIn("function Set-StatusText", SCRIPT)

    def test_every_failure_message_is_flagged_as_error(self) -> None:
        failures = re.findall(r'^\s*(?:Show-Message|Set-StatusText \$\w+) "(?:No se pudo|Error al|No se encontró).*$', SCRIPT, re.MULTILINE)
        self.assertGreater(len(failures), 20)
        for line in failures:
            self.assertTrue(line.rstrip().endswith("-Level Error"), line)
        self.assertNotRegex(SCRIPT, r'\$(settingsStatus|lblUpdateStatus)\.Text = "No se pudo')

    def test_missing_input_messages_are_flagged_as_warning(self) -> None:
        warnings = re.findall(r'^\s*Show-Message "(?:No hay |Ingresá ).*$', SCRIPT, re.MULTILINE)
        self.assertGreater(len(warnings), 8)
        for line in warnings:
            self.assertTrue(line.rstrip().endswith("-Level Warning"), line)

    def test_context_panel_does_not_cover_the_editor(self) -> None:
        # A Top panel brought to front docks after the Fill editor and hides its first lines.
        self.assertNotIn("$contextPanel.BringToFront()", SCRIPT)

    def test_context_shows_selected_model_capability_badges(self) -> None:
        badges = re.search(r"function Update-CapabilityBadges \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL)
        self.assertIsNotNone(badges)
        body = badges.group("body")
        for glyph in ("0xE774", "0xE890", "0xE723", "0xE8BD", "0xE82F"):
            self.assertIn(glyph, body)
        self.assertIn('Get-ThemeColor "Notice"', body)
        self.assertIn("$contextToolTip.SetToolTip", body)
        self.assertIn("$contextPanel.Controls.Add($capabilityBadgeHost)", SCRIPT)
        self.assertIn("Update-CapabilityBadges", SCRIPT.split("function Update-ModelCapabilityControls", 1)[1])

    def test_settings_can_check_for_repository_updates(self) -> None:
        self.assertIn("$tabSettings.Controls.Add($btnCheckUpdate)", SCRIPT)
        self.assertIn("$tabSettings.Controls.Add($btnInstallUpdate)", SCRIPT)
        self.assertIn('Invoke-GitCommand @("fetch", "--quiet", "origin", "main")', SCRIPT)
        self.assertIn('Invoke-GitCommand @("show", "FETCH_HEAD:VERSION")', SCRIPT)
        self.assertIn("Compare-AppVersions", SCRIPT)

    def test_update_is_fast_forward_only_and_preserves_local_changes(self) -> None:
        self.assertEqual(SCRIPT.count('Invoke-GitCommand @("branch", "--show-current")'), 2)
        self.assertIn('Invoke-GitCommand @("status", "--porcelain")', SCRIPT)
        self.assertIn('Invoke-GitCommand @("pull", "--ff-only", "origin", "main")', SCRIPT)
        self.assertIn("Hay cambios locales", SCRIPT)
        git_helper = re.search(r"function Invoke-GitCommand \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL)
        self.assertIsNotNone(git_helper)
        self.assertIn("$startInfo.Arguments", git_helper.group("body"))
        self.assertNotIn("$startInfo.ArgumentList", git_helper.group("body"))

    def test_startup_offers_available_update_in_a_modal(self) -> None:
        shown_handler = re.search(r"\$form\.Add_Shown\(\{(?P<body>.*?)\n\}\)", SCRIPT, re.DOTALL)
        self.assertIn("$startupUpdateTimer.Start()", shown_handler.group("body"))
        check = re.search(r"function Invoke-StartupUpdateCheck \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL)
        self.assertIsNotNone(check)
        body = check.group("body")
        self.assertIn("Update-AppUpdateControls", body)
        self.assertIn("$script:availableUpdateVersion", body)
        self.assertIn("[Windows.Forms.MessageBoxButtons]::YesNo", body)
        self.assertIn("Invoke-AppUpdateInstall", body)
        self.assertIn("Restart-App", body)

    def test_manual_and_startup_updates_share_one_install_path(self) -> None:
        self.assertEqual(SCRIPT.count("Install-AppUpdate\n"), 1)
        install_click = re.search(r"\$btnInstallUpdate\.Add_Click\(\{(?P<body>.*?)\n\}\)", SCRIPT, re.DOTALL)
        self.assertIn("Invoke-AppUpdateInstall", install_click.group("body"))

    def test_git_commands_keep_the_window_responsive(self) -> None:
        git_helper = re.search(r"function Invoke-GitCommand \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL)
        self.assertIn("ReadToEndAsync()", git_helper.group("body"))
        self.assertIn("Wait-TaskWithEvents", git_helper.group("body"))

    def _click_handler(self, button: str) -> str:
        handler = re.search(r"\$" + button + r"\.Add_Click\(\{(?P<body>.*?)\n\}\)", SCRIPT, re.DOTALL)
        self.assertIsNotNone(handler, button)
        return handler.group("body")

    def test_ask_keeps_the_prompt_in_the_editor(self) -> None:
        body = self._click_handler("btnPreguntar")
        self.assertNotIn("$textBox.Text = ", body)
        self.assertNotIn("Set-EditorText", body)
        self.assertIn("Show-AiResult $respuesta", body)

    def test_transforms_replace_the_editor_with_undo(self) -> None:
        helper = re.search(r"function Set-EditorText \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL)
        self.assertIsNotNone(helper)
        # .Text and .SelectedText clear the undo buffer; Paste(text) keeps Ctrl+Z.
        self.assertIn("$textBox.Paste(", helper.group("body"))
        self.assertNotRegex(SCRIPT, r"\$textBox\.Text = \$")
        for variable in ("$traducido", "$corregido", "$resumen", "$contenido"):
            self.assertIn(f"Set-EditorText {variable}", SCRIPT)

    def test_output_actions_use_the_preview_content(self) -> None:
        self.assertIn("function Get-PreviewContent", SCRIPT)
        for button in ("btnCopyMd", "btnCopyTxt", "btnLeer"):
            body = self._click_handler(button)
            self.assertIn("Get-PreviewContent", body, button)
            self.assertNotIn("$textBox.Text", body, button)
        for function in ("Export-PreviewPdf", "Export-SpeechMp3"):
            body = re.search(r"function " + function + r" \{(?P<body>.*?)\n\}", SCRIPT, re.DOTALL).group("body")
            self.assertIn("Get-PreviewContent", body, function)
            self.assertNotIn("$textBox.Text", body, function)

    def test_preview_offers_to_bring_the_answer_to_the_editor(self) -> None:
        self.assertIn("$tabPreview.Controls.Add($previewResultBar)", SCRIPT)
        self.assertNotIn("$previewResultBar.BringToFront()", SCRIPT)
        body = self._click_handler("btnUseResult")
        self.assertIn("Set-EditorText $script:aiResult", body)
        self.assertIn("Clear-AiResult", self._click_handler("btnDismissResult"))
        self.assertIn("Clear-AiResult", self._click_handler("btnLimpiar"))

    def test_version_uses_requested_format(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^v:\d{2}\.\d{2}\.\d{2}-\d{2}\.\d{2}$")


if __name__ == "__main__":
    unittest.main()
