"""Volume slider, pause by restart (macOS) and when Repetir is available."""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from txt_core.speech import engine as engine_module
from test_speech_engine import SpeechEngineFixture


def player_args(process):
    return process.args


class TestVolume(SpeechEngineFixture, unittest.TestCase):
    def playing(self):
        self.engine.start_edge_session("hola mundo", "Edge · Voz", "es-CR-JuanNeural")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        return self.engine.player_process

    def test_player_starts_at_the_chosen_volume(self):
        self.engine.set_volume(60)
        player = self.playing()
        args = player_args(player)
        self.assertEqual(args[args.index("-volume") + 1], "60")
        self.assertEqual(args[-1], self.engine.chunks[0].media_file)

    def test_changing_the_volume_restarts_the_audio_at_the_same_position(self):
        first = self.playing()
        self.engine.player_started_at = time.time() - 2.0
        self.engine.set_volume(30)
        second = self.engine.player_process
        self.assertIsNot(second, first)
        args = player_args(second)
        self.assertEqual(args[args.index("-volume") + 1], "30")
        self.assertAlmostEqual(float(args[args.index("-ss") + 1]), 2.0, delta=0.1)
        self.assertAlmostEqual(self.engine.elapsed_seconds(), 2.0, delta=0.1)
        self.assertEqual(self.engine.mode, "Playing")

    def test_same_volume_does_not_restart(self):
        first = self.playing()
        self.engine.set_volume(100)
        self.assertIs(self.engine.player_process, first)

    def test_volume_changed_while_paused_applies_when_continuing(self):
        first = self.playing()
        with mock.patch.object(engine_module.SuspendResume, "suspend"), \
                mock.patch.object(engine_module.SuspendResume, "resume") as resume:
            self.engine.pause()
            self.engine.set_volume(50)
            self.assertIs(self.engine.player_process, first)  # still paused
            self.engine.resume()
            resume.assert_not_called()
        args = player_args(self.engine.player_process)
        self.assertEqual(args[args.index("-volume") + 1], "50")
        self.assertEqual(self.engine.mode, "Playing")


class TestPauseSuspends(SpeechEngineFixture, unittest.TestCase):
    def test_pause_suspends_the_player_on_every_system_like_txt_ps1(self):
        self.engine.start_edge_session("hola mundo", "Edge · Voz", "es-CR-JuanNeural")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        player = self.engine.player_process
        for platform in ("darwin", "win32"):
            with mock.patch.object(engine_module.sys, "platform", platform),                     mock.patch.object(engine_module.SuspendResume, "suspend") as suspend,                     mock.patch.object(engine_module.SuspendResume, "resume") as resume:
                self.engine.pause()
                self.assertIs(self.engine.player_process, player)
                self.engine.resume()
            suspend.assert_called_once_with(player.pid)
            resume.assert_called_once_with(player.pid)
            self.assertIs(self.engine.player_process, player)
            self.assertEqual(self.engine.mode, "Playing")

    def test_stop_after_the_whole_audio_is_generated_plays_nothing(self):
        """Detener only updates the Repetir length; nothing starts playing."""
        self.engine.start_edge_session(" ".join(["palabra"] * 400), "Edge · Voz",
                                       "es-CR-JuanNeural")
        for chunk in self.engine.chunks:
            self.ready_chunk(chunk)
        self.engine.poll()
        started = len(self.runner.processes)
        self.engine.stop_voice_playback()
        self.engine.poll()
        self.assertEqual(len(self.runner.processes), started)
        self.assertEqual(self.engine.mode, "Idle")
        self.assertIsNone(self.engine.player_process)
        self.assertTrue(self.engine.replay.file)
        self.assertGreater(self.engine.replay.duration, 0)
        self.engine._clear_replay_cache()


class TestReplayReady(SpeechEngineFixture, unittest.TestCase):
    def test_ready_only_when_every_block_is_generated(self):
        self.engine.start_edge_session(" ".join(["palabra"] * 400), "Edge · Voz",
                                       "es-CR-JuanNeural")
        self.assertGreater(len(self.engine.chunks), 1)
        self.assertFalse(self.engine.replay_ready())
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        self.assertFalse(self.engine.replay_ready())
        for chunk in self.engine.chunks[1:]:
            self.ready_chunk(chunk)
        self.engine.poll()
        self.assertTrue(self.engine.replay_ready())

    def test_partial_reading_never_offers_repetir(self):
        self.engine.start_edge_session("hola mundo", "Edge · Voz", "es-CR-JuanNeural",
                                       cache_eligible=False)
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        self.assertFalse(self.engine.replay_ready())

    def test_total_length_shows_as_soon_as_repetir_is_ready(self):
        """Not only after Detener: the length of the whole reading."""
        self.engine.start_edge_session(" ".join(["palabra"] * 400), "Edge · Voz",
                                       "es-CR-JuanNeural")
        self.assertEqual(self.engine.replay_ready_duration(), 0.0)
        for chunk in self.engine.chunks:
            self.ready_chunk(chunk)
        self.engine.poll()
        total = sum(chunk.duration_seconds for chunk in self.engine.chunks)
        self.assertGreater(total, 0)
        self.assertAlmostEqual(self.engine.replay_ready_duration(), total)

    def test_volume_zero_is_mute(self):
        self.engine.set_volume(0)
        self.assertEqual(self.engine.volume, 0)

    def test_saved_audio_is_ready(self):
        self.engine.replay.file = "x.mp3"
        self.assertTrue(self.engine.replay_ready())


if __name__ == "__main__":
    unittest.main()
