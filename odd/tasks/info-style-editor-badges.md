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

- [ ] T1 — Editor not covered by context panel (route: inline, one file, already diagnosed)
- [ ] T2 — Shared informational style (Notice color + one font) for status, update, hint, version, attachment labels in both themes (route: inline)
- [ ] T3 — Capability badges (chat, reasoning, web, vision, text files) in green next to "Contexto IA" with tooltips (route: inline)

## Checks

- `python -m unittest discover -s tests` (static contract tests; RED before GREEN)
- PowerShell parser check of `txt.ps1`

## Progress

- Branch: `feat/info-style-editor-badges`
