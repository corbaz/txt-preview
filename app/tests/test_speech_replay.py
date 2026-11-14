"""Tests for replay timings and the atempo filter chain (S6), plus the
speech Api behaviours around Repetir (S13/T20): the repetition must honor
the speed slider current at the moment it is pressed, and Play must switch
the voice when the text language differs from the selected voice language."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import settings
from txt_core.speech import voices
from txt_core.speech import engine as engine_module
from txt_core.speech.engine import ReplayCache, SpeechEngine
from txt_core.speech.marks import speech_words_key
from txt_core.speech.replay import (
    build_atempo_filter,
    format_replay_time,
    get_replay_word_timings,
)


class FakeProcess:
    """Popen-like fake (same shape as the lifecycle-test double)."""

    def __init__(self, args, log=None):
        self.args = list(args)
        self.returncode = None
        self.pid = 5150
        self.stderr = b""
        self.log = log if log is not None else []

    def poll(self):
        return self.returncode


class FakeRunner:
    def __init__(self, log=None):
        self.processes = []
        self.log = log if log is not None else []

    def __call__(self, args, **kwargs):
        self.log.append("spawn")
        process = FakeProcess(args, self.log)
        self.processes.append(process)
        return process


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


VOICE_CATALOG = [
    {"name": "es-ES-ElviraNeural", "culture": "es-ES", "gender": "Female",
     "display_name": "Edge · es-ES-ElviraNeural (Female)"},
    {"name": "es-CR-JuanNeural", "culture": "es-CR", "gender": "Male",
     "display_name": "Edge · es-CR-JuanNeural (Male)"},
    {"name": "en-US-AndrewMultilingualNeural", "culture": "en-US", "gender": "Male",
     "display_name": "Edge · en-US-AndrewMultilingualNeural (Male)"},
    {"name": "en-US-EmmaMultilingualNeural", "culture": "en-US", "gender": "Female",
     "display_name": "Edge · en-US-EmmaMultilingualNeural (Female)"},
]


class SpeechApiTestCase(unittest.TestCase):
    """Api with a temp settings dir and a real engine on a fake runner."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings_dir = self._tmp.name
        self.log = []
        self.runner = FakeRunner(self.log)
        self.messages = []
        self.api = main.Api(settings_dir=self.settings_dir,
                            legacy_dir=self._tmp.name + "-legacy")
        self.api.engine = SpeechEngine(
            python_command="fakepython", ffplay_command="fakeffplay",
            ffprobe_command=None,
            emit=lambda level, message: self.messages.append((level, message)),
            runner=self.runner,
        )

    def save_catalog(self):
        voices.save_voice_cache(VOICE_CATALOG, self.settings_dir)

    def replay_media(self):
        import os
        handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.remove(handle.name))
        return handle.name


class TestReplayHonorsTheSliderSpeed(SpeechApiTestCase):
    """S13 rule 1: Repetir must use the speed current when it is pressed
    (or changed during the repetition), never the generation speed."""

    def start_replay(self):
        self.api.engine.replay = ReplayCache(
            file=self.replay_media(), duration=10.0, voice_display="Elvira")
        self.api.engine.start_replay_playback()
        self.assertEqual(self.api.engine.provider, "Replay")
        self.assertEqual(self.api.engine.mode, "Playing")

    def af_filter(self):
        args = self.api.engine.player_process.args
        return args[args.index("-af") + 1]

    def test_speed_change_during_replay_uses_the_new_tempo(self):
        self.start_replay()  # audio generated at speed 100
        self.api.set_speech_speed(50)
        self.assertEqual(self.af_filter(), "atempo=0.5")
        self.assertEqual(self.api._speech_speed, 50)

    def test_doubling_the_speed_yields_atempo_2(self):
        self.start_replay()
        self.api.set_speech_speed(200)
        self.assertEqual(self.af_filter(), "atempo=2.0")

    def test_paused_replay_stays_paused_at_the_new_tempo(self):
        self.start_replay()
        with mock.patch.object(engine_module.SuspendResume, "suspend"), \
                mock.patch.object(engine_module.SuspendResume, "resume"):
            self.api.engine.pause()
            self.assertEqual(self.api.engine.mode, "Paused")
            self.api.set_speech_speed(150)
        self.assertEqual(self.af_filter(), "atempo=1.5")
        self.assertEqual(self.api.engine.mode, "Paused")


