"""Historial: the last texts of the Editor, newest first, kept in the
settings.json both apps share. A text already in the list is not added again;
a loaded text that was changed comes back as a new entry on top."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import history, settings

NOW = datetime(2026, 11, 19, 14, 5, 7)


class HistoryRulesTests(unittest.TestCase):
    def test_a_new_text_goes_on_top_with_its_date(self):
        entries, added = history.add([{"text": "viejo", "saved_at": "2026-11-18 09:00:00"}],
                                     "nuevo", 10, NOW)
        self.assertTrue(added)
        self.assertEqual(entries, [{"text": "nuevo", "saved_at": "2026-11-19 14:05:07"},
                                   {"text": "viejo", "saved_at": "2026-11-18 09:00:00"}])

    def test_empty_text_and_a_text_already_listed_are_not_added(self):
        start = [{"text": "uno", "saved_at": "a"}, {"text": "dos", "saved_at": "b"}]
        for text in ("", "   \r\n  ", "dos", "dos\r\n", "dos  "):
            entries, added = history.add(start, text, 10, NOW)
            self.assertFalse(added, text)
            self.assertEqual(entries, start)

    def test_a_changed_text_is_a_new_entry_on_top_and_the_original_stays(self):
        start = [{"text": "uno", "saved_at": "a"}, {"text": "dos", "saved_at": "b"}]
        entries, added = history.add(start, "dos cambiado", 10, NOW)
        self.assertTrue(added)
        self.assertEqual([entry["text"] for entry in entries], ["dos cambiado", "uno", "dos"])

    def test_the_list_keeps_only_the_limit_newest_first(self):
        entries = []
        for number in range(5):
            entries, _ = history.add(entries, f"texto {number}", 3, NOW)
        self.assertEqual([entry["text"] for entry in entries], ["texto 4", "texto 3", "texto 2"])

    def test_the_ai_answer_is_kept_with_its_text(self):
        entries, added = history.add([], "pregunta", 10, NOW, preview="respuesta\r\n")
        self.assertTrue(added)
        self.assertEqual(entries, [{"text": "pregunta", "saved_at": "2026-11-19 14:05:07",
                                    "preview": "respuesta"}])
        # The same pair is not saved twice; the same text with another answer is new.
        self.assertFalse(history.add(entries, "pregunta", 10, NOW, preview="respuesta")[1])
        entries, added = history.add(entries, "pregunta", 10, NOW, preview="otra respuesta")
        self.assertTrue(added)
        entries, added = history.add(entries, "pregunta", 10, NOW)
        self.assertTrue(added)
        self.assertEqual([entry.get("preview") for entry in entries], [None, "otra respuesta", "respuesta"])

    def test_model_and_attachments_are_kept_with_the_text(self):
        entries, added = history.add([], "pregunta", 10, NOW, preview="respuesta",
                                     model="qwen/qwen3.8-27b", attachments=["C:/a.png", "C:/b.pdf"])
        self.assertTrue(added)
        self.assertEqual(entries[0], {"text": "pregunta", "preview": "respuesta",
                                      "model": "qwen/qwen3.8-27b",
                                      "attachments": ["C:/a.png", "C:/b.pdf"],
                                      "saved_at": "2026-11-19 14:05:07"})
        self.assertEqual(history.clean_entries(entries), entries)
        # The same text with another model or other files is a new entry.
        self.assertFalse(history.add(entries, "pregunta", 10, NOW, preview="respuesta",
                                     model="qwen/qwen3.8-27b",
                                     attachments=["C:/a.png", "C:/b.pdf"])[1])
        self.assertTrue(history.add(entries, "pregunta", 10, NOW, preview="respuesta",
                                    model="openai/gpt-oss-120b",
                                    attachments=["C:/a.png", "C:/b.pdf"])[1])
        self.assertTrue(history.add(entries, "pregunta", 10, NOW, preview="respuesta",
                                    model="qwen/qwen3.8-27b", attachments=["C:/a.png"])[1])

    def test_windows_line_ends_are_stored_as_new_lines(self):
        entries, _ = history.add([], "a\r\nb\r\n", 10, NOW)
        self.assertEqual(entries[0]["text"], "a\nb")

    def test_limit_is_a_number_from_1_to_50_and_defaults_to_10(self):
        self.assertEqual([history.clean_limit(value) for value in (0, 1, 7, "20", 50, 99, None, "x")],
                         [1, 1, 7, 20, 50, 50, 10, 10])

    def test_label_shows_day_month_time_and_the_first_line(self):
        entry = {"text": "\n  Primera línea del texto  \nsegunda", "saved_at": "2026-11-19 14:05:07"}
        self.assertEqual(history.label(entry), "19/11 14:05 · Primera línea del texto")
        long_entry = {"text": "x" * 80, "saved_at": "2026-11-19 14:05:07"}
        self.assertEqual(history.label(long_entry), "19/11 14:05 · " + "x" * 59 + "…")


class ApiHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.api = main.Api(settings_dir=self._tmp.name, legacy_dir=self._tmp.name + "-legacy")

    def stored(self) -> dict:
        with open(os.path.join(self._tmp.name, "settings.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_texts_are_saved_listed_and_taken_back(self):
        self.assertEqual(self.api.history_list(),
                         {"items": [], "limit": 10, "count_text": "Sin textos guardados."})
        self.assertTrue(self.api.history_add("primero")["added"])
        self.assertTrue(self.api.history_add("segundo\r\nlínea")["added"])
        self.assertFalse(self.api.history_add("primero")["added"])
        items = self.api.history_list()["items"]
        self.assertEqual([item["index"] for item in items], [0, 1])
        self.assertTrue(items[0]["label"].endswith(" · segundo"))
        self.assertEqual(self.api.history_take(0)["text"], "segundo\nlínea")
        self.assertEqual(self.api.history_take(1)["text"], "primero")
        self.assertFalse(self.api.history_take(5)["ok"])
        self.assertEqual([entry["text"] for entry in self.stored()["history"]],
                         ["segundo\nlínea", "primero"])

    def test_limit_is_saved_and_trims_the_list_at_once(self):
        for number in range(4):
            self.api.history_add(f"texto {number}")
        result = self.api.set_history_limit(2)
        self.assertEqual(result, {"ok": True, "limit": 2,
                                  "message": "Historial: se guardan los últimos 2 textos del Editor.",
                                  "count_text": "2 textos guardados."})
        self.assertEqual(self.stored()["history_limit"], 2)
        self.assertEqual([entry["text"] for entry in self.stored()["history"]], ["texto 3", "texto 2"])
        self.api.history_add("texto 4")
        self.assertEqual(len(self.stored()["history"]), 2)

    def test_trash_empties_the_list_and_keeps_every_other_setting(self):
        settings.save_settings({"theme": "light", "microphone": "JBL"}, self._tmp.name)
        self.api.history_add("algo")
        self.assertEqual(self.api.clear_history(), {"ok": True, "message": "Historial borrado.",
                                                    "count_text": "Sin textos guardados."})
        stored = self.stored()
        self.assertEqual(stored["history"], [])
        self.assertEqual((stored["theme"], stored["microphone"]), ("light", "JBL"))

    def test_one_text_is_removed_from_the_menu(self):
        for text in ("uno", "dos", "tres"):
            self.api.history_add(text)
        self.assertEqual(self.api.history_list()["count_text"], "3 textos guardados.")
        self.assertEqual(self.api.history_remove(1), {"ok": True, "message": "Texto quitado del historial.",
                                                      "count_text": "2 textos guardados."})
        self.assertEqual([entry["text"] for entry in self.stored()["history"]], ["tres", "uno"])
        self.assertFalse(self.api.history_remove(9)["ok"])
        self.api.history_remove(0)
        self.assertEqual(self.api.history_list()["count_text"], "1 texto guardado.")

    def test_model_and_attachments_are_saved_and_attached_again(self):
        folder = self._tmp.name
        first, second = (os.path.join(folder, name) for name in ("notas.txt", "datos.md"))
        for path in (first, second):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("contenido")
        self.api.add_attachments([first, second])
        self.api.history_add("con adjuntos", "respuesta")
        taken = self.api.history_take(0)
        self.assertEqual((taken["model"], taken["attachments"]), ("openai/gpt-oss-120b", [first, second]))
        self.api.clear_attachments()
        os.remove(second)
        restored = self.api.history_attach(taken["attachments"])
        self.assertEqual([item["name"] for item in restored["items"]], ["notas.txt"])
        self.assertEqual((restored["missing"], restored["errors"]), (["datos.md"], []))
        self.assertEqual(self.api.history_attach([])["items"], [])

    def test_closing_saves_the_last_editor_text(self):
        self.api.history_note("escrito antes de cerrar")
        self.api.save_editor_history()
        self.assertEqual(self.stored()["history"][0]["text"], "escrito antes de cerrar")

    def test_text_and_ai_answer_come_back_together(self):
        self.api.history_add("pregunta", "respuesta de la IA")
        self.assertEqual(self.api.history_take(0),
                         {"ok": True, "text": "pregunta", "preview": "respuesta de la IA",
                          "model": "openai/gpt-oss-120b", "attachments": []})
        self.api.history_note("otra pregunta", "otra respuesta")
        self.api.save_editor_history()
        saved = self.stored()["history"][0]
        self.assertEqual((saved["text"], saved["preview"]), ("otra pregunta", "otra respuesta"))


if __name__ == "__main__":
    unittest.main()
