"""Language detection and the legacy default voice per language+gender
(S13 rule 2, txt.ps1:2602-2607). Pure unit tests: no catalog process runs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech import voices
from txt_core.language import detect_language

SPANISH_PARAGRAPH = (
    "El perro de Juan corre por la playa y la gente se queda mirando "
    "cómo juega con la arena."
)
ENGLISH_PARAGRAPH = (
    "The house was old and the garden was full of trees, but it was not "
    "the best one in the town."
)
ACCENTED_SPANISH = (
    "¿Qué pasó aquí? Mamá cantó más canciones en la feria del pueblo "
    "y toda la familia bailó hasta el amanecer."
)


class TestDetectLanguage(unittest.TestCase):
    def test_spanish_paragraph_detects_es(self):
        self.assertEqual(detect_language(SPANISH_PARAGRAPH), "es")

    def test_english_paragraph_detects_en(self):
        self.assertEqual(detect_language(ENGLISH_PARAGRAPH), "en")

    def test_accented_spanish_detects_es(self):
        self.assertEqual(detect_language(ACCENTED_SPANISH), "es")

    def test_mixed_tie_stays_undecided(self):
        # 5 English marker words vs 5 Spanish marker words: no winner.
        self.assertIsNone(detect_language("the de of la and el to la in el"))

    def test_garbage_without_markers_stays_undecided(self):
        self.assertIsNone(detect_language("asdf qwer zxcv 1234 ipsum lorem"))

    def test_one_lone_marker_is_not_enough_signal(self):
        # Four words but a single marker: below the clear-margin bar.
        self.assertIsNone(detect_language("asdf qw the er"))

    def test_short_texts_stay_undecided(self):
        self.assertIsNone(detect_language("hola mundo"))
        self.assertIsNone(detect_language("¿Cómo estás?"))

    def test_empty_text_stays_undecided(self):
        self.assertIsNone(detect_language(""))
        self.assertIsNone(detect_language(None))
        self.assertIsNone(detect_language("   \n  "))

    def test_short_clear_dominance_still_detects(self):
        self.assertEqual(detect_language("la casa de Juan"), "es")
        self.assertEqual(detect_language("it was not the best"), "en")


def catalog(*pairs):
    """Catalog records like the real edge-voices.json cache."""
    return [
        voices._voice_record(name, "-".join(name.split("-")[:2]), gender)
        for name, gender in pairs
    ]


class TestDefaultVoiceFor(unittest.TestCase):
    FULL = catalog(
        ("es-ES-ElviraNeural", "Female"), ("es-CR-JuanNeural", "Male"),
        ("es-AR-TomasNeural", "Male"), ("es-DO-RamonaNeural", "Female"),
        ("es-AR-ElenaNeural", "Female"),
        ("en-US-AndrewMultilingualNeural", "Male"), ("en-US-GuyNeural", "Male"),
        ("en-US-EmmaMultilingualNeural", "Female"), ("en-US-JennyNeural", "Female"),
    )

    def test_legacy_defaults_win_when_present(self):
        # Legacy txt.ps1:2602-2607 priority order.
        self.assertEqual(voices.default_voice_for("es", "Male", self.FULL),
                         "es-CR-JuanNeural")
        self.assertEqual(voices.default_voice_for("es", "Female", self.FULL),
                         "es-DO-RamonaNeural")
        self.assertEqual(voices.default_voice_for("en", "Male", self.FULL),
                         "en-US-AndrewMultilingualNeural")
        self.assertEqual(voices.default_voice_for("en", "Female", self.FULL),
                         "en-US-EmmaMultilingualNeural")

    def test_second_legacy_choice_when_the_first_is_missing(self):
        partial = [voice for voice in self.FULL
                   if voice["name"] != "es-CR-JuanNeural"]
        self.assertEqual(voices.default_voice_for("es", "Male", partial),
                         "es-AR-TomasNeural")
        partial = [voice for voice in self.FULL
                   if voice["name"] != "en-US-EmmaMultilingualNeural"]
        self.assertEqual(voices.default_voice_for("en", "Female", partial),
                         "en-US-JennyNeural")

    def test_falls_back_to_the_first_catalog_voice_of_language_gender(self):
        fallback = catalog(("es-MX-JorgeNeural", "Male"),
                           ("en-US-AriaNeural", "Female"))
        self.assertEqual(voices.default_voice_for("es", "Male", fallback),
                         "es-MX-JorgeNeural")
        self.assertEqual(voices.default_voice_for("en", "Female", fallback),
                         "en-US-AriaNeural")

    def test_no_voice_for_the_language_returns_none(self):
        self.assertIsNone(voices.default_voice_for("es", "Male", []))
        self.assertIsNone(voices.default_voice_for(
            "en", "Female", catalog(("es-ES-ElviraNeural", "Female"))))

    def test_insufficient_signal_returns_none(self):
        self.assertIsNone(voices.default_voice_for("fr", "Male", self.FULL))
        self.assertIsNone(voices.default_voice_for("es", None, self.FULL))
        self.assertIsNone(voices.default_voice_for(None, "Female", self.FULL))


if __name__ == "__main__":
    unittest.main()
