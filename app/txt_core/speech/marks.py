"""Edge word marks and alignment keys, ported from txt.ps1 (Get-EdgeWordMarks,
Get-SpeechAlignmentKey, Get-SpeechWordsKey, Get-EdgeMarkIndexAt).

WordBoundary timings carry each spoken word and its audio offset; locating the
word in the chunk text turns the audio clock into an exact character position.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

_WORD_KEY_STRIP = re.compile(r"[^\w]", re.UNICODE)
_WHITESPACE_TOKEN = re.compile(r"\S+")


@dataclass(frozen=True)
class EdgeWordMark:
    start_seconds: float
    character: int
    text: str


def speech_alignment_key(word: str) -> str:
    """Lowercased word with punctuation stripped, used for cursor matching."""
    return _WORD_KEY_STRIP.sub("", word.lower())


def speech_words_key(raw_words: str) -> str:
    """Hex SHA-256 of the rendered word list; caches only reuse on same preview."""
    return hashlib.sha256(raw_words.encode("utf-8")).hexdigest()


def edge_word_marks(text: str, word_timings: Iterable[dict[str, Any]]) -> list[EdgeWordMark]:
    """Map per-word audio offsets onto character positions of the chunk text."""
    marks: list[EdgeWordMark] = []
    cursor = 0
    lowered = text.lower()
    for timing in word_timings:
        word = str(timing.get("text", ""))
        if not word:
            continue
        position = lowered.find(word.lower(), cursor)
        if position < 0:
            position = cursor
        else:
            cursor = position + len(word)
        marks.append(EdgeWordMark(
            start_seconds=float(timing.get("start_seconds", 0.0)),
            character=position,
            text=word,
        ))
    return marks


def word_index_at_character(text: str, character: int) -> int:
    """Index of the whitespace-separated token containing/preceding a character.

    Maps an EdgeWordMark's character offset onto the preview word list for the
    replay cache: tokens counted with \S+ finditer, 0 before the first token.
    """
    index = -1
    for match in _WHITESPACE_TOKEN.finditer(text):
        if match.start() > character:
            break
        index += 1
    return index if index >= 0 else 0


def get_mark_index_at(marks: Sequence[EdgeWordMark], elapsed: float, lead: float = 0.0) -> int:
    """Index of the last word whose audio onset was reached, or -1.

    Binary search for the last start_seconds <= elapsed + lead
    (legacy $speechHighlightLeadSeconds lookup extension).
    """
    lookup_time = elapsed + lead
    low, high = 0, len(marks) - 1
    found = -1
    while low <= high:
        middle = (low + high) // 2
        if marks[middle].start_seconds <= lookup_time:
            found = middle
            low = middle + 1
        else:
            high = middle - 1
    return found
