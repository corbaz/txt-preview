"""Micrófono: dictation by the local model (txt_core.dictation)."""
import io
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import dictation

REPO = Path(__file__).resolve().parents[2]


class FakeListener:
    """Stands for the dictation_listen.py process: its lines are fed by the test."""

    def __init__(self, arguments, **_options):
        self.arguments = arguments
        self._read, self._write = os.pipe()
        self.stdout = os.fdopen(self._read, "rb")
        self._writer = os.fdopen(self._write, "wb")
        self.killed = False
        self._ended = threading.Event()

    def say(self, line: str) -> None:
        self._writer.write((line + "\n").encode("utf-8"))
        self._writer.flush()

    def end(self) -> None:
        self._writer.close()
        self._ended.set()

    def poll(self):
        return 0 if self._ended.is_set() else None

    def wait(self, timeout=None):
        if not self._ended.wait(timeout):
            raise subprocess.TimeoutExpired("listener", timeout)
        return 0

    def kill(self) -> None:
        self.killed = True
        if not self._ended.is_set():
            self.end()


def wait_for(condition, seconds=2.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class DictationFixture(unittest.TestCase):
    def setUp(self):
        self.listeners = []

        def runner(arguments, **options):
            listener = FakeListener(arguments, **options)
            self.listeners.append(listener)
            return listener

        self.dictation = dictation.Dictation("python", runner=runner)
        self.addCleanup(self.dictation.close)

    def state(self):
        return self.dictation.poll()


class TestStartAndWords(DictationFixture):
    def test_start_runs_the_listener_with_language_and_microphone(self):
        result = self.dictation.start("es", "JBL Tune")
        self.assertTrue(result["ok"])
        arguments = self.listeners[0].arguments
        self.assertEqual(arguments[0], "python")
        self.assertEqual(Path(arguments[1]), REPO / "dictation_listen.py")
        self.assertEqual(arguments[2], "es")
        self.assertEqual(arguments[4], "JBL Tune")
        first = self.state()
        self.assertEqual(first["state"], "loading")
        self.assertEqual(first["message"], dictation.MSG_LOADING)

    def test_default_microphone_passes_no_name(self):
        self.dictation.start("en")
        self.assertEqual(len(self.listeners[0].arguments), 4)

    def test_ready_means_listening_and_words_reach_the_page_once(self):
        self.dictation.start("es")
        self.state()
        listener = self.listeners[0]
        listener.say("ready")
        self.assertTrue(wait_for(lambda: self.dictation._state == "listening"))
        self.assertEqual(self.state()["message"], dictation.MSG_LISTENING)
        listener.say("partial 1 hola est")
        listener.say("text 1  Hola,")
        listener.say("text 1  esta es una prueba")
        listener.say("text 1 .")
        self.assertTrue(wait_for(lambda: self.dictation._text.endswith(".")))
        state = self.state()
        # Spaces as the model put them: the final "." sticks to the last word.
        self.assertEqual(state["text"], " Hola, esta es una prueba.")
        self.assertEqual(state["partial"], "")
        self.assertEqual(self.state()["text"], "")  # handed over once

    def test_partial_is_what_the_model_still_guesses(self):
        self.dictation.start("es")
        listener = self.listeners[0]
        listener.say("ready")
        listener.say("partial 1 buenos dí")
        self.assertTrue(wait_for(lambda: self.dictation._partial == "buenos dí"))
        self.assertEqual(self.state()["partial"], "buenos dí")

    def test_a_second_start_while_dictating_starts_nothing(self):
        self.dictation.start("es")
        self.dictation.start("es")
        self.assertEqual(len(self.listeners), 1)


class TestStopAndFailures(DictationFixture):
    def test_stop_writes_the_control_file_and_done_goes_idle(self):
        self.dictation.start("es")
        listener = self.listeners[0]
        control = listener.arguments[3]
        self.addCleanup(lambda: os.path.exists(control) and os.remove(control))
        listener.say("ready")
        self.assertEqual(self.dictation.stop()["state"], "stopping")
        with open(control, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "stop")
        listener.say("text 2  último tramo")  # the phrase under way is still written
        listener.say("done")
        listener.end()
        self.assertTrue(wait_for(lambda: not self.dictation.active))
        state = self.state()
        self.assertEqual(state["state"], "idle")
        self.assertEqual(state["text"], " último tramo")
        self.assertEqual(state["message"], dictation.MSG_STOPPED)

    def test_listener_error_names_the_fix_and_leaves_the_editor_to_type(self):
        self.dictation.start("es")
        listener = self.listeners[0]
        listener.say("error falta el modelo de dictado: ejecutá el instalador (install.ps1 o install.sh)")
        listener.end()
        self.assertTrue(wait_for(lambda: not self.dictation.active))
        state = self.state()
        self.assertEqual(state["level"], "error")
        self.assertIn("falta el modelo de dictado", state["message"])
        self.assertIn("El editor quedó listo para escribir", state["message"])

    def test_listener_that_dies_without_a_word_is_an_error(self):
        self.dictation.start("es")
        self.listeners[0].end()
        self.assertTrue(wait_for(lambda: not self.dictation.active))
        state = self.state()
        self.assertEqual(state["level"], "error")
        self.assertIn(dictation.MSG_ENDED, state["message"])

    def test_no_python_is_reported(self):
        result = dictation.Dictation(None).start("es")
        self.assertFalse(result["ok"])
        self.assertIn(dictation.MSG_NO_PYTHON, result["message"])

    def test_listener_that_cannot_start_is_reported(self):
        def broken(*_arguments, **_options):
            raise OSError("sin permiso")
        result = dictation.Dictation("python", runner=broken).start("es")
        self.assertFalse(result["ok"])
        self.assertIn("sin permiso", result["message"])

    def test_close_kills_a_listener_still_running(self):
        self.dictation.start("es")
        self.dictation.close()
        self.assertTrue(self.listeners[0].killed)
        self.assertFalse(self.dictation.active)

    def test_stop_when_idle_does_nothing(self):
        self.assertEqual(self.dictation.stop(), {"ok": True, "state": "idle"})


class TestMicrophones(unittest.TestCase):
    def test_lists_the_names_the_listener_prints(self):
        def run(arguments, **_options):
            self.assertEqual(arguments[2], "--list")
            return mock.Mock(stdout="mic Micrófono (G432 Gaming Headset)\nmic JBL Tune 520BT\n"
                             .encode("utf-8"))
        self.assertEqual(dictation.list_microphones("python", runner=run),
                         ["Micrófono (G432 Gaming Headset)", "JBL Tune 520BT"])

    def test_missing_packages_or_python_give_an_empty_list(self):
        def run(*_arguments, **_options):
            return mock.Mock(stdout=b"error faltan los paquetes del dictado\n")
        self.assertEqual(dictation.list_microphones("python", runner=run), [])
        self.assertEqual(dictation.list_microphones(None), [])

        def broken(*_arguments, **_options):
            raise OSError("sin python")
        self.assertEqual(dictation.list_microphones("python", runner=broken), [])


@unittest.skipUnless(os.path.exists(REPO / "models" / "nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"),
                     "needs the dictation model (installer)")
class TestListenerScript(unittest.TestCase):
    """The real script, without a microphone."""

    def run_script(self, *arguments, **environment):
        env = dict(os.environ, **environment)
        done = subprocess.run([sys.executable, str(REPO / "dictation_listen.py"), *arguments],
                              capture_output=True, timeout=120, env=env)
        return done.returncode, done.stdout.decode("utf-8").splitlines()

    def test_check_names_the_language_variant(self):
        code, lines = self.run_script("--check", "es")
        self.assertEqual((code, lines), (0, ["ok es-US"]))

    def test_missing_model_names_the_installer(self):
        code, lines = self.run_script("--check", "es", TXT_DICTATION_MODEL="no-such-model.gguf")
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["fail falta el modelo de dictado: ejecutá el instalador "
                                 "(install.ps1 o install.sh)"])

    def test_install_with_the_model_present_downloads_nothing(self):
        code, lines = self.run_script("--install")
        self.assertEqual(code, 0)
        self.assertTrue(lines[-1].startswith("ok "))
        self.assertFalse(any(line.startswith("progress") for line in lines))


if __name__ == "__main__":
    unittest.main()
