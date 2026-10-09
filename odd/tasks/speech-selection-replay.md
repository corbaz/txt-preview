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
- [x] T2 — Cached audio + Replay button + seek slider (route: delegated)
- [x] T3 — Bubblegum pink tracking highlight visible over a selection in both themes; tracked word kept near the top (route: delegated)
- [x] T4 — Caret click sets the reading start; clicks while reading jump voice and highlight (route: delegated)

## Checks

- `python -m unittest discover -s tests` (static contract tests; RED before GREEN)
- PowerShell parser: 0 errors on `txt.ps1`
- Test-mode smoke with `TXT_PREVIEW_TEST_MODE=1` where possible

## Decisions

- Playback/seek: ffplay restarted with `-ss <offset>` on the cached file (the same player Edge already uses). Pause/Continuar reuse the existing NtSuspendProcess path, so no new player (WMP COM) dependency. Position = offset + elapsed clock, shown by the 40 ms speech timer.
- One cached file per generation: Edge chunks are bare MP3 frames, so they are byte-concatenated into one MP3; Windows voices render the same text to a WAV with a second SpeechSynthesizer in the background (SetOutputToWaveFile), since live System.Speech output cannot be replayed or seeked.
- The cache is replaced only when a new reading started with Play has been fully generated (Edge: every chunk ready; Windows: WAV render complete); voice/speed restarts do not cache. Deleted on close.
- Clicks: the preview JS records a plain click (pointer moved at most 4 px, selection collapsed, not on a link) as a word index; Play consumes it to read from that word, and the 40 ms speech timer polls it while an Edge or Windows reading is active to jump there. Polling via `InvokeScript` was chosen over HtmlDocument events because the document is rebuilt on every render.
- Jumps restart synthesis from the clicked word for both providers (text rebuilt from the rendered words, block changes as line breaks), keep the paused state, and never replace the Repetir cache (partial, like voice/speed restarts). A reading started by Play from a click is a new generation and is cached, like a selection reading. Clicks during Repetir are ignored (no word marks).
- Replay has no word highlighting (cached audio carries no word marks); voice/speed changes during Repetir only warn.

## Progress

- Branch: `feat/speech-selection-replay`
- T1: `getSpeechSelection` / `getSpeechSelectionStartWord` in the preview JS; Play reads the selection before re-rendering (the selection branch only switches tab, so the selection survives) and starts DOM alignment at the selected word. Without a known start word, highlighting is disabled rather than wrong. Tests RED 4 -> GREEN; parser 0 errors.
- T1 smoke: real preview HTML in a WebBrowser (IE11 mode) — selection inside a word returns start word 3 (fixed an IE quirk: `contains()` ignores text nodes), a selection starting on whitespace returns the next word, no selection returns empty; selection survives focus moving to a button.
- T2: Repetir button, replay TrackBar (tenths of a second) and `m:ss / m:ss` label in the speed row; disabled without cache or without ffplay. Tests RED 8 -> GREEN 50 OK; parser 0 errors.
- T2 smoke (test mode, silent WAV): cache enables controls, WAV header duration 3.33 s vs ffprobe 3.328 s, replay from 1.0 s reported 2.0 s after 1 s, pause freezes the clock, seeking while paused stays paused at 2.5 s, natural end returns to Idle and keeps the cache, close removes it. Edge concat: 2.184 s + 3.600 s chunks -> 5.784 s, decodes without errors.
- Not exercised: live audible playback through the full app window (DocumentText does not load in the hidden test-mode form).
- T3: tracking highlight `#FF69B4` with `#2B0016` text (about 7.9:1 contrast) in both palettes, plus `.speech-active::selection`; the native selection is cleared (`clearSpeechSelection`) right after its text and start word are captured, since it painted over the highlight. Auto-scroll keeps the word between 10% and 50% of the viewport, re-anchoring it at 20%. Tests RED 3 -> GREEN; parser 0 errors.
- T3 smoke (standalone WebBrowser, real preview HTML, light and dark): selection read then cleared to empty; computed active-word style `rgb(255, 105, 180) / rgb(43, 0, 22)` in both themes; jumping to word 300 scrolled it to 20% of the viewport.
- T4: `findSpeechWordAtPoint`, `recordSpeechClick`, `takeSpeechClick`, `getSpeechTextFrom` in the preview; `Get-PreviewSpeechClick`, `Get-PreviewSpeechTextFrom`, `Move-SpeechToWord`; alignment floor so the word before a partial start is never highlighted. Tests RED 3 -> GREEN 57 OK; parser 0 errors.
- T4 smoke (standalone WebBrowser, synthetic mouse events): click on word 5 -> 5 (consumed once); click right of a line end -> next block's first word (10); drag 2->6 -> -1; click over a selection -> -1; click on a link -> -1; text from word 7 keeps block breaks. Jump with a Windows voice (output muted): restarted at word 12, alignment floor 11, cache eligibility false.
