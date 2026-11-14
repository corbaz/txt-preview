"""PDF/MP3 exports ask only for the destination folder (txt.ps1 parity) and
generate a file name that never overwrites."""
import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import exports

NOW = datetime.datetime(2026, 11, 14, 9, 5)


class TestExportFilePath(unittest.TestCase):
    def test_name_is_lectura_with_date_and_time(self):
        path = exports.export_file_path("/dest", "pdf", now=NOW, exists=lambda p: False)
        self.assertEqual(Path(path), Path("/dest/lectura-20261114-0905.pdf"))

    def test_existing_files_are_never_overwritten(self):
        taken = {str(Path("/dest/lectura-20261114-0905.mp3")),
                 str(Path("/dest/lectura-20261114-0905-2.mp3"))}
        path = exports.export_file_path(
            "/dest", "mp3", now=NOW, exists=lambda p: str(Path(p)) in taken)
        self.assertEqual(Path(path), Path("/dest/lectura-20261114-0905-3.mp3"))


class FakeWindow:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def create_file_dialog(self, dialog_type, **kwargs):
        self.calls.append((dialog_type, kwargs))
        return self.answer


class TestExportFolderDialog(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.api = main.Api(settings_dir=self._dir.name)
        self.api._preview_text = "# Hola"

    def _export_pdf(self, window):
        self.api._window = window
        with mock.patch.object(main.sys, "platform", "darwin"), \
                mock.patch.object(main, "export_pdf_file") as writer:
            return self.api.export_pdf(), writer

    def test_pdf_goes_to_the_chosen_folder_with_a_generated_name(self):
        window = FakeWindow((self._dir.name,))
        result, writer = self._export_pdf(window)
        self.assertEqual(window.calls[0][0], main.webview.FileDialog.FOLDER)
        self.assertEqual(window.calls[0][1]["directory"],
                         str(Path.home() / "Documents"))
        target = Path(writer.call_args[0][1])
        self.assertEqual(target.parent, Path(self._dir.name))
        self.assertRegex(target.name, r"^lectura-\d{8}-\d{4}\.pdf$")
        self.assertEqual(result, {"ok": True, "path": str(target),
                                  "message": f"PDF guardado en {target}"})

    def test_next_export_starts_in_the_last_folder(self):
        self._export_pdf(FakeWindow((self._dir.name,)))
        window = FakeWindow((self._dir.name,))
        self._export_pdf(window)
        self.assertEqual(window.calls[0][1]["directory"], self._dir.name)

    def test_cancelled_dialog_exports_nothing(self):
        result, writer = self._export_pdf(FakeWindow(None))
        writer.assert_not_called()
        self.assertEqual(result, {"ok": False, "message": ""})

    def test_windows_uses_the_folder_tree_dialog(self):
        self.api._window = FakeWindow(None)
        with mock.patch.object(main.sys, "platform", "win32"), \
                mock.patch.object(main, "_windows_folder_tree",
                                  return_value=self._dir.name) as tree, \
                mock.patch.object(main, "export_mp3_file") as writer:
            self.api.engine = mock.Mock(applied_speed=100)
            result = self.api.export_mp3()
        self.assertEqual(tree.call_args[0][1], "Elegí la carpeta donde guardar el MP3")
        self.assertEqual(self.api._window.calls, [])
        self.assertRegex(Path(writer.call_args[0][1]).name, r"^lectura-\d{8}-\d{4}\.mp3$")
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
