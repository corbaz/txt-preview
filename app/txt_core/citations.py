"""Web-search citation-marker stripping, ported from txt.ps1 (Remove-AiCitationMarkers).

The legacy regex drops markers such as 【2†L58-L62】 or 【0†source】: fullwidth
brackets around a dagger. The spaces around a marker go too when it sat before
punctuation.
"""
from __future__ import annotations

import re

# Port of $aiCitationPattern in txt.ps1:4814.
_CITATION_PATTERN = re.compile(
    r"[ \t]*\u3010[^\u3010\u3011\r\n]*\u2020[^\u3010\u3011\r\n]*\u3011"
    r"(?:[ \t]+(?=[.,;:!?\u2026)\]]))?"
)


def strip_citation_markers(text: str) -> str:
    """Remove AI citation markers so previews, speech and exports never see them."""
    if not text:
        return text
    return _CITATION_PATTERN.sub("", text)
