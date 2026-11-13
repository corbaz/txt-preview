"""Spoken-word alignment cursor, ported from txt.ps1 (Get-NextAlignmentCursor /
Step-SpeechAlignment, line 3622).

The cursor sits on the preview word expected to be spoken next. Words at or
before AlignFloor were not spoken in this reading and are never highlighted.
Legacy constants: alignment window 8 words; 2 consecutive misses step forward.
"""
from __future__ import annotations

from typing import Sequence

from .marks import speech_alignment_key

ALIGNMENT_WINDOW = 8
MISSES_BEFORE_STEP = 2


def next_alignment_cursor(words: Sequence[str], cursor: int, misses: int,
                          spoken_word: str) -> tuple[int, int]:
    """Advance (cursor, misses) for one spoken word over keyed preview words."""
    key = speech_alignment_key(spoken_word)
    if not key:
        return cursor, misses

    start = cursor + 1
    if start >= len(words):
        return cursor, misses

    # Skip non-alphanumeric tokens; they can never match a spoken word.
    next_index = start
    while next_index < len(words) - 1 and words[next_index] == "":
        next_index += 1
    next_word = words[next_index]

    if next_word and (next_word == key or next_word.startswith(key) or key.startswith(next_word)):
        return next_index, 0

    # The engine split a compound token: the current word contains what was spoken.
    if cursor >= 0 and words[cursor] and key in words[cursor]:
        return cursor, misses

    # Exact matches only, inside a bounded look-ahead window.
    limit = min(len(words) - 1, start + ALIGNMENT_WINDOW)
    for index in range(next_index + 1, limit + 1):
        if words[index] == key:
            return index, 0

    misses += 1
    if misses >= MISSES_BEFORE_STEP:
        return next_index, 0
    return cursor, misses
