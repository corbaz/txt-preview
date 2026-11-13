"""Speech concurrency tests (T21/S14 rule 1): pywebview dispatches JS API
calls on different threads, so speech_tick (the ~120 ms poll) races with
start_speech / stop / speed / click restarts. Inside the stop's kill→clear
window a stale poll can see old Ready chunks with player_process=None and
spawn an old ffplay; the stop then loses the handle and the new session
becomes voice #2. The Api serializes every speech lifecycle entrypoint with
one re-entrant lock; these tests prove it with a gated real engine and fake
processes (no real ffplay or edge-tts runs), so no timing flake is possible.
"""
import io
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core.speech import engine as engine_module
from txt_core.speech.engine import SpeechEngine


class FakeProcess:
    """Popen-like fake (same shape as the lifecycle fakes)."""

    def __init__(self, args, log=None):
        self.args = list(args)
        self.returncode = None
        self.pid = 5150
        self.kill_calls = 0
        self.stderr = io.BytesIO(b"")
        self.log = log if log is not None else []

    def poll(self):
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self.log.append("kill")

    def wait(self, timeout=None):
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


class GatedEngine(SpeechEngine):
    """Real engine whose Api-facing lifecycle methods record enter/exit and
    can block on a gate, so two overlapping Api operations are observable
    deterministically (Event-gated, never sleep-timed)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.gates = {}
        self.sequence = []    # "enter:stop", "exit:poll", ... in real order
        self.active = []
        self.violations = []  # (operations already inside, entering operation)

    def _enter(self, name):
        if name in self.active:
            return  # nested engine-internal call, not a second Api operation
        if self.active:
            self.violations.append((tuple(self.active), name))
        self.active.append(name)
        self.sequence.append("enter:" + name)
        gate = self.gates.get(name)
        if gate is not None:
            gate()

    def _exit(self, name):
        if name in self.active:
            self.active.remove(name)
        self.sequence.append("exit:" + name)

    def stop_voice_playback(self):
        self._enter("stop")
        try:
            super().stop_voice_playback()
        finally:
            self._exit("stop")

    def poll(self):
        self._enter("poll")
        try:
            super().poll()
        finally:
            self._exit("poll")

    def start_edge_session(self, *args, **kwargs):
        self._enter("start")
        try:
            super().start_edge_session(*args, **kwargs)
        finally:
            self._exit("start")

    def pause(self):
        self._enter("pause")
        try:
            super().pause()
        finally:
            self._exit("pause")

    def resume(self):
        self._enter("resume")
        try:
            super().resume()
        finally:
            self._exit("resume")

    def start_replay_playback(self, offset_seconds=0.0):
        self._enter("replay")
        try:
            super().start_replay_playback(offset_seconds)
        finally:
            self._exit("replay")


def one_shot_gate(timeout=5.0):
    """Gate that blocks only the first caller; later callers pass through."""
    event = threading.Event()
    state = {"used": False}

    def gate():
        if state["used"]:
            return
        state["used"] = True
        event.wait(timeout)

    return gate, event


def wait_until(predicate, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class ApiConcurrencyFixture(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.runner = FakeRunner(self.log)
        self.messages = []
        self.engine = GatedEngine(
            python_command="fakepython",
            ffplay_command="fakeffplay",
            ffprobe_command=None,
            emit=lambda level, message: self.messages.append((level, message)),
            runner=self.runner,
        )
        self.api = main.Api()
        self.api.engine = self.engine
        self.addCleanup(self._cleanup_temp_files)

    def _cleanup_temp_files(self):
        for chunk in list(getattr(self.engine, "chunks", [])):
            for path in (chunk.media_file, chunk.timing_file, chunk.text_file):
                if path and os.path.exists(path):
                    os.remove(path)
        replay = getattr(self.engine, "replay", None)
        if replay is not None and replay.file and os.path.exists(replay.file):
            os.remove(replay.file)

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

    def playing_session(self, text="hola mundo", words="hola\nmundo"):
        """A live reading: generation done, ffplay playing the first chunk."""
        self.engine.start_edge_session(text, "Elvira (es-ES)",
                                       "es-ES-ElviraNeural")
        self.engine.initialize_alignment(words)
        for chunk in self.engine.chunks:
            self.ready_chunk(chunk)
        self.engine.poll()
        return self.engine.player_process


class TestTickCannotInterleave(ApiConcurrencyFixture):
    """The confirmed S14 race: an Api operation that runs inside another one's
    stop→start window respawns old Ready audio; the Api lock must make every
    overlap impossible."""

    def test_speech_tick_cannot_poll_inside_a_blocked_start(self):
        gate = threading.Event()
        self.engine.gates["stop"] = lambda: gate.wait(5)
        result = {}
        t_start = threading.Thread(
            target=lambda: result.update(start=self.api.start_speech("hola mundo")))
        t_start.start()
        self.assertTrue(wait_until(lambda: "enter:stop" in self.engine.sequence),
                        "the start never reached its stop")
        t_tick = threading.Thread(
            target=lambda: result.update(tick=self.api.speech_tick()))
        t_tick.start()
        # Give an unlocked tick a full second to (wrongly) poll inside the stop.
        wait_until(lambda: self.engine.violations, timeout=1.0)
        self.assertEqual(self.engine.violations, [])
        gate.set()
        t_start.join(5)
        t_tick.join(5)
        self.assertFalse(t_start.is_alive())
        self.assertFalse(t_tick.is_alive())
        self.assertEqual(self.engine.violations, [])
        self.assertTrue(result["start"]["ok"])
        self.assertIn(result["tick"]["mode"], ("Idle", "Generating"))

    def test_poll_cannot_spawn_a_stale_ready_chunk_inside_the_stop_window(self):
        player = self.playing_session("hola mundo")
        # Mid-stop window (L24): the player was killed already but the old
        # Ready chunk is still tracked with no player — the unlocked poll used
        # to respawn its ffplay, which the stop then lost (the orphan voice).
        player.finish(0)
        self.engine.chunks[0].status = "Ready"
        self.engine.player_process = None
        spawns_before = len(self.runner.processes)

        gate = threading.Event()
        self.engine.gates["stop"] = lambda: gate.wait(5)
        t_start = threading.Thread(target=lambda: self.api.start_speech("hola mundo"))
        t_start.start()
        self.assertTrue(wait_until(lambda: "enter:stop" in self.engine.sequence))
        t_tick = threading.Thread(target=lambda: self.api.speech_tick())
        t_tick.start()
        wait_until(lambda: len(self.runner.processes) > spawns_before, timeout=1.0)
        self.assertEqual(len(self.runner.processes), spawns_before)
        gate.set()
        t_start.join(5)
        t_tick.join(5)
        self.assertFalse(t_start.is_alive())
        self.assertFalse(t_tick.is_alive())
        self.assertEqual(self.engine.violations, [])

    def test_click_restart_cannot_interleave_and_leaves_one_player(self):
        player = self.playing_session("hola mundo")
        self.api.speech_click(0, "mundo")
        gate = threading.Event()
        self.engine.gates["stop"] = lambda: gate.wait(5)
        t_move = threading.Thread(target=lambda: self.api.speech_tick())
        t_move.start()
        self.assertTrue(wait_until(lambda: "enter:stop" in self.engine.sequence),
                        "the click restart never reached its stop")
        t_other = threading.Thread(target=lambda: self.api.speech_tick())
        t_other.start()
        wait_until(lambda: self.engine.violations, timeout=1.0)
        self.assertEqual(self.engine.violations, [])
        gate.set()
        t_move.join(5)
        t_other.join(5)
        self.assertFalse(t_move.is_alive())
        self.assertFalse(t_other.is_alive())
        self.assertEqual(self.engine.violations, [])
        # Max active transition is 1: the old player died exactly once, before
        # anything new was spawned (generation → player → kill → generation).
        self.assertEqual(player.kill_calls, 1)
        self.assertEqual(self.log, ["spawn", "spawn", "kill", "spawn"])

    def test_speed_change_cannot_interleave_with_the_tick(self):
        player = self.playing_session("hola mundo")
        gate = threading.Event()
        self.engine.gates["stop"] = lambda: gate.wait(5)
        t_speed = threading.Thread(
            target=lambda: self.api.set_speech_speed(150))
        t_speed.start()
        self.assertTrue(wait_until(lambda: "enter:stop" in self.engine.sequence),
                        "the speed restart never reached its stop")
        t_tick = threading.Thread(target=lambda: self.api.speech_tick())
        t_tick.start()
        wait_until(lambda: self.engine.violations, timeout=1.0)
        self.assertEqual(self.engine.violations, [])
        gate.set()
        t_speed.join(5)
        t_tick.join(5)
        self.assertFalse(t_speed.is_alive())
        self.assertFalse(t_tick.is_alive())
        self.assertEqual(self.engine.violations, [])
        self.assertEqual(self.engine.applied_speed, 150)
        self.assertEqual(player.kill_calls, 1)

    def test_play_over_play_never_leaves_an_orphan_voice(self):
        """End-to-end S14 proof: Play while a reading runs, with a poll forced
        (Event-gated) inside the stop window, must never orphan the player the
        stale poll spawned for an old Ready chunk."""
        text = "palabra " * 30
        player = self.playing_session(
            text, words="\n".join(["palabra"] * 30))
        self.assertEqual(len(self.engine.chunks), 2)
        player.finish(0)  # the old player exits; the poll has not seen it yet

        calls = {"count": 0}
        stop_event = threading.Event()
        original_terminate = engine_module._terminate_process

        def gated_terminate(process):
            original_terminate(process)
            calls["count"] += 1
            if calls["count"] == 1:  # the player kill: stop is mid-window now
                stop_event.wait(5)

        poll_gate, poll_event = one_shot_gate()
        self.engine.gates["poll"] = poll_gate

        with mock.patch.object(engine_module, "_terminate_process",
                               gated_terminate):
            t_start = threading.Thread(
                target=lambda: self.api.start_speech("hola mundo"))
            t_start.start()
            self.assertTrue(
                wait_until(lambda: "enter:stop" in self.engine.sequence))
            t_tick = threading.Thread(target=lambda: self.api.speech_tick())
            t_tick.start()
            self.assertTrue(
                wait_until(lambda: "enter:poll" in self.engine.sequence))
            # Release the (unlocked) tick so it polls inside the stop window.
            poll_event.set()
            wait_until(lambda: len(self.runner.processes) > 3, timeout=1.0)
            stop_event.set()
            t_start.join(5)
            t_tick.join(5)
            self.assertFalse(t_start.is_alive())
            self.assertFalse(t_tick.is_alive())

        self.assertEqual(self.engine.violations, [])
        # Max active transition is 1: no live ffplay may survive untracked.
        orphans = [p for p in self.runner.processes
                   if p.args and p.args[0] == "fakeffplay"
                   and p.returncode is None and p.kill_calls == 0]
        self.assertEqual(orphans, [])
        self.assertEqual(self.engine.provider, "Edge")
        self.assertEqual(len(self.engine.chunks), 1)


class TestCloseAppSerialization(ApiConcurrencyFixture):
    """Cerrar (and the OS closing hook through stop_speech) must not destroy
    the window while another thread's stop is still running."""

    def test_close_app_never_destroys_inside_another_thread_stop(self):
        gate, event = one_shot_gate()
        self.engine.gates["stop"] = gate
        t_stop = threading.Thread(target=lambda: self.api.stop_speech())
        t_stop.start()
        self.assertTrue(wait_until(lambda: "enter:stop" in self.engine.sequence))
        window = mock.Mock()
        window.destroy.side_effect = lambda: self.engine.sequence.append("destroy")
        self.api._window = window
        t_close = threading.Thread(target=lambda: self.api.close_app())
        t_close.start()
        wait_until(lambda: "destroy" in self.engine.sequence, timeout=1.0)
        self.assertNotIn("destroy", self.engine.sequence)
        event.set()
        t_stop.join(5)
        t_close.join(5)
        self.assertFalse(t_stop.is_alive())
        self.assertFalse(t_close.is_alive())
        self.assertEqual(self.engine.sequence,
                         ["enter:stop", "exit:stop",
                          "enter:stop", "exit:stop", "destroy"])


class TestPendingClickLatestWins(ApiConcurrencyFixture):
    """A new click overwrites an older pending click: only the newest jump
    runs, exactly once, when the next tick consumes the queue atomically."""

    def test_the_latest_pending_click_wins(self):
        self.playing_session("hola mundo")
        self.api.speech_click(0, "hola")
        self.api.speech_click(1, "mundo")

        state = self.api.speech_tick()

        self.assertEqual(state["mode"], "Generating")
        self.assertEqual(self.engine.chunks[0].text, "mundo")
        self.assertEqual(self.engine.session_start_cursor, 0)
        self.assertEqual(self.log, ["spawn", "spawn", "kill", "spawn"])


if __name__ == "__main__":
    unittest.main()
