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
        with mock.patch.object(engine_module, "PAUSE_BY_RESTART", False), \
                mock.patch.object(engine_module.SuspendResume, "suspend"), \
                mock.patch.object(engine_module.SuspendResume, "resume") as resume:
            self.engine.pause()
            self.engine.set_volume(50)
            self.assertIs(self.engine.player_process, first)  # still paused
            self.engine.resume()
            resume.assert_not_called()
        args = player_args(self.engine.player_process)
        self.assertEqual(args[args.index("-volume") + 1], "50")
        self.assertEqual(self.engine.mode, "Playing")


class TestPauseByRestart(SpeechEngineFixture, unittest.TestCase):
    def test_pause_stops_the_player_and_continue_starts_it_at_the_same_point(self):
        self.engine.start_edge_session("hola mundo", "Edge · Voz", "es-CR-JuanNeural")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        first = self.engine.player_process
        self.engine.player_started_at = time.time() - 1.5
        with mock.patch.object(engine_module, "PAUSE_BY_RESTART", True), \
                mock.patch.object(engine_module.SuspendResume, "suspend") as suspend:
            self.engine.pause()
            suspend.assert_not_called()
            self.assertIsNone(self.engine.player_process)
            self.assertEqual(self.engine.mode, "Paused")
            self.assertAlmostEqual(self.engine.elapsed_seconds(), 1.5, delta=0.1)
            self.engine.poll()  # a tick while paused never starts the audio
            self.assertIsNone(self.engine.player_process)
            self.engine.resume()
        second = self.engine.player_process
        self.assertIsNot(second, first)
        args = player_args(second)
        self.assertAlmostEqual(float(args[args.index("-ss") + 1]), 1.5, delta=0.1)
        self.assertEqual(self.engine.mode, "Playing")
        self.assertEqual(self.engine.current_index, 0)

    def test_replay_continues_from_the_paused_position(self):
        self.engine.replay.file = __file__  # any existing file
        self.engine.replay.duration = 30.0
        self.engine.start_replay_playback(4.0)
        self.engine.player_started_at = time.time() - 2.0
        with mock.patch.object(engine_module, "PAUSE_BY_RESTART", True):
            self.engine.pause()
            self.engine.resume()
        args = player_args(self.engine.player_process)
        self.assertAlmostEqual(float(args[args.index("-ss") + 1]), 6.0, delta=0.1)
        self.assertEqual(self.engine.provider, "Replay")
        self.assertEqual(self.engine.mode, "Playing")
        self.engine.replay.file = ""  # never delete the test file


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

    def test_saved_audio_is_ready(self):
        self.engine.replay.file = "x.mp3"
        self.assertTrue(self.engine.replay_ready())


if __name__ == "__main__":
    unittest.main()
