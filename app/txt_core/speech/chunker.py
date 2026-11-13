"""Speech text chunking, ported from txt.ps1 (Split-TextIntoSpeechChunks).

S14/T21: the first chunk is a short lead so the first audio starts fast. The
lead ends at the first reasonable sentence or blank-line boundary after a
minimum of 8 words (never later than 25 words / ~180 chars); without such a
boundary it cuts at the last word boundary inside that range (a word is never
split). The remainder is grouped by the legacy balanced-by-length algorithm
into at most desired-1 chunks, so no text is lost or duplicated.
"""
from __future__ import annotations

import bisect
import math
import re

_MIN_LEAD_WORDS = 8
_MAX_LEAD_WORDS = 25
_MAX_LEAD_CHARS = 180

_WORD = re.compile(r"\S+")
# Sentence end: . ! ? … followed by whitespace or the end of the text.
_SENTENCE_END = re.compile(r"[.!?\u2026]+(?=\s|$)")
_PARAGRAPH_SPLIT = re.compile(r"(?:\r?\n)+")


def _word_boundaries(text: str) -> list[tuple[int, int, int]]:
    """(cut position, word count, char length) after every word."""
    return [(match.end(), count, match.end())
            for count, match in enumerate(_WORD.finditer(text), start=1)]


def _lead_cut(text: str) -> int | None:
    """Character offset where the short lead ends, or None to keep it whole."""
    word_cuts = _word_boundaries(text)
    if not word_cuts:
        return None
    ends = [cut for cut, _, _ in word_cuts]

    def boundary_at(position: int) -> tuple[int, int]:
        return bisect.bisect_right(ends, position), position

    # Reasonable boundaries in text order: sentence ends first, then blank
    # lines (a paragraph break is also a reasonable boundary — it preserves
    # paragraphs where possible).
    candidates = [boundary_at(match.end())
                  for match in _SENTENCE_END.finditer(text)]
    candidates += [boundary_at(match.start())
                   for match in _PARAGRAPH_SPLIT.finditer(text)]
    for count, position in sorted(candidates):
        if _MIN_LEAD_WORDS <= count <= _MAX_LEAD_WORDS \
                and position <= _MAX_LEAD_CHARS:
            return position
    # No sentence/paragraph boundary in range: cut at the last word boundary
    # at or before 25 words (never splitting a word).
    loose = [cut for cut, count, _ in word_cuts if count <= _MAX_LEAD_WORDS]
    if loose:
        return loose[-1]
    return word_cuts[0][0]


def split_text_into_speech_chunks(text: str, desired_chunks: int = 6) -> list[str]:
    """Short lead chunk first, then the balanced remainder (at most desired-1)."""
    text = (text or "").strip()
    if not text:
        return []
    if desired_chunks <= 1:
        return [text]
    if len(_WORD.findall(text)) <= _MAX_LEAD_WORDS or len(text) <= _MAX_LEAD_CHARS:
        return [text]
    cut = _lead_cut(text)
    if cut is None or cut >= len(text):
        return [text]
    lead = text[:cut].rstrip()
    rest = text[cut:].lstrip()
    if not rest.strip():
        return [lead]
    return [lead] + _balanced_paragraph_groups(rest, desired_chunks - 1)


def _balanced_paragraph_groups(text: str, desired_groups: int) -> list[str]:
    """Legacy balanced-by-length grouping of trimmed paragraphs."""
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text.strip()) if p.strip()]
    if not paragraphs:
        return []

    group_count = max(1, min(desired_groups, len(paragraphs)))
    groups: list[str] = []
    paragraph_index = 0

    for group_index in range(group_count):
        remaining_groups = group_count - group_index
        remaining_length = sum(len(p) for p in paragraphs[paragraph_index:])
        target_length = math.ceil(remaining_length / remaining_groups)
        parts: list[str] = []
        current_length = 0

        while paragraph_index < len(paragraphs):
            parts.append(paragraphs[paragraph_index])
            current_length += len(paragraphs[paragraph_index])
            paragraph_index += 1

            paragraphs_left = len(paragraphs) - paragraph_index
            groups_left = group_count - group_index - 1
            if groups_left > 0 and current_length >= target_length and paragraphs_left >= groups_left:
                break
            if paragraphs_left == groups_left:
                break

        groups.append("\n\n".join(parts))

    return groups
