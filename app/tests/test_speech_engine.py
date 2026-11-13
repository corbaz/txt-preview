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
from txt_core.speech.engine import (
    Chunk,
    EdgeWordMark,
    ReplayCache,
    SpeechEngine,
    get_remaining_speech_text,
)


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


class TestGetRemainingSpeechText(unittest.TestCase):
    # Legacy Get-RemainingSpeechText: the current chunk from the first
    # whitespace boundary at/after the character position plus every later
    # chunk, joined by blank lines.
    def test_middle_of_word_advances_to_next_whitespace(self):
        texts = ["hola mundo", "chau"]
        self.assertEqual(get_remaining_speech_text(texts, 0, 2), "mundo\n\nchau")

    def test_word_being_spoken_is_skipped(self):
        # The scan starts on the word the audio clock is on: it is already
        # being spoken, so the remaining text starts after it (legacy parity).
        self.assertEqual(get_remaining_speech_text(["hola mundo"], 0, 5), "")

    def test_first_whitespaces_are_trimmed(self):
        self.assertEqual(get_remaining_speech_text(["hola  mundo"], 0, 4), "mundo")

    def test_chunks_join_with_blank_lines(self):
        # The in-flight word is skipped; later chunks join with blank lines.
        self.assertEqual(get_remaining_speech_text(["a", "b", "c"], 0, 0), "b\n\nc")

    def test_current_chunk_exhausted_returns_later_chunks(self):
        self.assertEqual(get_remaining_speech_text(["hola", "chau"], 0, 99), "chau")

    def test_last_chunk_exhausted_returns_empty(self):
        self.assertEqual(get_remaining_speech_text(["hola"], 0, 99), "")

    def test_index_past_the_chunks_returns_empty(self):
        self.assertEqual(get_remaining_speech_text(["hola"], 1, 0), "")
        self.assertEqual(get_remaining_speech_text([], 0, 0), "")


