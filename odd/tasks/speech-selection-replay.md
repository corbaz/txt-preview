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
- [x] T6 — Word highlighting during Repetir, following playback and the seek slider (route: delegated)
- [x] T7 — Clicks during Repetir never leak into the next Play; a new preview text deletes the Repetir cache (route: delegated)
- [x] T8 — Any AI request stops the reading or Repetir and deletes the Repetir audio first (route: delegated)
- [x] T9 — Strip web-search citation markers from AI answers (route: delegated)

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

- T5 (editable preview synced to the Editor) was implemented in `28ffde2` and reverted at the user's request: Vista previa stays read-only (selection + click-to-jump only); text is edited only in the Editor.
- T6 decisions: the cache stores word timings (audio offset -> preview word index) next to the audio. Edge marks come from WordBoundary per chunk, offset by the summed duration of the chunks joined before them. Windows marks come from the background WAV render's SpeakProgress, collected by a compiled `SpeechRenderTrack` class (render events can arrive on worker threads, where a PowerShell script block crashed the process in the smoke). The WAV is rendered at 16 kHz 16-bit mono because SAPI reports AudioPosition on a 16 kHz clock: at 22.05 kHz the marks ran about 38% ahead of the audio (measured with ffmpeg silencedetect on Helena and Laura). Marks past the audio end are dropped. Offsets map to preview words with the same aligner as the live reading (`Get-NextAlignmentCursor`, shared), starting from the reading's start word (selection or click); selections with an unknown start get no timings. A SHA-256 of the preview words at reading time is stored; Repetir re-checks it after every preview re-render and plays without highlight when the text differs. Clicks during Repetir stay ignored; only the slider moves the position (dragging previews the word).
- T6: tests RED 5 (+1 for the 16 kHz fix) -> GREEN 63 OK; parser 0 errors.
- T6 smoke (standalone WebBrowser with real preview HTML, live Windows voice muted with SetOutputToNull, silent WAV swapped in for timer-driven playback; no keyboard simulation): Windows render completed with 20 marks for 20 words; Edge two real chunks gave 20 marks, chunk 2's first word at 0.10 s cached at 3.916 s (= 3.816 s chunk 1 + 0.10 s). Seek mapping Windows 0/1/2.5/4/7.7 s -> none/con/en/Segunda/repeticion.; Edge 0/1/2.5/4/7.6 s -> none/algunas/voz/Segunda/repeticion. Timer-driven replay at 2.0 s highlighted "para"; seek while paused to 4.0 s stayed paused on "Segunda"; seek back to 0.5 s -> word 0. Different preview text -> highlight disabled, nothing marked; same text re-rendered -> highlight back. A start at word 5 maps the first mark to word 5.
- T7a (review finding R3-click-leak-after-replay): a click during Repetir stayed pending in the preview and became the start of the next Play (which also replaced the cache). Pending clicks are now dropped (`Clear-PreviewSpeechClick`) on every speech tick while Repetir is active, when Repetir starts, when it stops, and in Play when Play interrupts a Repetir. A click made while idle still sets the start of the next Play, unless Repetir runs in between.
- T7b (user decision, replaces T6's play-without-highlight fallback): every cache stores the fingerprint of the preview text it was made from. `Get-ReplayCacheDecision` returns Keep (same text), Delete (other text, or a cache that never learned its text) or Unknown (page still loading). It runs on every preview DocumentCompleted and right after a cache is saved, since Play re-renders new text before the old reading is cached. Delete stops a running Repetir first, then removes the file and disables Repetir and the slider (label back to 0:00 / 0:00). The same text re-rendered (theme change) keeps the cache.
- T7: tests RED 6 -> GREEN 69 OK (includes a pwsh behavior test of the Keep/Delete/Unknown decision); parser 0 errors.
- T7 smoke (standalone WebBrowser with the app's DocumentCompleted handler body, silent WAV, synthetic DOM mouse events only; no keyboard simulation): a click while replaying, while paused, and just before Stop all left no pending click (-1); an idle click stayed pending (3) and Play's reader returned it; an idle click before Repetir was dropped at start. Theme re-render of the same text kept the cache (Repetir enabled, 0:00 / 0:04). New text while replaying stopped the replay (provider cleared, Idle), deleted the file, disabled Repetir and the slider, label 0:00 / 0:00. A cache keyed to a previous text was deleted by the check.
- T8: `Stop-SpeechForAiRequest` (Stop-VoicePlayback, then Clear-SpeechReplayCache) runs at the start of every AI request path (Corregir, Preguntar, Resumir and the shared Invoke-Translation used by both Traducir buttons), before Start-Busy and the request. A static test checks each path and that no other `Invoke-GroqRequest` call exists. Tests RED -> GREEN; parser 0 errors.
- T8 smoke (real button handlers raised via `OnClick` reflection, `Invoke-GroqRequest` replaced by a canned answer, no network and no keyboard simulation): Resumir during a Windows reading (live voice rendered to a scratch WAV), Preguntar during a playing Repetir, Corregir during a paused Repetir. In all three the request ran with the player Idle and no cache; afterwards mode Idle, Play/Pause/Stop state Idle, "Pausar" label, synthesizer Ready, ffplay process gone, cache file deleted, Repetir and slider disabled, label 0:00 / 0:00. Edge readings use the same Stop-VoicePlayback path but were not run live.
- T9: new (no earlier stripping code existed in txt.ps1 or its history). `Get-AiResponseText` is now the only place that reads the model text; it decodes it and runs `Remove-AiCitationMarkers` for all four request paths, so the preview, Play, Repetir, Llevar al editor and the exports only ever get the clean text. The pattern removes a fullwidth-bracket marker containing a dagger (U+3010 ... U+2020 ... U+3011) on one line, the spaces before it, and the spaces after it when punctuation follows. Normal brackets, Markdown links and fullwidth brackets without a dagger are kept. Tests: static (single `message.content` read, four `Get-AiResponseText` calls) plus a pwsh behavior test over 8 inputs including the user's sample; RED -> GREEN 73 OK; parser 0 errors.
- T9 smoke: the T8 handler runs returned "Experiencia previa en el sector retail. Fuente." from the canned "…retail【2†L58-L62】. Fuente 【0†source】." in both the Editor (Resumir) and the stored AI answer (Preguntar).

- T10 — Every launch starts on `openai/gpt-oss-120b`; the saved model is ignored (route: inline, one mechanical file). Test RED 1 → GREEN; suite OK.
