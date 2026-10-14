# Local subscription bridges as AI providers
Objective: let txt.ps1 use the local Claude, Codex and Gemini bridges next to Groq. Branch: `feat/local-bridges`.
Delivery: ask-on-risk (forecast ~450 authored lines). Test runner: `python -m unittest discover -s tests` (pwsh 7, Windows).

## Specs
- S1 Providers: Claude bridge (`http://127.0.0.1:4098`, user `claude`), Codex bridge (`4094`, user `codex`) and Gemini bridge (`4092`, user `gemini`) become providers next to Groq. OpenCode (`4096`) stays out for a second stage (user answer to "¿Arrancamos solo con los tres bridges, que comparten protocolo, y dejamos OpenCode para una segunda etapa?": "ok").
- S2 Detection: "y en configuracion hay que poner algo o se pueden ver si estan arrancados?" — bridges are probed at startup and on "Actualizar modelos"; Configuración shows each bridge as off, missing/wrong password, or connected with its model count. A bridge that is off adds no models.
- S3 One selector: "y en la pantalla de modelo hay que elegir el provedor y el modelo?" — agreed answer: a single model selector grouped by provider, e.g. `Groq · openai/gpt-oss-120b`, `Claude · Sonnet`.
- S4 Passwords: "en el profile ya estan las contraseña pero vos queres que las revalide ?" — the password is read from `CLAUDE_BRIDGE_PASSWORD` / `CODEX_BRIDGE_PASSWORD` / `GEMINI_BRIDGE_PASSWORD` (process, then user environment); otherwise from an optional field in Configuración, stored encrypted for the Windows user like the Groq key; otherwise from `%LOCALAPPDATA%\prompting\<name>-bridge\password.txt`.
- S5 Protocol: `GET /models` -> `[{id, name, vision?}]`; `POST /chat` with `{model, message, images:[{mimeType, data}]}` -> `{text, isError, error}`; HTTP Basic auth. Text documents travel inside `message`, as with Groq.
- S6 Capabilities: bridge models chat and accept documents as text; vision for Claude, for Codex models that report `vision`, never for Gemini. No web search on bridges.
- S7 Only local: "al estar los brige solo lopuede unsar los locales o el port queda expuesto para cualqiera" — answered: bridges bind `127.0.0.1` (verified in source and netstat); the app only talks to `127.0.0.1`.

## Tasks
- [ ] T1 S1 S2 S4 S5 S6 S7 — bridge core: probing, password resolution, model listing, capabilities, request/response dispatch. Route: inline (no writer trigger). Commit: -
- [ ] T2 S2 S3 S4 — UI: grouped selector, models list provider column, Configuración bridge status and optional password fields, attachment label names the provider. Route: inline. Commit: -
- [ ] T3 S1-S7 — README and in-app hints. Route: inline. Commit: -

## Log
- L1 (2026-10-14) User: "estos funciones las tengo en profiles C:\Users\Sancho\OneDrive - NTT DATA EMEAL\Documents-ScriptLabs\PowerShell\Microsoft.PowerShell_profile.ps1 no te puse las pass pero yo los tengo corriendo y andan no se como lo configurariamos en los provedorees y modelos" (profile defines `gemini-server` 4092, `codex-server` 4094, `zen-server` 4096, `claude-server` 4098).
- L2 Evidence: the three bridges answer 401 with their `password.txt`; the profile sets the passwords inside each server function only, so `txt` (run in-process by the profile function) sees them only if they move to the profile top level.
- L3 User approved the design ("ok"): single grouped selector, passwords from environment with Configuración as option.
