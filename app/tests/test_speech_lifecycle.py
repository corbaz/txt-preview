"""Speech lifecycle tests (T19/S12): a restart or a close must terminate the
old audio (never two voices at once), a finished reading must return to Idle
so a later preview click never starts a new one, and closing the app stops
the audio before the window is destroyed.

Processes are fakes with poll/kill/wait/pid; no real ffplay or edge-tts runs.
"""
import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core.speech import engine as engine_module
from txt_core.speech.engine import ReplayCache, SpeechEngine


class FakeProcess:
    """Popen-like fake. kill() does not reap by itself, so a suspended or
    stuck process can be simulated (kill observed, poll() still None)."""

    def __init__(self, args, log=None):
        self.args = list(args)
        self.returncode = None
        self.pid = 5150
        self.kill_calls = 0
        self.wait_calls = 0
        self.wait_timeout = None
        self.stderr = io.BytesIO(b"")
        self.log = log if log is not None else []

    def poll(self):
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self.log.append("kill")

    def wait(self, timeout=None):
        self.wait_calls += 1
        self.wait_timeout = timeout
        return self.returncode

    def finish(self, exit_code):
        self.returncode = exit_code


class FakeRunner:
    def __init__(self, log=None):
        self.processes = []
        self.log = log if log is not None else []

    def __call__(self, args, **kwargs):
        self.log.append("spawn")
        process = FakeProcess(args, self.log)
        self.processes.append(process)
        return process


class EngineFixture(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.runner = FakeRunner(self.log)
        self.messages = []
        self.engine = SpeechEngine(
            python_command="fakepython",
            ffplay_command="fakeffplay",
            ffprobe_command=None,
            emit=lambda level, message: self.messages.append((level, message)),
            runner=self.runner,
        )

    def ready_chunk(self, chunk, timings=None):
        """Simulate edge_tts_words.py finishing: media + timing files appear."""
        with open(chunk.media_file, "wb") as handle:
            handle.write(b"ID3fake")
        if timings is None:
            timings = [{"text": word, "start_seconds": i * 0.5}
                       for i, word in enumerate(chunk.text.split())]
        with open(chunk.timing_file, "w", encoding="utf-8") as handle:
            import json
            json.dump(timings, handle)
        chunk.process.finish(0)

    def start_session(self, text="hola mundo", words="hola\nmundo"):
        self.engine.start_edge_session(text, "Elvira (es-ES)", "es-ES-ElviraNeural")
        self.engine.initialize_alignment(words)

    def cleanup_replay_file(self):
        path = self.engine.replay.file
        if path:
            self.addCleanup(lambda: os.path.exists(path) and os.remove(path))


class TestTerminateProcess(EngineFixture):
    def test_live_process_is_killed_and_reaped_with_a_short_timeout(self):
        process = FakeProcess(["fakeffplay", "a.mp3"], self.log)
        engine_module._terminate_process(process)
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, 1)
        self.assertEqual(process.wait_timeout, 3)

    def test_dead_or_none_processes_are_ignored(self):
        engine_module._terminate_process(None)
        dead = FakeProcess(["fakeffplay"], self.log)
        dead.finish(0)
        engine_module._terminate_process(dead)
        self.assertEqual(dead.kill_calls, 0)
        self.assertEqual(self.log, [])


class TestStopTerminatesProcesses(EngineFixture):
    def test_stop_kills_the_live_player_and_live_generators(self):
        self.start_session("uno\n\ndos", words="uno\ndos")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        player = self.engine.player_process
        generator = self.engine.chunks[1].process
        self.assertIsNotNone(player)
        self.assertIsNotNone(generator)

        self.engine.stop_voice_playback()

        self.assertEqual(player.kill_calls, 1)
        self.assertEqual(player.wait_calls, 1)
        self.assertEqual(generator.kill_calls, 1)
        self.assertEqual(generator.wait_calls, 1)
        self.assertIsNone(self.engine.player_process)
        self.assertEqual(self.engine.mode, "Idle")

    def test_stop_tolerates_dead_or_missing_processes(self):
        self.start_session("hola mundo")
        dead_generator = self.engine.chunks[0].process
        dead_generator.finish(0)
        self.engine.player_process = None
        self.engine.stop_voice_playback()  # must not raise
        self.assertEqual(dead_generator.kill_calls, 0)

    def test_stop_never_leaves_the_replay_player_running(self):
        self.engine.replay = ReplayCache(
            file=self._replay_media(), duration=10.0, voice_display="Elvira")
        self.engine.start_replay_playback()
        player = self.engine.player_process
        self.engine.stop_voice_playback()
        self.assertEqual(player.kill_calls, 1)

    def _replay_media(self):
        handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.remove(handle.name))
        return handle.name

    def test_stop_kills_a_suspended_player(self):
        # Paused playback is a suspended process: poll() stays None, but the
        # kill must happen anyway (S12: Detener/Cerrar during pause).
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        player = self.engine.player_process
        with mock.patch.object(engine_module.SuspendResume, "suspend"), \
                mock.patch.object(engine_module.SuspendResume, "resume"):
            self.engine.pause()
        self.assertIsNone(player.poll())  # still suspended
        self.engine.stop_voice_playback()
        self.assertEqual(player.kill_calls, 1)

    def test_stop_survives_a_wait_timeout(self):
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        player = self.engine.player_process

        def stuck_wait(timeout=None):
            raise subprocess.TimeoutExpired(player.args, timeout)

        player.wait = stuck_wait
        self.engine.stop_voice_playback()  # must not raise
        self.assertEqual(player.kill_calls, 1)


