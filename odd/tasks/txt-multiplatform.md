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
- S8: "dejar botoneras tal cual original en bottom y todos los mismo botones de antes y misma ui y UX siempre arrancar maximizado" — the cross-platform app must preserve the original bottom control deck, every prior button/control, the same UI/UX and always start maximized.

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
| T12 | S4 | Cross-platform test suite: port Windows-gated tests, cover shared logic | 8972bc6 |
| T13 | S1, S7 | Cutover: default install path points to the new app; PS app kept as legacy | complete after T15 visual parity |
| T15 | S8 | Rebuild the pywebview layout to match the original UI/UX: top nav/context bar, editor canvas, complete bottom control deck, maximized startup | d3a0886 |

## Log

- L1: "la idea es converti a la app en multiplataforma que yo trabaje todo aca en windows pero ue la app este preparada para que la clone la mac y funciones identica en la mac y cada uno tenga su instalador en el radme explicado para el usurio o una ia para que le instale todo con su doctor si le falta algo se entiende analizalo profundamente . Luego si yo hago un cambio en windows debe quedar compatible para la Mac asi el otro usuario en su mac lo actualiza con un pull se entiende tdo"
- L2: "lo de tauri me confundi talvez pyton sea mejor cual es tu mejor opcion" → user confirmed Python + pywebview (S5) and Edge-only TTS (S6). Branch renamed to `feat/cross-platform`.
- L3: T2 delivered citations/prompts/groq/bridges/models; the Markdown renderer (listed in T2) is implemented inside T3 where the preview consumes it.
- L4: T4 parity gaps to close before cutover: speed change during an Edge reading does not restart/re-synthesize remaining text (legacy Restart-ActiveSpeechPlayback applies immediately); replay mark words map directly by character position instead of re-running Get-ReplayWordTimings; voice catalog (edge-tts list-voices) is still hardcoded to es-ES-ElviraNeural. Commit 9e1ef2f; prior parts d3f9f53 (chunker+marks) and 6909078 (alignment+replay+atempo).
- L5: T5 decisions: legacy .doc/.ppt (Office COM) support dropped on BOTH platforms for cross-platform parity — users get a conversion message; PDF now via PyMuPDF; bridge vision flag defaults False until /models probing lands; API key/bridge passwords read from env only until T10 persisted settings.
- L7: T11: updater refuses dirty worktrees and non-main branches (legacy parity); UpdateStatus carries an extra `updated` flag so the UI distinguishes applied updates.
- L8: T4 parity gaps from L4 CLOSED in ffad99c: voice catalog (edge-voices.json cache + selector), speed restart during Edge reading (Restart-ActiveSpeechPlayback port), replay marks re-run the live aligner (CacheStartCursor parity). Replay-cache eligibility pinned: only Play-started readings feed Repetir (legacy CacheEligible).
- L6: T10 notes: legacy EncryptedBridgePasswords are NOT imported (env/password.txt resolution stays); the real legacy settings.json on the dev machine was migrated in place (api_key_enc added, legacy fields intact, legacy app still compatible); keyring>=25 added to requirements by the orchestrator after the worker stopped for the out-of-surface approval.
- L9: T13 cutover: VERSION bumped to v:26.11.13-08.51; CHANGELOG notes published; legacy app (txt.ps1) kept in repo; default install path has targeted the Python app since T7. Final validation: 301/301 app tests green; legacy suite 122/123 (pre-existing pwsh-lock flake); GUI smoke + live doctor OK.
- L10: "dejar botoneras tal cual original en bottom y todos los mismo botones de antes y misma ui y UX siempre arrancar maximizado" — screenshots supplied: original top navigation/context bar, large editor canvas, and complete three-row bottom control deck. Reopened T13 and added S8/T15.
- L12: T15 implemented in d3a0886: production UI rebuilt to the original layout per `design/txt-original-parity/01-original-layout.html` — 52px top bar (Editor/Vista previa/Navegador left, live status center, Configuración tab + Modelo select right), 46px Contexto IA bar (capability tooltips, checked "Usar web en la próxima consulta", Adjuntar archivos, attachment summary, Quitar adjuntos affordance only when attachments exist), editor canvas with no top toolbars, and the complete centered 4-row bottom deck (row 1 AI actions with legacy "Traducir Inglés a Español/Español a Inglés" labels; row 2 Pegar/Copiar MD/Copiar TXT/Micrófono/PDF/MP3/Limpiar chat — preview exports moved out of the preview page; row 3 Hombre/Mujer · Español/Inglés radio-like toggles that filter the voice catalog client-side and persist via set_speech_voice, Voz selector, Play/Pausar/Detener, Tema: Oscuro, Cerrar; row 4 Velocidad de lectura slider 50–200@100 with Spanish-comma label + Repetir/seek slider driven by speech_tick + version bottom-right). Startup maximized (create_window maximized=True). New Api methods: start_dictation (Windows: legacy Win+H via ctypes keybd_event; macOS: osascript dialog instruction, never silent success; other platforms refuse), close_app (window.destroy). Copy MD/TXT follow the legacy preview-first rule (preview content while Vista previa shows an AI response, otherwise editor text). Deliberate deviations from the original: theme button ships "Tema: Oscuro/Claro" (task wording) instead of legacy "Modo: Dark"; deck is flex-wrap (not absolute pixel coords) so it wraps/scrolls on narrow windows; capability icons are static artboard indicators (not live per-model capability states); Micrófono keeps the constant "Micrófono" label instead of legacy "Mic <Esc>" relabel (message conveys the state). Validation: 342/342 app tests green (was 303; +30 UI contract, +9 dictation/close), compileall clean, node --check clean, GUI smoke maximized open/destroy OK, screenshot verified against the artboard. (design-only, no production code touched): `design/txt-original-parity/01-original-layout.html` is the chosen single artboard (1920×1000, maximized window) reproducing the original layout — title bar, 52px top nav/status bar, 46px Contexto IA bar, editor canvas, and the full 188px bottom deck (3 button rows + speed/replay slider row, version bottom-right) with the exact legacy labels, coordinates and navy/lilac palette (`$themePalettes`, `SetBounds` from txt.ps1). `design/system.md` + `design/system.html` sync the pywebview tokens from `app/www/css/app.css` (token source for the system doc). No alternatives were explored because S8 requests exact parity, not a redesign. Noted discrepancy for T15 implementation: the artboard uses the deck label "Tema: Oscuro" as specified, while legacy txt.ps1 uses "Modo: Dark"; the parent should confirm which string T15 ships.

- L13: T13 re-closed after visual proof: maximized GUI screenshot verified against the supplied original screenshots; 342/342 app tests green.
