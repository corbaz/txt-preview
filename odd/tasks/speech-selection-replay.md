# Feature: speech-selection-replay

## Objective

Text-to-speech improvements in Vista previa:
1. If text is selected in the preview when Play is pressed, read only the selection, not the whole text.
2. Keep the last generated audio until a new full generation; a Replay button plays it again without re-synthesizing, and a seek slider next to it moves playback forward/backward.

## Scope

- `txt.ps1` (preview HTML/JS, speech state, toolbar controls), `tests/`, `README.md`.
- Applies to both voice providers where feasible (Edge via file + ffplay; Windows SpeechSynthesizer via WAV file).

## Tasks

- [x] T1 — Play reads only the preview selection when one exists (route: delegated, writer trigger: large file needing preparation reading)
- [ ] T2 — Cached audio + Replay button + seek slider (route: delegated)

## Checks

- `python -m unittest discover -s tests` (static contract tests; RED before GREEN)
- PowerShell parser: 0 errors on `txt.ps1`
- Test-mode smoke with `TXT_PREVIEW_TEST_MODE=1` where possible

## Progress

- Branch: `feat/speech-selection-replay`
- T1: `getSpeechSelection` / `getSpeechSelectionStartWord` in the preview JS; Play reads the selection before re-rendering (the selection branch only switches tab, so the selection survives) and starts DOM alignment at the selected word. Without a known start word, highlighting is disabled rather than wrong. Tests RED 4 -> GREEN; parser 0 errors.
- T1 smoke: real preview HTML in a WebBrowser (IE11 mode) — selection inside a word returns start word 3 (fixed an IE quirk: `contains()` ignores text nodes), a selection starting on whitespace returns the next word, no selection returns empty; selection survives focus moving to a button.