class TestSetSpeedKillsTheOldPlayer(EngineFixture):
    def test_speed_restart_kills_the_old_player_once_before_the_new_session(self):
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        old_player = self.engine.player_process

        self.engine.set_speed(150)

        # Single-voice guarantee: the old player died exactly once, before
        # the restarted session spawned its generator.
        self.assertEqual(old_player.kill_calls, 1)
        self.assertEqual(self.log, ["spawn", "spawn", "kill", "spawn"])
        self.assertEqual(len(self.engine.chunks), 1)
        self.assertEqual(self.engine.chunks[0].process.args[0], "fakepython")


class TestReplayRestartKillsTheOldPlayer(EngineFixture):
    def test_replay_replaces_a_live_player_only_after_killing_it(self):
        self.engine.replay = ReplayCache(
            file=self._replay_media(), duration=10.0, voice_display="Elvira")
        self.engine.start_replay_playback()
        first = self.engine.player_process

        self.engine.start_replay_playback(2.0)

        self.assertEqual(first.kill_calls, 1)
        self.assertIsNot(self.engine.player_process, first)
        self.assertEqual(self.log[-2:], ["kill", "spawn"])

    def _replay_media(self):
        handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.remove(handle.name))
        return handle.name


class TestNaturalCompletion(EngineFixture):
    """poll() at the end of the last chunk (legacy Start-CurrentEdgeChunk tail)."""

    def setUp(self):
        super().setUp()
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        self.engine.player_process.finish(0)
        self.engine.poll()

    def test_finishing_the_last_chunk_returns_to_idle_and_saves_the_replay_cache(self):
        self.assertEqual(self.engine.mode, "Idle")
        self.assertEqual(self.messages[-1], ("info", "Lectura con voz Edge finalizada."))
        # The Repetir cache is saved exactly like a manual stop would.
        self.assertTrue(self.engine.replay.file)
        self.assertTrue(os.path.isfile(self.engine.replay.file))
        self.assertGreater(self.engine.replay.duration, 0)
        self.assertEqual(self.engine.replay.mark_words, [0, 1])
        self.assertFalse(self.engine.replay.eligible)
        # The chunk audio files are dropped like a manual stop.
        self.assertFalse(os.path.isfile(self.engine.chunks[0].media_file))
        self.cleanup_replay_file()

    def test_completion_is_emitted_once(self):
        before = len(self.messages)
        self.engine.poll()
        self.assertEqual(len(self.messages), before)
        self.assertEqual(self.engine.mode, "Idle")


