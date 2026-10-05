# Feature: info-style-editor-badges

## Objective

Fix the editor typing bug, unify the style of informational messages across themes, and show the selected model capabilities as green icons next to "Contexto IA".

## Problem

- The editor looks like it does not accept typing: `$contextPanel.BringToFront()` docks the Top panel after the Fill `TextBox`, so the panel covers the first 46 px where the caret lives (reproduced with a minimal WinForms layout).
- Informational labels use mixed colors (`Muted` vs `Notice`) and fonts, including update messages in Configuración.
- The editor context bar does not show what the selected model can do.

## Scope

- `txt.ps1` and `tests/test_txt_settings.py` only.

## Tasks

- [x] T1 — Editor not covered by context panel (route: inline, one file, already diagnosed)
- [x] T2 — Shared informational style (Notice color + one font) for status, update, hint, version, attachment labels in both themes (route: inline)
- [x] T3 — Capability badges (chat, reasoning, web, vision, text files) in green next to "Contexto IA" with tooltips (route: inline)

## Checks

- `python -m unittest discover -s tests` (static contract tests; RED before GREEN)
- PowerShell parser check of `txt.ps1`

## Progress

- Branch: `feat/info-style-editor-badges`
- T1 `0fce313`, T2 `243a8ea`, T3 `b3cba26`.
- RED observed (4 failing contract tests), then GREEN: `python -m unittest discover -s tests` -> 17 OK.
- Parser check: 0 errors. App launched for 15 s without runtime errors.
- Icon glyphs E8BD/E82F/E774/E890/E723 verified present in Segoe Fluent Icons.
- Review assess: risk medium, review_due false (under_budget).
- Pending: visual check by the user (no visible desktop in the agent session).
