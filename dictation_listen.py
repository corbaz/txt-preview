"""Dictation for TXT Preview: a streaming speech model on this machine, written as it is said.

Usage: dictation_listen.py LANGUAGE CONTROL_FILE [MICROPHONE]
       dictation_listen.py --list
       dictation_listen.py --check LANGUAGE
       dictation_listen.py --install

LANGUAGE is the language spoken (`es`, `en`): the model's own variant of it is used (`es-US`).
MICROPHONE is part of a microphone's name (`JBL Tune 520BT`); absent, the system's default.
`--list` prints "mic <name>" for each microphone, as the system names it, and exits.
`--check` prints "ok <language>" when dictation can start, or "fail <why>", and exits.
`--install` downloads the model into the `models` folder beside this script, printing
"progress <percent>" as it goes, then "ok <file>" or "fail <why>".

The model is NVIDIA's Nemotron 3.5 ASR Streaming (0.6B, 40 languages), run by transcribe-cpp on
the CPU. Nothing leaves the machine, and nothing is kept outside this folder.

Both apps (app/main.py and txt.ps1) run this script and read its lines. It prints "ready" once
the model is loaded (the microphone records from the start, so nothing said while it loads is
lost). The words come as the model commits them: "text <n> <words>", each to be appended as it
is, spaces included: a piece without a leading space goes on the word before it, and the first
piece of a phrase always has one. What it still guesses at comes as "partial <n> <text>". A pause
of PAUSE_SECONDS ends phrase n: the model is asked for its last words, and the next phrase is
n + 1. Writing "stop" to CONTROL_FILE ends it: the phrase under way is written out first, then
"done". A failure is one line, "error <why>".
"""

import os
import queue
import re
import sys
import threading
import time

RATE = 16000
BLOCK_SECONDS = 0.05
PAUSE_SECONDS = 0.8
MIN_SPEECH_SECONDS = 0.2
MODEL_FILE = "nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"
MODEL_URL = ("https://huggingface.co/handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf/"
             "resolve/main/" + MODEL_FILE)
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
# TXT_DICTATION_MODEL names another model file: the tests use it to stand for a missing one.
MODEL_PATH = os.environ.get("TXT_DICTATION_MODEL") or os.path.join(MODELS_DIR, MODEL_FILE)
# The variant of each language the model is asked for: Latin American Spanish over Spain's.
PREFERRED = {"es": "es-US", "en": "en-US", "pt": "pt-BR", "fr": "fr-FR"}
MISSING_MODEL = "falta el modelo de dictado: ejecutá el instalador (install.ps1 o install.sh)"
MISSING_PACKAGES = ("faltan los paquetes del dictado (transcribe-cpp, sounddevice, numpy): "
                    "ejecutá el instalador (install.ps1 o install.sh)")

GLUED = re.compile(r"([.!?])([A-ZÁÉÍÓÚÑ¿¡])")

_say_lock = threading.Lock()


def say(line: str) -> None:
    """One line to the app, at once; the threads that write never mix their lines."""
    with _say_lock:
        sys.stdout.write(line.replace("\n", " ") + "\n")
        sys.stdout.flush()


def is_stopped(control: str) -> bool:
    """Whether the app wrote "stop"; a read that meets the app writing is tried again later."""
    try:
        with open(control, encoding="utf-8") as source:
            return source.read().strip() == "stop"
    except OSError:
        return False


def sound():
    """sounddevice, or the message that names the fix."""
    try:
        import sounddevice
    except Exception as error:  # ImportError, or PortAudio missing
        raise RuntimeError(MISSING_PACKAGES) from error
    return sounddevice


def engine():
    """transcribe-cpp, with its native notes silenced.

    They go to stderr ("load_backend: …"), which nobody reads: the apps read stdout, and
    PowerShell 5.1 takes any stderr line as a failure. Errors still reach stdout as "error"."""
    os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
    try:
        import transcribe_cpp
    except Exception as error:
        raise RuntimeError(MISSING_PACKAGES) from error
    return transcribe_cpp