class ApiFixture(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.runner = FakeRunner(self.log)
        self.messages = []
        self.api = main.Api()
        self.engine = SpeechEngine(
            python_command="fakepython",
            ffplay_command="fakeffplay",
            ffprobe_command=None,
            emit=lambda level, message: self.messages.append((level, message)),
            runner=self.runner,
        )
        self.api.engine = self.engine

    def finished_session(self):
        self.engine.start_edge_session("hola mundo", "Elvira (es-ES)",
                                       "es-ES-ElviraNeural")
        self.engine.initialize_alignment("hola\nmundo")
        chunk = self.engine.chunks[0]
        with open(chunk.media_file, "wb") as handle:
            handle.write(b"ID3fake")
        import json
        with open(chunk.timing_file, "w", encoding="utf-8") as handle:
            json.dump([{"text": "hola", "start_seconds": 0.0},
                       {"text": "mundo", "start_seconds": 0.5}], handle)
        chunk.process.finish(0)
        self.engine.poll()
        self.engine.player_process.finish(0)
        self.engine.poll()
        if self.engine.replay.file:
            self.addCleanup(
                lambda: os.path.exists(self.engine.replay.file)
                and os.remove(self.engine.replay.file))
        return chunk


class TestReplayCompletion(EngineFixture):
    def test_finishing_a_replay_returns_to_idle_with_the_legacy_message(self):
        # Detener left a replay cache; Repetir started and its player exited.
        self.engine.replay = ReplayCache(
            file="", duration=10.0, voice_display="Elvira (es-ES)",
            words_key="k", mark_seconds=[], mark_words=[], eligible=False)
        self.engine.provider = "Replay"
        self.engine.mode = "Playing"
        player = FakeProcess(["fakeffplay", "replay.mp3"], self.log)
        self.engine.player_process = player
        player.finish(0)

        self.engine.poll()  # RED: IndexError on the empty chunk list

        self.assertEqual(self.engine.mode, "Idle")
        self.assertIn(("info", "Repetición finalizada."), self.messages)
        # Emits once: a second poll with no player stays quiet.
        self.engine.poll()
        self.assertEqual(self.messages.count(("info", "Repetición finalizada.")), 1)

    def test_failing_replay_player_reports_an_error_and_goes_idle(self):
        self.engine.provider = "Replay"
        self.engine.mode = "Playing"
        player = FakeProcess(["fakeffplay", "replay.mp3"], self.log)
        self.engine.player_process = player
        player.finish(1)

        self.engine.poll()

        self.assertEqual(self.engine.mode, "Idle")
        self.assertEqual(self.messages[-1][0], "error")


class TestClickAfterCompletion(ApiFixture):
    """S12 bug 3: after a reading finished, a preview click must never
    restart the audio (legacy Move-SpeechToWord ignores Idle)."""

    def test_click_after_completion_is_ignored(self):
        self.finished_session()
        spawns = len(self.runner.processes)

        self.api.speech_click(0, "hola mundo")
        state = self.api.speech_tick()

        self.assertEqual(state["mode"], "Idle")
        self.assertEqual(len(self.runner.processes), spawns)
        self.assertEqual(self.engine.mode, "Idle")


class TestCloseAppStopsSpeech(unittest.TestCase):
    def test_close_app_stops_speech_before_destroying_the_window(self):
        api = main.Api()
        api.engine = mock.Mock()
        window = mock.Mock()
        api._window = window
        order = []
        window.destroy.side_effect = lambda: order.append("destroy")
        with mock.patch.object(api, "stop_speech",
                               side_effect=lambda: order.append("stop")):
            result = api.close_app()
        self.assertTrue(result["ok"])
        self.assertEqual(order, ["stop", "destroy"])

    def test_close_app_still_destroys_the_window_when_stop_fails(self):
        api = main.Api()
        api.engine = mock.Mock()
        window = mock.Mock()
        api._window = window
        with mock.patch.object(api, "stop_speech", side_effect=RuntimeError("boom")):
            result = api.close_app()
        self.assertTrue(result["ok"])
        window.destroy.assert_called_once_with()


class _FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _FakeWindow:
    def __init__(self):
        self.events = types.SimpleNamespace(closing=_FakeEvent())

    def destroy(self):
        pass


class TestCreateAppClosingHook(unittest.TestCase):
    """S12 bug 2: closing via the OS button stops the audio too."""

    def test_create_app_registers_a_closing_hook_that_stops_speech(self):
        api = main.Api()
        api.engine = mock.Mock()
        window = _FakeWindow()
        with mock.patch.object(main, "Api", return_value=api), \
                mock.patch.object(main.webview, "create_window", return_value=window), \
                mock.patch.object(main.webview, "start"), \
                mock.patch.object(main.Api, "initialize_settings"), \
                mock.patch.object(main.Api, "_startup_update_check"):
            main.create_app()
        self.assertEqual(len(window.events.closing.handlers), 1)
        window.events.closing.handlers[0]()  # must not raise
        api.engine.stop_voice_playback.assert_called_once_with()


class TestPreviewClickGating(unittest.TestCase):
    """S12 bug 3 (frontend half): the #preview click handler only bridges the
    click while the last known speech state is an active reading."""

    JS = (Path(__file__).resolve().parents[1] / "www" / "js" / "main.js"
          ).read_text(encoding="utf-8")

    def test_preview_click_handler_gates_on_the_last_speech_state(self):
        source = self.JS
        start = source.index('$("preview").addEventListener("click"')
        handler = source[start:start + 800]
        self.assertIn("speech_click", handler)
        gate = handler.index('if (!speechState || speechState.mode === "Idle") return;')
        self.assertLess(gate, handler.index("speech_click"))


if __name__ == "__main__":
    unittest.main()
