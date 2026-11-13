"""Tests for the Edge speech chunker (legacy Split-TextIntoSpeechChunks, S6)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech.chunker import split_text_into_speech_chunks


class TestSplitTextIntoSpeechChunks(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(split_text_into_speech_chunks("", 6), [])

    def test_single_paragraph_single_chunk(self):
        self.assertEqual(split_text_into_speech_chunks("un solo párrafo", 6), ["un solo párrafo"])

    def test_more_paragraphs_than_desired(self):
        text = "\n\n".join(f"p{i}" for i in range(10))
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertEqual(len(chunks), 6)
        # Every original paragraph survives, in order, joined by blank lines.
        rejoined = "\n\n".join(chunks)
        self.assertEqual(rejoined.replace("\r\n", "\n"), text)

    def test_fewer_paragraphs_than_desired(self):
        text = "\n\n".join(["a", "b", "c"])
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertEqual(len(chunks), 3)

    def test_groups_are_balanced_by_length(self):
        # 3 paragraphs of very different sizes, 3 desired chunks -> each alone.
        text = "\n\n".join(["corto", "x" * 200, "medio"])
        chunks = split_text_into_speech_chunks(text, 3)
        self.assertEqual(chunks, ["corto", "x" * 200, "medio"])

    def test_blank_paragraphs_are_skipped(self):
        text = "uno\n\n\n\n\ndos"
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertEqual(chunks, ["uno", "dos"])

    def test_group_joined_with_blank_line(self):
        # With desired=1 everything joins into one chunk separated by blank lines.
        text = "uno\n\ndos\n\ntres"
        chunks = split_text_into_speech_chunks(text, 1)
        self.assertEqual(chunks, ["uno\n\ndos\n\ntres"])

    def test_word_count_sums_match_original(self):
        import re
        text = "\n\n".join(["palabra " * n for n in (5, 20, 3, 12, 7)])
        chunks = split_text_into_speech_chunks(text, 6)
        original = len(re.findall(r"\S+", text))
        total = sum(len(re.findall(r"\S+", c)) for c in chunks)
        self.assertEqual(total, original)


if __name__ == "__main__":
    unittest.main()
