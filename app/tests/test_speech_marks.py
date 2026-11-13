"""Tests for Edge word marks and alignment keys (legacy Get-EdgeWordMarks et al., S6)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech.marks import (
    EdgeWordMark,
    edge_word_marks,
    get_mark_index_at,
    speech_alignment_key,
    speech_words_key,
    word_index_at_character,
)


class TestEdgeWordMarks(unittest.TestCase):
    def test_positions_follow_word_order_case_insensitive(self):
        text = "Hola mundo, esto es TXT"
        timings = [
            {"text": "hola", "start_seconds": 0.0},
            {"text": "mundo", "start_seconds": 0.4},
            {"text": "esto", "start_seconds": 1.1},
            {"text": "es", "start_seconds": 1.5},
            {"text": "TXT", "start_seconds": 1.8},
        ]
        marks = edge_word_marks(text, timings)
        self.assertEqual([m.character for m in marks], [0, 5, 12, 17, 20])
        self.assertEqual([m.start_seconds for m in marks], [0.0, 0.4, 1.1, 1.5, 1.8])

    def test_word_not_found_keeps_cursor(self):
        # If the spoken token is not in the text (e.g. numbers spoken differently),
        # the mark falls back to the current cursor position.
        marks = edge_word_marks("texto fijo", [{"text": "inexistente", "start_seconds": 2.0}])
        self.assertEqual(marks[0].character, 0)
        self.assertEqual(marks[0].text, "inexistente")

    def test_empty_word_timings_skipped(self):
        marks = edge_word_marks("algo", [{"text": "", "start_seconds": 0.0}, {"text": "algo", "start_seconds": 0.5}])
        self.assertEqual(len(marks), 1)

    def test_repeated_words_advance(self):
        text = "da da da"
        timings = [{"text": "da", "start_seconds": s} for s in (0.0, 0.3, 0.6)]
        marks = edge_word_marks(text, timings)
        self.assertEqual([m.character for m in marks], [0, 3, 6])


class TestWordIndexAtCharacter(unittest.TestCase):
    # Legacy replay-cache character-to-word mapping: the preview word index of
    # the token containing/preceding a character offset (\S+ tokens).
    def test_start_of_text(self):
        self.assertEqual(word_index_at_character("hola mundo", 0), 0)

    def test_middle_of_word(self):
        self.assertEqual(word_index_at_character("hola mundo", 2), 0)

    def test_between_words_points_at_previous_token(self):
        self.assertEqual(word_index_at_character("hola mundo", 4), 0)

    def test_at_next_word_start(self):
        self.assertEqual(word_index_at_character("hola mundo", 5), 1)

    def test_past_end_points_at_last_token(self):
        self.assertEqual(word_index_at_character("hola mundo", 99), 1)

    def test_empty_text(self):
        self.assertEqual(word_index_at_character("", 0), 0)

    def test_before_first_token(self):
        self.assertEqual(word_index_at_character("   hola", 1), 0)


class TestKeys(unittest.TestCase):
    def test_alignment_key_strips_non_alnum(self):
        self.assertEqual(speech_alignment_key("¡Hola, mundo!"), "holamundo")
        self.assertEqual(speech_alignment_key("número-1"), "número1")

    def test_words_key_is_stable_hex(self):
        key = speech_words_key("uno\ndos")
        self.assertEqual(key, speech_words_key("uno\ndos"))
        self.assertNotEqual(key, speech_words_key("uno\ntres"))
        self.assertRegex(key, r"^[0-9a-f]+$")


class TestMarkIndexAt(unittest.TestCase):
    def _marks(self):
        return [EdgeWordMark(start_seconds=s, character=i * 2, text="w")
                for i, s in enumerate((0.0, 0.5, 1.0, 2.0))]

    def test_binary_search_last_reached(self):
        marks = self._marks()
        self.assertEqual(get_mark_index_at(marks, 0.4, lead=0.0), 0)
        self.assertEqual(get_mark_index_at(marks, 0.5, lead=0.0), 1)
        self.assertEqual(get_mark_index_at(marks, 1.9, lead=0.0), 2)

    def test_lead_extends_lookup(self):
        marks = self._marks()
        self.assertEqual(get_mark_index_at(marks, 0.0, lead=0.5), 1)

    def test_before_first_mark(self):
        self.assertEqual(get_mark_index_at(self._marks(), -1.0, lead=0.0), -1)

    def test_empty_marks(self):
        self.assertEqual(get_mark_index_at([], 5.0, lead=0.0), -1)


if __name__ == "__main__":
    unittest.main()