def microphones() -> "dict[str, int]":
    """The microphones by name: on Windows WASAPI's, which keeps names whole (MME cuts them at 31
    characters); on macOS Core Audio's, its only one."""
    sd = sound()
    found: "dict[str, int]" = {}
    for index, device in enumerate(sd.query_devices()):
        api = sd.query_hostapis(device["hostapi"])["name"]
        if device["max_input_channels"] > 0 and (sys.platform != "win32" or "WASAPI" in api):
            found.setdefault(device["name"], index)
    return found


def load_model():
    if not os.path.exists(MODEL_PATH):
        raise RuntimeError(MISSING_MODEL)
    return engine().Model(MODEL_PATH)


def model_language(model, wanted: str) -> str:
    """The model's variant of `wanted` (`es` → `es-US`), or an error naming the language."""
    offered = list(model.capabilities.languages)
    base = wanted.lower().split("-")[0]
    for tag in (wanted, PREFERRED.get(base, "")):
        if tag in offered:
            return tag
    for tag in offered:
        if tag.lower().split("-")[0] == base:
            return tag
    raise RuntimeError(f"el modelo de dictado no habla '{wanted}'")


def install_model() -> None:
    """Download the model beside this script; a download cut short goes on from where it stopped."""
    import urllib.request
    try:
        import truststore
        truststore.inject_into_ssl()  # the system's certificates, as the app does
    except Exception:  # without truststore the default store is tried
        pass
    if os.path.exists(MODEL_PATH):
        say(f"ok {MODEL_PATH}")
        return
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    part = MODEL_PATH + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "txt-preview"})
    if have:
        request.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        if have and response.status != 206:  # the server sent it whole: start again
            have = 0
        total = have + int(response.headers.get("Content-Length") or 0)
        shown = -1
        with open(part, "ab" if have else "wb") as target:
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                target.write(block)
                have += len(block)
                percent = int(have * 100 / total) if total else 0
                if percent != shown:
                    shown = percent
                    say(f"progress {percent}")
    if total and have < total:
        raise RuntimeError("la descarga del modelo quedó incompleta: volvé a ejecutar el instalador")
    os.replace(part, MODEL_PATH)
    say(f"ok {MODEL_PATH}")


def clear_stale(folder: str) -> None:
    """Stop files a dictation ended by force left behind: those an hour old go."""
    cutoff = time.time() - 3600
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        if name.startswith("txt-dictation-") and name.endswith(".txt"):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass


class Pauses:
    """Tells speech from silence by loudness, against a noise floor learned from the quietest blocks."""

    def __init__(self) -> None:
        # A headset's microphone can be very quiet, so the least level that counts as speech is low.
        self.floor = 0.0005
        self.spoken = 0.0
        self.silent = 0.0
        self.loudest = 0.0

    def feed(self, block) -> bool:
        """Whether the phrase under way just ended: enough speech, then a pause."""
        import numpy as np
        seconds = len(block) / RATE
        level = float(np.sqrt(np.mean(block ** 2))) if len(block) else 0.0
        self.loudest = max(self.loudest, level)
        if level > max(self.floor * 3, 0.002):
            self.spoken += seconds
            self.silent = 0.0
            return False
        self.floor = self.floor * 0.95 + level * 0.05
        self.silent += seconds
        if self.spoken >= MIN_SPEECH_SECONDS and self.silent >= PAUSE_SECONDS:
            self.spoken = 0.0
            return True
        return False


