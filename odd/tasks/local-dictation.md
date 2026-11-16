# local-dictation

Objective: the Micrófono button dictates with a speech model on this machine, in both apps, instead of the system dictation.
Branch: main (project rule). Delivery: exception-ok (work-unit commits on main). Test runner: `python -m unittest discover -s tests` from `app/` and from the repo root.

## Specs

- S1 Own engine in both apps. The Micrófono button no longer uses the system dictation (Win+H on Windows, `startDictation:` on macOS, which never starts: "Dictado de macOS activado" is shown and nothing is dictated). It records the microphone and transcribes on this machine, the way the user's speedy-code plugin does (`hooks/listen.py`: sounddevice + transcribe-cpp + Nemotron 3.5 ASR Streaming).
- S2 Independent of speedy-code. User: "hazlo como si no existiera el otro proyecto por que este pue ser instalado speed-code otro uusario no lo tiene". TXT ships its own script and downloads its own model; it never reads the plugin's folders.
- S3 User: "todo debe quedar en las misma folder del repo". The model lives in `<repo>/models/` (not in git). Python packages go where edge-tts goes (user answered "si edge-tss" to: packages in the user's Python like edge-tts, only the model in the repo).
- S4 User: "configuracion agrga el elegir el mic del cual se va a tomar". Configuración has a microphone selector (detected microphones plus the system default); the choice is saved with the other settings.
- S5 Installers (`install.ps1`, `install.sh`) install `transcribe-cpp`, `sounddevice`, `numpy` and download the model (about 750 MB).
- S6 Use: Micrófono starts dictating and the text enters the editor while speaking; Esc or the same button stops it and the button goes back to «Micrófono» (assumption: the label while dictating stays «Mic <Esc>» as in txt.ps1).
- S7 A missing model or package gives a clear message that names the fix; the editor stays ready to type (earlier user rule: "Si no funciona o no detecta el dictado, debe ir al editor y escribir").

## Tasks

- [x] T1 (S1-S3, S7) inline — `dictation_listen.py` at the repo root: list, check, install, listen.
- [x] T2 (S1, S4, S6, S7) inline — Python app: bridge, editor insertion, Esc, Configuración selector.
- [x] T3 (S1, S4, S6, S7) inline — txt.ps1: same behaviour.
- [x] T4 (S5) inline — installers, doctor, README, .gitignore. Risk item 5.

## Log

- L1 (2026-11-16) User: "~\.claude\local-mods no toques nada pero lee el plugin la parte del microfon la deteccion de cuales tiene y la transcripcion de lo que hablas de voz a texto" then "en las 2 app hazlo y configuracion agrga el elegir el mic del cual se va a tomar , con respectoa baja hazlo como si no existiera el otro proyecto por que este pue ser instalado speed-code otro uusario no lo tiene si se entiende y todo debe quedar en las misma folder del repo".
- L2 (2026-11-16) Asked where the Python packages go; user: "si edge-tss" (same place as edge-tts, model only in the repo).
- L3 Evidence: macOS trace `dictation taken=True responder=NSKVONotifying_WebKitHost responds=False`: the system dictation cannot be started from the app.
- L4 Route: all inline (dependent units, one behaviour).
- L5 (2026-11-16) Done. Evidence: app suite OK (751 tests, 1 skipped); root suite OK (140 tests) including a real listener run in txt.ps1 with a synthesized recording; model download and resume exercised against Hugging Face (751,094,240 bytes); installer dictation steps run in isolation on Windows (pip=0, install=0, unreachable path=1). Not verified: anything on macOS (packages, microphone permission, install.sh), a live microphone, the UI on screen.
- L6 Decisions: stop by control file (same in both apps); `microphone` is a plain field of the shared settings.json; the doctor reports a missing dictation as AVISO and never fails (the TXT alias chains install.sh && run.sh, so a failed 750 MB download must not block the app); sentences glued by the model ("local.Funciona") get a space in the listener.
