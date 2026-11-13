"""Tests for the Edge speech engine state machine (legacy Update-EdgeVoicePlayback,
Start-CurrentEdgeChunk, Suspend-VoicePlayback, Save-SpeechReplayCache, S6).

Processes are injected through `runner`, so no real python/ffplay is needed and
no network call happens: generation is simulated by marking the fake process
exited and writing the media + timing files the pipeline would produce.
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech import engine as engine_module
from txt_core.speech.engine import Chunk, EdgeWordMark, ReplayCache, SpeechEngine


class FakeProcess:
    def __init__(self, args):
        self.args = list(args)
        self.returncode = None
        self.pid = 4242
        self.stderr = io.BytesIO(b"")

    def poll(self):
        return self.returncode

    def finish(self, exit_code):
        self.returncode = exit_code


class FakeRunner:
    def __init__(self):
        self.processes = []

    def __call__(self, args, **kwargs):
        process = FakeProcess(args)
        self.processes.append(process)
        return process


class SpeechEngineFixture:
    def setUp(self):
        self.runner = FakeRunner()
        self.messages = []
        self.engine = SpeechEngine(
            python_command="fakepython",
            ffplay_command="fakeffplay",
            ffprobe_command=None,
            emit=lambda level, message: self.messages.append((level, message)),
            runner=self.runner,
        )

    # ---- helpers -----------------------------------------------------------
    def ready_chunk(self, chunk, timings=None):
        """Simulate edge_tts_words.py finishing: media + timing files appear."""
        with open(chunk.media_file, "wb") as handle:
            handle.write(b"ID3fake")
        if timings is None:
            timings = [{"text": word, "start_seconds": i * 0.5}
                       for i, word in enumerate(chunk.text.split())]
        with open(chunk.timing_file, "w", encoding="utf-8") as handle:
            json.dump(timings, handle)
        chunk.process.finish(0)

    def last_message(self):
        return self.messages[-1][1] if self.messages else ""

    def start_session(self, text="hola mundo", words="hola\nmundo"):
        self.engine.start_edge_session(text, "Elvira (es-ES)", "es-ES-ElviraNeural")
        self.engine.initialize_alignment(words)


class TestStartEdgeSession(SpeechEngineFixture, unittest.TestCase):
    def test_builds_chunks_and_spawns_generation_cli(self):
        text = "\n\n".join(f"párrafo número {i} con algo de texto" for i in range(7))
        self.engine.start_edge_session(text, "Elvira (es-ES)", "es-ES-ElviraNeural")
        self.assertEqual(self.engine.mode, "Generating")
        self.assertEqual(self.engine.provider, "Edge")
        self.assertEqual(len(self.engine.chunks), 6)

        generated = self.runner.processes[: len(self.engine.chunks)]
        self.assertEqual(len(generated), 6)
        for chunk, process in zip(self.engine.chunks, generated):
            self.assertTrue(os.path.isfile(chunk.text_file))
            with open(chunk.text_file, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), chunk.text)
            self.assertEqual(process.args, [
                "fakepython", str(engine_module.EDGE_TTS_WORDS_SCRIPT),
                "--voice", "es-ES-ElviraNeural",
                "--rate", "0",
                "--text-file", chunk.text_file,
                "--media-file", chunk.media_file,
                "--timings-file", chunk.timing_file,
            ])
            self.assertEqual(chunk.status, "Generating")

        # Word offsets accumulate per chunk over the preview word list.
        expected_start = 0
        for chunk in self.engine.chunks:
            self.assertEqual(chunk.start_word_index, expected_start)
            expected_start += len(chunk.text.split())


class TestPoll(SpeechEngineFixture, unittest.TestCase):
    def test_ready_chunk_starts_ffplay(self):
        self.start_session("hola mundo")
        chunk = self.engine.chunks[0]
        self.ready_chunk(chunk, [{"text": "hola", "start_seconds": 0.0}])
        self.engine.poll()
        # The same poll marks the chunk Ready and starts its player.
        self.assertEqual(chunk.status, "Playing")
        self.assertEqual(self.engine.mode, "Playing")
        self.assertEqual(self.engine.current_index, 0)
        self.assertEqual(chunk.word_marks,
                         [EdgeWordMark(0.0, 0, "hola")])
        ffplay = self.runner.processes[1].args
        self.assertEqual(ffplay[0], "fakeffplay")
        self.assertEqual(ffplay[1:-1], ["-nodisp", "-autoexit", "-loglevel", "error"])
        self.assertEqual(ffplay[-1], chunk.media_file)

    def test_player_exit_zero_advances_to_next_chunk(self):
        self.start_session("uno\n\ndos")
        for chunk in self.engine.chunks:
            self.ready_chunk(chunk)
        self.engine.poll()
        first_player = self.engine.player_process
        self.assertIsNotNone(first_player)
        first_player.finish(0)
        self.engine.poll()
        self.assertEqual(self.engine.chunks[0].status, "Played")
        self.assertEqual(self.engine.current_index, 1)
        self.assertEqual(self.engine.mode, "Playing")
        self.assertEqual(self.runner.processes[-1].args[-1], self.engine.chunks[1].media_file)

    def test_player_exit_one_stops_with_error(self):
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        self.engine.player_process.finish(1)
        self.engine.poll()
        self.assertEqual(self.engine.mode, "Idle")
        self.assertEqual(self.engine.provider, None)
        self.assertIn("No se pudo reproducir la voz Edge", self.last_message())

    def test_failed_generation_marks_chunk_failed(self):
        self.start_session("hola mundo")
        self.engine.chunks[0].process.finish(1)
        self.engine.poll()
        self.assertEqual(self.engine.chunks[0].status, "Failed")
        self.assertEqual(self.engine.mode, "Generating")


class TestPauseResume(SpeechEngineFixture, unittest.TestCase):
    def test_pause_freezes_clock_and_resume_shifts_start(self):
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        player = self.engine.player_process
        self.assertIsNotNone(player)
        with mock.patch.object(engine_module.SuspendResume, "suspend") as suspend, \
                mock.patch.object(engine_module.SuspendResume, "resume") as resume:
            self.engine.pause()
            suspend.assert_called_once_with(player.pid)
            self.assertEqual(self.engine.mode, "Paused")
            self.assertIsNotNone(self.engine.pause_started_at)
            elapsed_paused = self.engine.elapsed_seconds()
            self.assertIsNotNone(elapsed_paused)
            time.sleep(0.05)
            # While paused the audio clock stays bounded (pause_started_at).
            self.assertAlmostEqual(self.engine.elapsed_seconds(), elapsed_paused, delta=0.01)
            self.engine.resume()
            resume.assert_called_once_with(player.pid)
            self.assertEqual(self.engine.mode, "Playing")
            self.assertIsNone(self.engine.pause_started_at)
        # The clock grows again and still includes the pre-pause playback time,
        # but the paused duration was shifted out of player_started_at.
        elapsed_after = self.engine.elapsed_seconds()
        self.assertGreaterEqual(elapsed_after, elapsed_paused)
        self.assertLess(elapsed_after, elapsed_paused + 0.25)

    def test_pause_without_player_sets_mode_only(self):
        self.start_session("hola mundo")
        self.engine.pause()
        self.assertEqual(self.engine.mode, "Paused")


class TestReplayCache(SpeechEngineFixture, unittest.TestCase):
    def test_save_builds_concatenated_mp3_and_cumulative_marks(self):
        self.start_session("hola mundo\n\nchau", words="hola\nmundo\nchau")
        for chunk in self.engine.chunks:
            self.ready_chunk(chunk)
        self.engine.poll()
        self.engine.replay.eligible = True
        self.engine.stop_voice_playback()
        cache = self.engine.replay
        self.assertTrue(os.path.isfile(cache.file))
        with open(cache.file, "rb") as handle:
            # Both chunk MP3 bytes concatenated in order.
            self.assertEqual(handle.read(), b"ID3fake" * 2)
        # ffprobe unavailable -> word-count estimate per chunk (both 1.0s).
        self.assertAlmostEqual(cache.duration, 2.0)
        self.assertEqual(cache.mark_words, [0, 1, 2])
        self.assertEqual(cache.mark_seconds, [0.0, 0.5, 1.0])
        self.assertEqual(cache.voice_display, "Elvira (es-ES)")
        self.assertFalse(self.engine.replay.eligible)

    def test_empty_audio_emits_warning(self):
        media = os.path.join(tempfile.gettempdir(), "txt-test-empty.mp3")
        with open(media, "wb") as handle:
            handle.write(b"")
        self.engine.chunks = [Chunk(
            index=0, text="hola", text_file="t.txt", media_file=media,
            timing_file="t.json", start_word_index=0, status="Ready",
            duration_seconds=0.0,
            word_marks=[EdgeWordMark(0.0, 0, "hola")],
        )]
        self.engine.session_id = 1
        self.engine.voice_display = "Elvira (es-ES)"
        self.engine.replay.eligible = True
        self.engine.stop_voice_playback()
        self.assertIn("El audio generado está vacío.", self.last_message())
        self.assertFalse(self.engine.replay.file)
        # The concatenated temp file is not left behind (legacy catch cleanup).
        self.assertFalse(os.path.isfile(
            os.path.join(tempfile.gettempdir(),
                         f"txt-preview-replay-{os.getpid()}-{self.engine.session_id}.mp3")))

    def test_marks_beyond_audio_duration_are_dropped(self):
        # Legacy: word times beyond the audio mean a clock mismatch; keep the
        # audio, drop the marks.
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0], timings=[
            {"text": "hola", "start_seconds": 0.0},
            {"text": "mundo", "start_seconds": 5.0},
        ])
        self.engine.poll()
        self.engine.replay.eligible = True
        self.engine.stop_voice_playback()
        self.assertTrue(self.engine.replay.file)
        self.assertGreater(self.engine.replay.duration, 0)
        self.assertEqual(self.engine.replay.mark_seconds, [])
        self.assertEqual(self.engine.replay.mark_words, [])


class TestStopVoicePlayback(SpeechEngineFixture, unittest.TestCase):
    def test_stop_cleans_everything(self):
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        media_file = self.engine.chunks[0].media_file
        self.assertTrue(os.path.isfile(media_file))
        self.engine.replay.eligible = True
        self.engine.stop_voice_playback()
        self.assertFalse(os.path.isfile(media_file))
        self.assertEqual(self.engine.mode, "Idle")
        self.assertEqual(self.engine.provider, None)
        self.assertEqual(self.engine.chunks, [])
        self.assertEqual(self.engine.player_process, None)
        self.assertEqual(self.engine.align_words, [])
        self.assertEqual(self.engine.align_cursor, -1)
        self.assertEqual(self.engine.align_floor, -1)
        self.assertFalse(self.engine.replay.eligible)


class TestReplayStart(SpeechEngineFixture, unittest.TestCase):
    def test_builds_ffplay_args_with_tempo(self):
        handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        handle.close()
        self.engine.applied_speed = 150
        self.engine.replay = ReplayCache(
            file=handle.name, duration=10.0, voice_display="Elvira (es-ES)")
        self.engine.start_replay_playback(0.0)
        self.assertEqual(self.runner.processes[-1].args, [
            "fakeffplay", "-nodisp", "-autoexit", "-loglevel", "error",
            "-af", "atempo=1.5", handle.name,
        ])
        self.assertEqual(self.engine.mode, "Playing")
        self.assertEqual(self.engine.provider, "Replay")
        self.assertEqual(self.engine.replay_tempo, 1.5)
        os.remove(handle.name)

    def test_offset_is_clamped_and_seeks(self):
        handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        handle.close()
        self.engine.replay = ReplayCache(file=handle.name, duration=10.0)
        self.engine.start_replay_playback(99.0)
        args = self.runner.processes[-1].args
        self.assertIn("-ss", args)
        self.assertEqual(args[args.index("-ss") + 1], "9.800")
        os.remove(handle.name)

    def test_missing_replay_file_warns(self):
        self.engine.replay = ReplayCache()
        self.engine.start_replay_playback()
        self.assertEqual(self.engine.mode, "Idle")
        self.assertIn("No hay audio generado para repetir", self.last_message())


if __name__ == "__main__":
    unittest.main()