class Phrase:
    """One phrase's stream: hands on each word the model commits, and shows what it still guesses."""

    def __init__(self, session, language: str, number: int) -> None:
        self.stream = session.stream(language=language)
        self.number = number
        self.written = ""
        self.guess = ""

    def feed(self, audio) -> None:
        self.stream.feed(audio)
        self.show()

    def finish(self) -> str:
        """The phrase's last words, then its whole text; the stream is let go."""
        self.stream.finalize()
        self.show(final=True)
        self.stream.reset()
        return self.written

    def show(self, final: bool = False) -> None:
        text = self.stream.text()
        committed = (text.committed + text.tentative) if final else text.committed
        if len(committed) > len(self.written) and committed.startswith(self.written):
            # Spaces as the model put them: a word can come in two pieces ("princi", "pal."). A
            # phrase's first piece starts with one, so it never sticks to the text before it.
            fresh = committed[len(self.written):]
            if not self.written:
                fresh = " " + fresh.lstrip()
            elif fresh[:1].isalpha() and self.written[-1:] in ".,;:!?":
                fresh = " " + fresh
            # Two sentences said without a pause come glued ("local.Funciona").
            fresh = GLUED.sub(r"\1 \2", fresh)
            self.written = committed
            if fresh.strip():
                say(f"text {self.number} {fresh.rstrip()}")
        guess = "" if final else text.tentative.strip()
        if guess != self.guess:
            self.guess = guess
            if guess:
                say(f"partial {self.number} {guess}")


def listen(wanted_language: str, control: str, wanted: str) -> None:
    import numpy as np
    blocks: "queue.Queue" = queue.Queue()

    # TXT_DICTATION_AUDIO, raw 16 kHz mono float32, stands for the microphone in a test: fed in real time.
    test_audio = os.environ.get("TXT_DICTATION_AUDIO")
    if test_audio:
        samples = np.fromfile(test_audio, dtype=np.float32)
        size = int(RATE * BLOCK_SECONDS)

        def feed() -> None:
            for start in range(0, len(samples), size):
                blocks.put(samples[start:start + size])
                time.sleep(BLOCK_SECONDS)

        stream = None
        threading.Thread(target=feed, daemon=True).start()
    else:
        sd = sound()
        device = next((index for name, index in microphones().items() if wanted and wanted in name), None)
        # WASAPI records at the device's own rate: auto_convert brings it to 16 kHz. Core Audio converts by itself.
        extra = sd.WasapiSettings(auto_convert=True) if device is not None and sys.platform == "win32" else None
        stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=int(RATE * BLOCK_SECONDS),
                                device=device, extra_settings=extra,
                                callback=lambda data, frames, when, status: blocks.put(data[:, 0].copy()))
        stream.start()

    clear_stale(os.path.dirname(control))
    model = load_model()
    language = model_language(model, wanted_language)
    session = model.session(n_threads=max(1, (os.cpu_count() or 4) // 2))
    say("ready")

    pauses = Pauses()
    phrase = Phrase(session, language, 1)

    def take():
        """Every block waiting, in one piece: a slow feed never leaves the model behind the voice."""
        waiting = [blocks.get(timeout=0.1)]
        while not blocks.empty():
            waiting.append(blocks.get())
        return np.concatenate(waiting)

    while not is_stopped(control):
        try:
            audio = take()
        except queue.Empty:
            continue
        phrase.feed(audio)
        if pauses.feed(audio):
            phrase.finish()
            phrase = Phrase(session, language, phrase.number + 1)

    # Stopped, maybe mid-phrase: what was recorded is still written.
    if stream:
        stream.stop()
    while not blocks.empty():
        phrase.feed(blocks.get())
    phrase.finish()
    session.close()
    model.close()
    try:
        os.remove(control)
    except OSError:
        pass
    say("done")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    arguments = sys.argv[1:]
    if arguments == ["--list"]:
        for name in microphones():
            say(f"mic {name}")
        return
    if arguments[:1] == ["--check"]:
        try:
            say(f"ok {model_language(load_model(), arguments[1] if len(arguments) > 1 else 'es')}")
        except Exception as error:  # pylint: disable=broad-except
            say(f"fail {error}")
        return
    if arguments == ["--install"]:
        try:
            install_model()
        except Exception as error:  # pylint: disable=broad-except
            say(f"fail {error}")
            sys.exit(1)
        return
    if len(arguments) < 2:
        say("error uso: dictation_listen.py LANGUAGE CONTROL_FILE [MICROPHONE]")
        sys.exit(2)
    listen(arguments[0], arguments[1], arguments[2] if len(arguments) > 2 else "")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # pylint: disable=broad-except
        say(f"error {error}")
        time.sleep(0.1)
        sys.exit(1)
