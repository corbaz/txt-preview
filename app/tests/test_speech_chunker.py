"""Tests for the Edge speech chunker (legacy Split-TextIntoSpeechChunks, S6;
S14/T21 rewrites the lead: a short first chunk so audio starts fast, then at
most desired-1 balanced chunks — no text lost or duplicated)."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech.chunker import split_text_into_speech_chunks

SEP = "\n\n"


def words(text):
    return re.findall(r"\S+", text)


def long_text(sentences, paragraph_sep=SEP):
    """Multi-sentence text over ~180 chars so the lead split applies."""
    return paragraph_sep.join(sentences)


class TestSplitTextIntoSpeechChunks(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(split_text_into_speech_chunks("", 6), [])

    def test_blank_text(self):
        self.assertEqual(split_text_into_speech_chunks("   \n\n  ", 6), [])

    def test_single_paragraph_single_chunk(self):
        self.assertEqual(split_text_into_speech_chunks("un solo párrafo", 6), ["un solo párrafo"])

    # ---- S14: short texts stay whole ---------------------------------------
    def test_short_text_is_one_chunk(self):
        # 20 words but 120 chars: inside both the word and char limits.
        text = "palabra " * 19 + "final"
        self.assertLessEqual(len(words(text)), 25)
        self.assertLessEqual(len(text), 180)
        self.assertEqual(split_text_into_speech_chunks(text, 6), [text])

    def test_short_multi_paragraph_text_keeps_one_chunk_with_its_paragraphs(self):
        text = "uno\n\n\ndos\n\ntres"
        self.assertEqual(split_text_into_speech_chunks(text, 6), [text])

    def test_desired_of_one_is_one_chunk(self):
        text = "uno\n\ndos\n\ntres"
        self.assertEqual(split_text_into_speech_chunks(text, 1), [text])

    # ---- S14: the lead chunk is short and ends at a sentence ----------------
    def test_long_text_lead_ends_at_the_first_sentence_after_eight_words(self):
        first = "Esta oración tiene exactamente ocho palabras en total justas."
        second = "Y esta segunda oración continúa el texto con más contenido nuevo."
        third = "Y una tercera oración termina el contenido para volverlo largo."
        text = " ".join([first, second, third])
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertEqual(chunks[0], first)
        self.assertEqual(len(chunks), 2)

    def test_first_sentence_of_two_words_is_not_a_tiny_lead(self):
        first = "Hola."
        second = "Esta segunda oración ya supera las ocho palabras mínimas."
        third = "Y una tercera oración llega después para cerrar el asunto."
        fourth = "Y una cuarta oración final empuja el texto fuera del rango."
        text = " ".join([first, second, third, fourth])
        chunks = split_text_into_speech_chunks(text, 6)
        lead_words = len(words(chunks[0]))
        self.assertGreaterEqual(lead_words, 8)
        self.assertLessEqual(lead_words, 25)
        self.assertLessEqual(len(chunks[0]), 180)
        self.assertTrue(chunks[0].startswith("Hola."))

    def test_lead_never_exceeds_twenty_five_words_or_one_eighty_chars(self):
        first = "Esta oración ya arranca con nueve palabras así que es razonable."
        filler = " " + "palabra adicional " * 40
        text = first + filler
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertLessEqual(len(words(chunks[0])), 25)
        self.assertLessEqual(len(chunks[0]), 180)
        self.assertGreaterEqual(len(words(chunks[0])), 8)

    def test_first_sentence_longer_than_the_cap_cuts_at_a_word_boundary(self):
        # One 30-word sentence: no sentence boundary inside the range, so the
        # lead cuts at the last word boundary at or before 25 words.
        text = " ".join(f"palabra{i}" for i in range(30)) + "."
        chunks = split_text_into_speech_chunks(text, 6)
        lead = chunks[0]
        self.assertEqual(len(words(lead)), 25)
        self.assertTrue(lead.endswith("palabra24"))
        self.assertFalse(lead.endswith("."))

    def test_one_long_paragraph_splits_without_losing_words(self):
        text = " ".join(f"palabra{i}" for i in range(40))
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(len(chunks), 6)
        self.assertLessEqual(len(words(chunks[0])), 25)

    def test_total_chunks_never_exceed_desired(self):
        text = SEP.join(
            f"Oración número {i} con varias palabras dentro para partir." for i in range(12))
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertLessEqual(len(chunks), 6)
        self.assertGreater(len(chunks), 1)

    def test_all_original_words_appear_exactly_once_in_order(self):
        text = SEP.join(
            f"Oración número {i} con varias palabras dentro para partir." for i in range(12))
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertEqual(words(" ".join(chunks)), words(text))

    def test_paragraph_boundaries_and_punctuation_are_preserved(self):
        sentences = [f"Oración número {i} con varias palabras dentro para partir."
                     for i in range(12)]
        text = SEP.join(sentences)
        chunks = split_text_into_speech_chunks(text, 6)
        rejoined = SEP.join(chunks)
        # Every paragraph break survives as a blank line in the joined chunks.
        self.assertEqual(rejoined.count("\n\n"), text.count("\n\n"))
        for sentence in sentences:
            self.assertIn(sentence, rejoined)

    def test_blank_paragraphs_are_preserved_in_the_chunks(self):
        sentences = [f"Oración número {i} con varias palabras dentro para partir."
                     for i in range(6)]
        text = SEP.join(sentences[:3] + ["", ""] + sentences[3:])
        chunks = split_text_into_speech_chunks(text, 6)
        rejoined = SEP.join(chunks)
        self.assertEqual(words(rejoined), words(text))

    def test_rest_splits_into_at_most_desired_minus_one(self):
        # 6 long sentences: lead + up to 5 balanced rest chunks.
        sentences = [f"Oración número {i} con muchas palabras para partir bien." for i in range(6)]
        text = SEP.join(sentences)
        chunks = split_text_into_speech_chunks(text, 6)
        self.assertLessEqual(len(chunks), 6)
        self.assertEqual(words(" ".join(chunks)), words(text))

    def test_remaining_balanced_groups_still_balance_by_length(self):
        # Long multi-paragraph text (27 words): the lead takes the first
        # paragraph at its boundary and the rest keeps whole paragraph groups.
        para1 = ("palabra " * 10).strip()
        para2 = "x" * 200
        para3 = ("palabra " * 15).strip() + " fin"
        text = SEP.join([para1, para2, para3])
        chunks = split_text_into_speech_chunks(text, 3)
        self.assertEqual(chunks, [para1, para2, para3])

    def test_no_word_is_ever_split(self):
        text = " ".join(f"palabra{i}" for i in range(40))
        for chunk in split_text_into_speech_chunks(text, 6):
            for token in words(chunk):
                self.assertIn(token, text.split())


if __name__ == "__main__":
    unittest.main()