class TestPlaySwitchesVoiceToTheTextLanguage(SpeechApiTestCase):
    """S13 rule 2: Play detects the text language and, when it differs from
    the selected voice language, switches to that language's default voice
    keeping the gender; matching languages keep the chosen voice."""

    def setUp(self):
        super().setUp()
        self.api.engine = mock.Mock()
        self.save_catalog()
        # These cases start from a chosen Spanish female voice.
        self.api._speech_voice = "es-ES-ElviraNeural"

    def start(self, text):
        return self.api.start_speech(text)

    def test_english_text_switches_the_spanish_voice_to_the_en_default(self):
        result = self.start("The house was old and the garden was full of trees.")
        self.assertTrue(result["voice_switched"])
        self.assertEqual(result["voice"], "en-US-EmmaMultilingualNeural")
        self.assertEqual(result["voice_language"], "en")
        self.assertEqual(result["message"],
                         "Texto en inglés: se usó la voz en-US-EmmaMultilingualNeural.")
        # The reading itself uses the resolved voice.
        self.assertEqual(self.api._speech_voice, "en-US-EmmaMultilingualNeural")
        self.assertEqual(self.api.engine.start_edge_session.call_args[0][2],
                         "en-US-EmmaMultilingualNeural")
        # The switch persists like set_speech_voice does.
        self.assertEqual(
            settings.load_settings(self.settings_dir)["speech_voice"],
            "en-US-EmmaMultilingualNeural")

    def test_spanish_text_switches_an_english_voice_to_the_es_default(self):
        self.api.set_speech_voice("en-US-AndrewMultilingualNeural")
        result = self.start("El perro de Juan corre por la playa y la gente.")
        self.assertTrue(result["voice_switched"])
        self.assertEqual(result["voice"], "es-CR-JuanNeural")
        self.assertEqual(result["message"],
                         "Texto en español: se usó la voz es-CR-JuanNeural.")

    def test_matching_language_keeps_the_chosen_voice(self):
        self.api.set_speech_voice("es-CR-JuanNeural")
        result = self.start("El perro de Juan corre por la playa y la gente.")
        self.assertFalse(result["voice_switched"])
        self.assertEqual(result["voice"], "es-CR-JuanNeural")
        self.assertEqual(
            settings.load_settings(self.settings_dir)["speech_voice"],
            "es-CR-JuanNeural")

    def test_insufficient_signal_keeps_the_chosen_voice(self):
        result = self.start("asdf qwer zxcv 1234")
        self.assertFalse(result["voice_switched"])
        self.assertEqual(result["voice"], "es-ES-ElviraNeural")

    def test_no_catalog_keeps_the_chosen_voice(self):
        import os
        os.remove(os.path.join(self.settings_dir, "edge-voices.json"))
        result = self.start("The house was old and the garden was full of trees.")
        self.assertFalse(result["voice_switched"])
        self.assertEqual(result["voice"], "es-ES-ElviraNeural")

    def test_english_text_switches_a_spanish_male_voice_to_the_en_male_default(self):
        # S15/T22 truth table: ES text? No — EN text + ES Male voice: the
        # language changes, the active gender (Male) is preserved and the
        # default EN+Male voice is selected and persisted.
        self.api.set_speech_voice("es-CR-JuanNeural")
        result = self.start("The house was old and the garden was full of trees.")
        self.assertTrue(result["voice_switched"])
        self.assertEqual(result["voice"], "en-US-AndrewMultilingualNeural")
        self.assertEqual(result["voice_language"], "en")
        self.assertEqual(result["voice_gender"], "Male")
        self.assertEqual(
            settings.load_settings(self.settings_dir)["speech_voice"],
            "en-US-AndrewMultilingualNeural")

    def test_spanish_text_switches_an_english_female_voice_to_the_es_female_default(self):
        # S15/T22 truth table: ES text + EN Female voice: the language
        # changes, the active gender (Female) is preserved and the default
        # ES+Female voice is selected and persisted (here the catalog
        # fallback, because Ramona/Elena are not in it).
        self.api.set_speech_voice("en-US-EmmaMultilingualNeural")
        result = self.start("El perro de Juan corre por la playa y la gente.")
        self.assertTrue(result["voice_switched"])
        self.assertEqual(result["voice"], "es-ES-ElviraNeural")
        self.assertEqual(result["voice_language"], "es")
        self.assertEqual(result["voice_gender"], "Female")
        self.assertEqual(
            settings.load_settings(self.settings_dir)["speech_voice"],
            "es-ES-ElviraNeural")

    def test_result_keeps_the_voice_fields_without_a_switch(self):
        result = self.start("El perro de Juan corre por la playa y la gente.")
        self.assertTrue(result["ok"])
        self.assertEqual(result["voice"], "es-ES-ElviraNeural")
        self.assertEqual(result["voice_language"], "es")
        self.assertFalse(result["voice_switched"])


