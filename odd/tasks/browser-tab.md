# Feature: browser-tab

## Objective

Web search on by default for web-capable models, and an embedded browser tab: links clicked in Vista previa open there, with an address bar, back/forward history, manual URLs, and a fallback to the system default browser.

## Decisions

- Engine: WebView2 (user choice). The Edge runtime is already installed; the app downloads the pinned NuGet package `Microsoft.Web.WebView2` 1.0.4258.31 once, extracts three DLLs (~930 KB) into `%LOCALAPPDATA%\TXT Preview\webview2\<version>`, and loads them only if each has a valid Microsoft Authenticode signature.
- The browser is created lazily on first use, so startup never downloads anything.
- Web search defaults on whenever a web-capable model is selected; the checkbox only applies to the current session (no longer persisted).

## Tasks

- [x] T1 — Web search on by default (route: inline)
- [x] T2 — WebView2 bootstrap: download, verify signatures, load (route: inline)
- [x] T3 — Navegador tab: nav button, back/forward, address bar, open externally (route: inline)
- [x] T4 — Preview link clicks open the Navegador tab (route: inline)

## Checks

- `python -m unittest discover -s tests` (static contract tests; RED before GREEN)
- Test-mode smoke: load the app with `TXT_PREVIEW_TEST_MODE=1`, open a URL in the Navegador tab, check title, back/forward state.

## Progress

- Branch: `feat/keep-prompt`, merged into `main` and pushed with the version bump.
- Native review: approved and acknowledged (lineage review-4b5bab069ee8dbda) after excluding `.git/.gentle-ai-*` from the VS Code file watcher.
- T1 `3ced18e`; T2-T4 in the next commit.
- Tests: RED 4 failing, GREEN 32 OK; parser 0 errors; VS Code diagnostics empty.
- Smoke (test mode): example.com opened in 0.9-1.9 s (first run includes download); back/forward states correct; a preview link click switched to Navegador and loaded the page.
- Tamper check: appending a byte to a DLL made it NotSigned; the app rejected it, deleted the folder, and re-downloaded on the next run.
- Prototype: WebView2 154 loaded from pwsh 7 and navigated to example.com; all three DLLs Valid / CN=Microsoft Corporation.
