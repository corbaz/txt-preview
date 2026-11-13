"""Speech text chunking, ported from txt.ps1 (Split-TextIntoSpeechChunks).

Paragraphs are grouped so reading can start while later blocks are still
synthesizing; the Edge pipeline synthesizes and plays one chunk at a time.
"""
from __future__ import annotations

import math
import re

_PARAGRAPH_SPLIT = re.compile(r"(?:\r?\n)+")


def split_text_into_speech_chunks(text: str, desired_chunks: int = 6) -> list[str]:
    """Group trimmed paragraphs into at most desired_chunks blank-line-joined groups."""
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text.strip()) if p.strip()]
    if not paragraphs:
        return []

    group_count = min(desired_chunks, len(paragraphs))
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
