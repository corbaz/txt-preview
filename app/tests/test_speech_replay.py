"""Tests for replay timings and the atempo filter chain (S6)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech.replay import build_atempo_filter, get_replay_word_timings, format_replay_time


class TestReplayWordTimings(unittest.TestCase):
    def test_collects_word_indices_and_seconds(self):
        # words: hola(0) mundo(1) esto(2); spoken with offsets.
        words = ["hola", "mundo", "esto"]
        spoken = [("hola", 0.0), ("mundo", 0.4), ("esto", 1.1)]
        result = get_replay_word_timings(
            mark_seconds=[s for _, s in spoken],
            spoken_words=[w for w, _ in spoken],
            words=words,
            start_cursor=-1,
        )
        self.assertEqual(result["words"], [0, 1, 2])
        self.assertEqual(result["seconds"], [0.0, 0.4, 1.1])

    def test_skips_words_that_do_not_advance(self):
        words = ["hola", "mundo"]
        spoken = [("hola", 0.0), ("zzz", 0.2), ("mundo", 0.5)]
        result = get_replay_word_timings([0.0, 0.2, 0.5], ["hola", "zzz", "mundo"], words, -1)
        # "zzz" misses once; cursor stays 0 -> no entry for it.
        self.assertEqual(result["words"], [0, 1])
        self.assertEqual(result["seconds"], [0.0, 0.5])

    def test_no_duplicate_last_index(self):
        words = ["hola", "mundo"]
        spoken = [("hola", 0.0), ("mundo", 0.4), ("otro", 0.8)]
        result = get_replay_word_timings([0.0, 0.4, 0.8], ["hola", "mundo", "otro"], words, -1)
        self.assertEqual(result["words"], [0, 1])


class TestAtempoFilter(unittest.TestCase):
    def test_no_filter_at_normal_speed(self):
        self.assertEqual(build_atempo_filter(1.0), "")

    def test_chain_for_4x(self):
        # Legacy loop: remaining=4 -> stage 2, remaining=2.0 -> final "atempo=2.0".
        self.assertEqual(build_atempo_filter(4.0), "atempo=2,atempo=2.0")

    def test_chain_for_quarter(self):
        self.assertEqual(build_atempo_filter(0.25), "atempo=0.5,atempo=0.5")

    def test_chain_for_3x(self):
        self.assertEqual(build_atempo_filter(3.0), "atempo=2,atempo=1.5")

    def test_simple_1_5x(self):
        self.assertEqual(build_atempo_filter(1.5), "atempo=1.5")

    def test_no_filter_within_epsilon(self):
        self.assertEqual(build_atempo_filter(1.0005), "")


class TestFormatReplayTime(unittest.TestCase):
    def test_minutes_seconds(self):
        self.assertEqual(format_replay_time(0), "0:00")
        self.assertEqual(format_replay_time(65.4), "1:05")
        self.assertEqual(format_replay_time(599.9), "9:59")


if __name__ == "__main__":
    unittest.main()