class TestVoiceDefaultsMap(SpeechApiTestCase):
    """S15/T22: list_voices exposes the legacy default voice for every
    language+gender combination, resolved by one source (voices.py
    default_voice_for) so the selector never duplicates the table in JS."""

    def test_all_four_combinations_get_the_legacy_default(self):
        self.save_catalog()
        result = self.api.list_voices()
        self.assertTrue(result["ok"])
        defaults = result["defaults"]
        # es|Female misses both preferred names in this catalog (Juan,
        # Andrew and Emma are present): the first catalog voice of the
        # combination is the fallback default.
        self.assertEqual(defaults["es|Male"], "es-CR-JuanNeural")
        self.assertEqual(defaults["es|Female"], "es-ES-ElviraNeural")
        self.assertEqual(defaults["en|Male"], "en-US-AndrewMultilingualNeural")
        self.assertEqual(defaults["en|Female"], "en-US-EmmaMultilingualNeural")

    def test_combination_without_voices_maps_to_none(self):
        voices.save_voice_cache(
            [voice for voice in VOICE_CATALOG
             if voice["name"] != "en-US-EmmaMultilingualNeural"],
            self.settings_dir)
        result = self.api.list_voices()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["defaults"]["en|Female"])
        self.assertEqual(result["defaults"]["es|Male"], "es-CR-JuanNeural")


class TestReplayHighlight(SpeechApiTestCase):
    WORDS = "uno\ndos\ntres\ncuatro"

    def setUp(self):
        super().setUp()
        self.api.engine.replay = ReplayCache(
            file=self.replay_media(), duration=4.0, voice_display="Elvira",
            words_key=speech_words_key(self.WORDS),
            mark_seconds=[0.0, 1.0, 2.0, 3.0],
            mark_words=[0, 1, 2, 3], eligible=False,
        )
        self.api.engine.provider = "Replay"
        self.api.engine.mode = "Playing"

    def test_replay_highlight_follows_the_cached_mark_at_current_position(self):
        with mock.patch.object(self.api, "_replay_position", return_value=1.20):
            state = self.api.speech_tick(self.WORDS)
        self.assertEqual(state["highlight_word_index"], 1)
        self.assertTrue(self.api.engine.replay_highlight_checked)
        self.assertTrue(self.api.engine.replay_highlight_valid)

    def test_replay_highlight_uses_the_lead_to_advance_near_a_boundary(self):
        with mock.patch.object(self.api, "_replay_position", return_value=0.95):
            state = self.api.speech_tick(self.WORDS)
        self.assertEqual(state["highlight_word_index"], 1)

    def test_replay_highlight_is_cleared_when_preview_words_do_not_match(self):
        with mock.patch.object(self.api, "_replay_position", return_value=2.20):
            state = self.api.speech_tick("texto\ndistinto")
        self.assertIsNone(state["highlight_word_index"])
        self.assertTrue(self.api.engine.replay_highlight_checked)
        self.assertFalse(self.api.engine.replay_highlight_valid)

    def test_replay_without_marks_has_no_highlight(self):
        self.api.engine.replay.mark_seconds = []
        self.api.engine.replay.mark_words = []
        with mock.patch.object(self.api, "_replay_position", return_value=2.20):
            state = self.api.speech_tick(self.WORDS)
        self.assertIsNone(state["highlight_word_index"])


if __name__ == "__main__":
    unittest.main()