class TestSetSpeed(SpeechEngineFixture, unittest.TestCase):
    def test_idle_only_updates_the_rate(self):
        self.engine.start_edge_session("hola mundo", "Elvira (es-ES)",
                                       "es-ES-ElviraNeural")
        self.engine.set_speed(150)
        self.assertEqual(self.engine.applied_speed, 150)
        self.assertEqual(self.engine.mode, "Generating")
        self.assertEqual(len(self.runner.processes), len(self.engine.chunks))

    def test_playing_restarts_from_current_position_at_new_rate(self):
        self.start_session("hola mundo", words="hola\nmundo")
        self.ready_chunk(self.engine.chunks[0], timings=[
            {"text": "hola", "start_seconds": 0.0},
            {"text": "mundo", "start_seconds": 0.5},
        ])
        self.engine.poll()
        # The audio clock is ~0.3s in: "hola" is being spoken, "mundo" remains.
        self.engine.player_started_at -= 0.3
        generation_before = len(self.runner.processes)
        self.engine.set_speed(150)

        self.assertEqual(self.engine.applied_speed, 150)
        # New Edge session with the remaining text only.
        self.assertEqual(len(self.engine.chunks), 1)
        self.assertEqual(self.engine.chunks[0].text, "mundo")
        with open(self.engine.chunks[0].text_file, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "mundo")
        self.assertEqual(self.runner.processes[generation_before].args,
                         ["fakepython", str(engine_module.EDGE_TTS_WORDS_SCRIPT),
                          "--voice", "es-ES-ElviraNeural",
                          "--rate", "50",
                          "--text-file", self.engine.chunks[0].text_file,
                          "--media-file", self.engine.chunks[0].media_file,
                          "--timings-file", self.engine.chunks[0].timing_file])
        # The highlight floor sits on the word cursor at the restart.
        self.assertEqual(self.engine.align_floor, self.engine.align_cursor)
        self.assertEqual(self.engine.align_cursor, 0)
        # The old reading's media files are gone.
        self.assertEqual([c.status for c in self.engine.chunks], ["Generating"])
        self.assertIn("Velocidad cambiada a 1,50x. Continuando desde la posición actual.",
                      self.last_message())

    def test_paused_restarts_and_stays_paused(self):
        self.start_session("hola mundo", words="hola\nmundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        self.engine.player_started_at -= 0.3
        with mock.patch.object(engine_module.SuspendResume, "suspend"), \
                mock.patch.object(engine_module.SuspendResume, "resume"):
            self.engine.pause()
            self.engine.set_speed(50)
        self.assertEqual(self.engine.mode, "Paused")
        self.assertEqual(self.engine.chunks[0].text, "mundo")
        self.assertIn("Velocidad cambiada a 0,50x. La lectura permanece pausada.",
                      self.last_message())

    def test_finished_reading_reports_legacy_message(self):
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        self.engine.player_process.finish(0)
        self.engine.poll()  # the chunk played; the session is over
        self.engine.set_speed(150)
        self.assertEqual(self.engine.mode, "Idle")
        self.assertIn("La lectura ya había finalizado.", self.last_message())

    def test_restart_never_replaces_the_replay_cache(self):
        self.start_session("hola mundo")
        self.ready_chunk(self.engine.chunks[0])
        self.engine.poll()
        self.engine.replay.eligible = True
        self.engine.set_speed(150)
        self.assertFalse(self.engine.replay.eligible)


    def test_marks_realign_through_get_replay_word_timings(self):
        # Legacy Get-ReplayWordTimings: a spoken token that does not advance
        # the aligner produces no replay mark (char mapping gave it one).
        self.start_session("hola zzz mundo", words="hola\nmundo")
        self.ready_chunk(self.engine.chunks[0], timings=[
            {"text": "hola", "start_seconds": 0.0},
            {"text": "zzz", "start_seconds": 0.2},
            {"text": "mundo", "start_seconds": 0.5},
        ])
        self.engine.poll()
        self.engine.replay.eligible = True
        self.engine.stop_voice_playback()
        self.assertEqual(self.engine.replay.mark_words, [0, 1])
        self.assertEqual(self.engine.replay.mark_seconds, [0.0, 0.5])

    def test_jump_session_marks_start_after_the_jump_cursor(self):
        # Legacy CacheStartCursor = wordIndex - 1: after a Move-SpeechToWord
        # jump, Repetir marks the preview words the jumped reading really
        # highlighted (offset by the words before the jump).
        self.engine.start_edge_session("mundo chau", "Elvira (es-ES)",
                                       "es-ES-ElviraNeural", start_cursor=0)
        self.engine.initialize_alignment("hola\nmundo\nchau")
        self.ready_chunk(self.engine.chunks[0], timings=[
            {"text": "mundo", "start_seconds": 0.0},
            {"text": "chau", "start_seconds": 0.4},
        ])
        self.engine.poll()
        self.engine.replay.eligible = True
        self.engine.stop_voice_playback()
        self.assertEqual(self.engine.replay.mark_words, [1, 2])
        self.assertEqual(self.engine.replay.mark_seconds, [0.0, 0.4])


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


class TestReplayCacheEligibility(SpeechEngineFixture, unittest.TestCase):
    """Legacy CacheEligible: only a Play-started reading may feed Repetir."""

    def test_play_start_is_cache_eligible(self):
        self.start_session()
        self.assertTrue(self.engine.replay.eligible)

    def test_explicit_partial_start_is_not_eligible(self):
        self.engine.start_edge_session(
            "hola mundo", "Elvira (es-ES)", "es-ES-ElviraNeural", cache_eligible=False,
        )
        self.assertFalse(self.engine.replay.eligible)

    def test_stop_turns_eligibility_off(self):
        self.start_session()
        self.engine.stop_voice_playback()
        self.assertFalse(self.engine.replay.eligible)
