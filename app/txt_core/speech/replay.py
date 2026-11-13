"""Replay helpers, ported from txt.ps1 (Get-ReplayWordTimings 3682,
Get-AtempoFilter, Format-ReplayTime)."""
from __future__ import annotations

import math
from typing import Sequence

from .alignment import next_alignment_cursor


def get_replay_word_timings(mark_seconds: Sequence[float], spoken_words: Sequence[str],
                            words: Sequence[str], start_cursor: int) -> dict[str, list]:
    """Re-run the alignment over spoken words to build replay seek marks.

    Only spoken words that advance the cursor past startCursor produce an
    entry; a repeated index never duplicates.
    """
    seconds: list[float] = []
    word_indices: list[int] = []
    cursor = start_cursor
    misses = 0
    for i, spoken in enumerate(spoken_words):
        cursor, misses = next_alignment_cursor(words, cursor, misses, spoken)
        if cursor > start_cursor and (not word_indices or word_indices[-1] != cursor):
            seconds.append(mark_seconds[i])
            word_indices.append(cursor)
    return {"seconds": seconds, "words": word_indices}


def build_atempo_filter(tempo: float) -> str:
    """ffmpeg atempo chain for a playback tempo, or '' when none is needed."""
    if abs(tempo - 1.0) < 0.001:
        return ""
    stages: list[str] = []
    remaining = tempo
    while remaining > 2.0:
        stages.append("atempo=2")
        remaining /= 2.0
    while remaining < 0.5:
        stages.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1.0) >= 0.001:
        stages.append(f"atempo={round(remaining, 4)}")
    return ",".join(stages)


def format_replay_time(seconds: float) -> str:
    """Legacy '{0}:{1:00}' with floored seconds."""
    total = int(math.floor(max(0.0, seconds)))
    return f"{total // 60}:{total % 60:02d}"
