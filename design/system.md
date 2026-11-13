# TXT Preview — Design System

Token source: `app/www/css/app.css` (the pywebview app stylesheet). This document records only
the tokens that file actually defines — nothing invented, no legacy-app palette mixed in.
The legacy navy/lilac palette is documented separately in `design/txt-original-parity/`.

## 1. Color tokens

Defined once on `:root` (dark default) and overridden by `body[data-theme="light"]`.

### Dark (default, `:root`)

| Token | Value | Used for |
| --- | --- | --- |
| `--bg` | `#202124` | Window background |
| `--panel` | `#2a2b30` | Header, status bar, chrome surfaces |
| `--editor` | `#17181b` | Editor canvas, inputs, browser address bar |
| `--text` | `#e8eaed` | Primary text |
| `--muted` | `#9aa0a6` | Secondary text, labels, hints, version badge |
| `--accent` | `#8ab4f8` | Active tab, links, focus borders, checkbox accent, speech highlight |
| `--border` | `#3c4043` | Separators, ghost-button borders, table cells |

### Light (`body[data-theme="light"]`)

| Token | Value | Used for |
| --- | --- | --- |
| `--bg` | `#ffffff` | Window background |
| `--panel` | `#f1f3f4` | Header, status bar, chrome surfaces |
| `--editor` | `#ffffff` | Editor canvas, inputs, browser address bar |
| `--text` | `#202124` | Primary text |
| `--muted` | `#5f6368` | Secondary text, labels, hints, version badge |
| `--accent` | `#1a73e8` | Active tab, links, focus borders, checkbox accent, speech highlight |
| `--border` | `#dadce0` | Separators, ghost-button borders, table cells |

### Derived (semi-transparent, from the same accent token)

- Speech word highlight: `color-mix(in srgb, var(--accent) 35%, transparent)`.
- Disabled ghost controls: `opacity: 0.5` on the ghost styles.
- Browser frame background: fixed `#fff` (not tokenized).

## 2. Typography

- System font stack (body, controls): `system-ui, -apple-system, "Segoe UI", sans-serif`.
- Editor / code stack: `ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace`.
- Body base size is the browser default (controls set explicit sizes):
  - Segmented nav tabs: `14px`.
  - Ghost buttons, hints, settings labels: `13px`.
  - Version badge, status bar, attachment summary: `12px`.
  - Editor textarea: `15px`, `line-height: 1.6`.
  - Preview (`#preview` padding `18px 26px`): default markdown sizing.

## 3. Radius

| Shape | Value | Applies to |
| --- | --- | --- |
| Pill | `999px` | `.seg` tabs, `.ghost` buttons, browser address bar |
| Medium | `8px` | Settings inputs/selects, markdown `pre` blocks |
| Small | `4px` | Inline `code` spans |

## 4. Spacing

| Context | Value |
| --- | --- |
| Header (`#app-header`) | padding `10px 16px`, gap `12px` |
| Segmented group (`#segmented`) | gap `4px` |
| Toolbar rows (`#ai-bar`, `#preview-bar`, `#speech-bar`, `#editor-tools-bar`) | padding `10px 16px 0` (speech-bar), `8px 16px` (editor-tools-bar), gap `8px`, `flex-wrap: wrap` |
| Editor padding | `18px 22px` |
| Preview padding | `18px 26px` |
| Settings form | max-width `520px`, centered, gap `6px`, top margin `24px`, side padding `20px`, label top margin `10px` |
| Status bar (`#status-bar`) | padding `6px 16px`, `min-height: 28px` |
| Attachment summary | padding `6px 16px 0` |
| Browser bar | padding `10px 16px`, gap `8px` |

## 5. Control styles

### Segmented tabs (`.seg`)

- Border: none, background transparent, color `--muted`.
- Padding `8px 18px`, radius `999px`, font-size `14px`.
- Active (`.seg.active`): background `--accent`, color `--bg`.

### Ghost buttons (`.ghost`)

- `1px solid var(--border)` border, transparent background, color `--muted`.
- Padding `7px 14px`, radius `999px`, font-size `13px`.
- Hover: color `--text`, border-color `--accent`.
- Disabled: `opacity: 0.5` (in toolbar rows), cursor default.
- Toolbars keep labels on one line (`white-space: nowrap`) and wrap the row on narrow widths.

### Inputs / selects (settings)

- Background `--editor`, color `--text`, `1px solid var(--border)` border.
- Radius `8px`, padding `10px 12px`, font-size `14px`.
- Focus: border-color `--accent`.
- Row variant (`.row`): flex, gap `8px`, children `flex: 1; min-width: 0`.

### Browser address bar

- Background `--editor`, radius `999px`, padding `8px 16px`, font-size `13px`, `flex: 1`.

### Editor textarea (`#editor`)

- `flex: 1; min-height: 0`, no border/outline, background `--editor`.
- Padding `18px 22px`, font-size `15px`, line-height `1.6`, mono stack.

### Markdown preview

- Links colored `--accent`; inline code pill on `--panel` with `--border`; `pre` blocks radius `8px`.
- Tables collapsed, `--border` cells, `6px 10px` cell padding.
- Blockquote: `3px` left border in `--accent`, muted text, `14px` left padding.

### Speech words

- `.sw { cursor: pointer }`, `.speaking` highlight = 35% accent tint.

## 6. Layout skeleton

- `body`: `height: 100vh`, `overflow: hidden`, column flex — header on top, `#pages` fills,
  chrome bars (`#status-bar`, toolbar rows) live inside pages.
- Pages: one visible at a time (`.page.active`), `flex: 1`, own scrolling (`overflow: auto`);
  the editor page is a column flex so the textarea stretches.
- Header order: segmented tabs → theme toggle (ghost) → version badge pushed right with `margin-left: auto`.

## 7. Accessibility notes

- Keyboard focus is only styled on settings inputs (`border-color: --accent`); buttons rely on
  the browser default outline — keep it, never remove the focus ring.
- Theme is driven by `body[data-theme]`, not by OS preference.
- Checkbox uses `accent-color: var(--accent)`; labels wrap their inputs (`.ghost` label pattern).
