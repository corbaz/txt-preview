"""Conservative es/en text-language detection for the Play voice switch
(S13 rule 2). Legacy txt.ps1 had no detection; S13 adds it: only a clear
signal switches the voice, otherwise the chosen voice stays.

Heuristic: Spanish/English marker words plus the Spanish accents (á é í ó
ú ü ñ ¿ ¡) score each language; a decision needs at least MIN_WORDS words,
at least MIN_HITS marker hits, and a winner share >= WINNER_SHARE.
"""
from __future__ import annotations

import re

SPANISH_WORDS = {
    "el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "es",
    "por", "para", "con", "se", "más", "pero", "qué", "cómo",
}
ENGLISH_WORDS = {
    "the", "of", "and", "to", "in", "is", "it", "you", "that", "was", "for",
    "are", "with", "they", "this", "have", "from", "not",
}
SPANISH_MARKS = set("áéíóúüñ")

MIN_WORDS = 4
MIN_HITS = 2
WINNER_SHARE = 0.6

_WORD = re.compile(r"[a-záéíóúüñ]+")


def detect_language(text: str | None) -> str | None:
    """Return "es" or "en" for a clearly dominant text, else None.

    Short texts, marker-free garbage and ties stay undecided (the caller
    keeps the user's chosen voice — insufficient signal).
    """
    raw = text or ""
    words = _WORD.findall(raw.lower())
    if len(words) < MIN_WORDS:
        return None
    spanish = english = 0
    for word in words:
        if word in SPANISH_WORDS or any(mark in word for mark in SPANISH_MARKS):
            spanish += 1
        if word in ENGLISH_WORDS:
            english += 1
    # The opening ¿ / ¡ markers are punctuation outside the word tokens.
    spanish += raw.count("¿") + raw.count("¡")
    total = spanish + english
    if total < MIN_HITS:
        return None
    if spanish > english and spanish / total >= WINNER_SHARE:
        return "es"
    if english > spanish and english / total >= WINNER_SHARE:
        return "en"
    return None
