# Feature: pdf-and-documents

## Objective

Professional A4 PDF export, and attaching PDF, Word and PowerPoint documents to AI requests.

## Decisions

- PDF export uses a print-only document (`Get-PrintHtml`), separate from Vista previa: A4, 22/20/24 mm margins through `@page` (the old body padding left pages 2+ without margins), always-light paper, "Página X de Y" footer, and break rules (headings keep with their text, orphans/widows 3, no splitting of code, quotes or list items, repeated table headers). Vista previa and print share `ConvertTo-PreviewBodyHtml`.
- Groq's API accepts only text and images, so documents are attached as text extracted locally:
  - `.docx` / `.pptx`: parsed from their Open XML parts, no Office needed; slides ordered numerically.
  - `.doc` / `.ppt`: read through Word/PowerPoint COM, read-only, closed afterwards; without Office the user is asked to save as `.docx`/`.pptx`.
  - `.pdf`: PdfPig 0.1.16 (Apache-2.0, unsigned), downloaded once from NuGet and accepted only if the package SHA-256 matches the pinned hash; requires PowerShell 7.
  - Extracted text is capped at 300,000 characters; scanned PDFs without text raise a clear error.

## Tasks

- [x] T1 — A4 print layout for PDF export (route: inline) — `caacacd`
- [x] T2 — Attach PDF, Word and PowerPoint as extracted text (route: inline) — `6a1b635`

## Checks and evidence

- Tests: RED observed for each task; GREEN 38 OK, including generated `.docx`/`.pptx` extraction tests.
- PDF export compared before/after on the same sample: Letter 216x279 mm, 9 pages, dark background, no margins on pages 2+ → A4 210x297 mm, 6 pages, white, margins on every page, repeated table header.
- Real files: PDF (6 pages, 1.5 s including the PdfPig download), `.doc`, `.ppt`, Office-written `.docx`/`.pptx`; no Word/PowerPoint process left running.
- Wrong hash: package rejected, nothing extracted, temporary download removed.
- Native review: approved and acknowledged (lineages review-5a7fa2896c93c07b and review-b849f1a1d5ed917f).
