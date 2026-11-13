# TXT Preview multiplatform (Windows + macOS)

App conversion from Windows-only PowerShell/WinForms to a cross-platform Python + pywebview application with identical behavior on Windows and macOS, per-platform installers, a dependency doctor, and a git-pull update workflow.

## Specs

- S1: "la idea es converti a la app en multiplataforma" — the app must work identically on Windows and macOS.
- S2: "que yo trabaje todo aca en windows pero ue la app este preparada para que la clone la mac y funciones identica en la mac" — development happens on Windows; a Mac user clones the repo and runs the same app with identical behavior.
- S3: "cada uno tenga su instalador en el radme explicado para el usurio o una ia para que le instale todo con su doctor si le falta algo" — README documents per-platform installers; a doctor checks and installs missing dependencies (git, Python, edge-tts, ffmpeg, WebView2 runtime), usable by a human or by an AI agent.
- S4: "Luego si yo hago un cambio en windows debe quedar compatible para la Mac asi el otro usuario en su mac lo actualiza con un pull" — every change pushed from Windows must stay Mac-compatible; the Mac user updates with `git pull`.
- S5 (decision): stack is **Python + pywebview** (native WebView2 on Windows / WKWebView on macOS; HTML/CSS/JS shared).
- S6 (decision): TTS is **Edge voices only** (`edge-tts` on both platforms); `System.Speech`/SAPI is dropped.
- S7: the existing PowerShell/WinForms app (`txt.ps1`) stays in the repo until parity is declared; the new app lives under `app/`.

## Tasks

| ID | Spec | Route | Commit |
| --- | --- | --- | --- |
| T1 | S5, S7 | Scaffold `app/`: pywebview entry, JS bridge, requirements, minimal shell; runs on Windows | 131c4dd |
| T2 | S1 | Port portable logic to Python: markdown render, citation stripping, AI prompts, Groq/bridge HTTP, model catalog | 3d073aa |
| T3 | S1, S2 | UI shell: Editor/Vista previa/Configuración/Navegador tabs, themes light/dark | 45dd5fd |
| T4 | S6, S2 | Edge-only TTS: chunker, playback (ffplay), pause/resume, replay, speed, per-word highlight in preview | 9e1ef2f |
| T5 | S1 | Attachments: text/images/docx/pptx/pdf extraction (python-docx, python-pptx, PyMuPDF) | 4ba7d90 |
| T6 | S1 | Export: PDF and MP3 | fdf2f96 |
| T7 | S3 | Doctor + installers: `install.ps1` (Windows) and `install.sh` (macOS), detect/install/explain missing deps, AI-readable output | ec9a7fe |
| T8 | S4 | CI: GitHub Actions matrix (windows + macos) running doctor dry-run and test suite on every push | 0a3f191 |
| T9 | S3 | README rewrite: clone → doctor → run flow per OS, explained for a human or an AI agent | README in this commit |
| T10 | S2 | Settings/secrets: platform-aware paths, migrate DPAPI-encrypted settings from the PS app (Windows), Keychain-safe storage on macOS | cecbff6 |
| T11 | S4 | In-app update: VERSION check + `git pull --ff-only` on both OS | 7e6a5de |
| T12 | S4 | Cross-platform test suite: port Windows-gated tests, cover shared logic | pending |
| T13 | S1, S7 | Cutover: default install path points to the new app; PS app kept as legacy | pending |

## Log

- L1: "la idea es converti a la app en multiplataforma que yo trabaje todo aca en windows pero ue la app este preparada para que la clone la mac y funciones identica en la mac y cada uno tenga su instalador en el radme explicado para el usurio o una ia para que le instale todo con su doctor si le falta algo se entiende analizalo profundamente . Luego si yo hago un cambio en windows debe quedar compatible para la Mac asi el otro usuario en su mac lo actualiza con un pull se entiende tdo"
- L2: "lo de tauri me confundi talvez pyton sea mejor cual es tu mejor opcion" → user confirmed Python + pywebview (S5) and Edge-only TTS (S6). Branch renamed to `feat/cross-platform`.
- L3: T2 delivered citations/prompts/groq/bridges/models; the Markdown renderer (listed in T2) is implemented inside T3 where the preview consumes it.
- L4: T4 parity gaps to close before cutover: speed change during an Edge reading does not restart/re-synthesize remaining text (legacy Restart-ActiveSpeechPlayback applies immediately); replay mark words map directly by character position instead of re-running Get-ReplayWordTimings; voice catalog (edge-tts list-voices) is still hardcoded to es-ES-ElviraNeural. Commit 9e1ef2f; prior parts d3f9f53 (chunker+marks) and 6909078 (alignment+replay+atempo).
- L5: T5 decisions: legacy .doc/.ppt (Office COM) support dropped on BOTH platforms for cross-platform parity — users get a conversion message; PDF now via PyMuPDF; bridge vision flag defaults False until /models probing lands; API key/bridge passwords read from env only until T10 persisted settings.
- L7: T11: updater refuses dirty worktrees and non-main branches (legacy parity); UpdateStatus carries an extra `updated` flag so the UI distinguishes applied updates.
- L8: T4 parity gaps from L4 CLOSED in ffad99c: voice catalog (edge-voices.json cache + selector), speed restart during Edge reading (Restart-ActiveSpeechPlayback port), replay marks re-run the live aligner (CacheStartCursor parity). Replay-cache eligibility pinned: only Play-started readings feed Repetir (legacy CacheEligible).
- L6: T10 notes: legacy EncryptedBridgePasswords are NOT imported (env/password.txt resolution stays); the real legacy settings.json on the dev machine was migrated in place (api_key_enc added, legacy fields intact, legacy app still compatible); keyring>=25 added to requirements by the orchestrator after the worker stopped for the out-of-surface approval.
