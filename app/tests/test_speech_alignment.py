"""Tests for the spoken-word alignment cursor (legacy Get-NextAlignmentCursor, S6).

Legacy constants: alignment window 8 words, 2 consecutive misses step forward.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech.alignment import next_alignment_cursor


class TestNextAlignmentCursor(unittest.TestCase):
    def test_empty_key_keeps_state(self):
        words = ["hola", "mundo"]
        self.assertEqual(next_alignment_cursor(words, 0, 1, "!!!"), (0, 1))

    def test_cursor_past_end_keeps_state(self):
        self.assertEqual(next_alignment_cursor(["hola"], 0, 0, "mundo"), (0, 0))

    def test_exact_match_at_next_advances(self):
        words = ["hola", "mundo"]
        self.assertEqual(next_alignment_cursor(words, 0, 0, "mundo"), (1, 0))

    def test_prefix_match_on_next_word_advances(self):
        # Prefix matching applies to the NEXT preview word only.
        words = ["hola", "hablando", "de", "esto"]
        self.assertEqual(next_alignment_cursor(words, 0, 0, "hablan"), (1, 0))

    def test_compound_beats_prefix_attempt_at_current(self):
        # Cursor already ON "hablando"; next is "de": spoken "hablan" stays via compound.
        words = ["hablando", "de", "esto"]
        self.assertEqual(next_alignment_cursor(words, 0, 0, "hablan"), (0, 0))

    def test_compound_token_stays_on_current(self):
        # Engine split a compound: current preview word contains the spoken key.
        words = ["medio", "ambiente"]
        self.assertEqual(next_alignment_cursor(words, 1, 0, "amb"), (1, 0))

    def test_exact_match_inside_window_jumps(self):
        # Skip up to 8 words ahead for an exact match only.
        words = ["a", "b", "c", "d", "e", "f", "g", "h", "objetivo", "j"]
        self.assertEqual(next_alignment_cursor(words, 0, 0, "objetivo"), (8, 0))

    def test_inexact_word_beyond_next_misses_without_stepping(self):
        words = ["a", "b", "c", "d", "e", "f", "g", "h", "objetivoo", "j"]
        # "objetivoo" is not an exact match: one miss, cursor stays until 2 misses.
        self.assertEqual(next_alignment_cursor(words, 0, 0, "objetivo"), (0, 1))

    def test_window_bounds_are_start_plus_eight_inclusive(self):
        # Window covers indices start+1 .. start+8: index 9 is reachable from start=1.
        words = [str(i) for i in range(10)]
        self.assertEqual(next_alignment_cursor(words, 0, 0, "9"), (9, 0))

    def test_two_consecutive_misses_step_forward(self):
        words = ["hola", "mundo"]
        cursor, misses = next_alignment_cursor(words, 0, 0, "zzz")
        self.assertEqual((cursor, misses), (0, 1))
        self.assertEqual(next_alignment_cursor(words, cursor, misses, "yyy"), (1, 0))

    def test_skips_empty_tokens(self):
        words = ["hola", "", "mundo"]
        self.assertEqual(next_alignment_cursor(words, 0, 0, "mundo"), (2, 0))

    def test_punctuation_in_spoken_word_ignored(self):
        words = ["hola", "mundo"]
        self.assertEqual(next_alignment_cursor(words, 0, 0, "¡Mundo!"), (1, 0))


if __name__ == "__main__":
    unittest.main()
