"""Web-search citation-marker stripping, ported from txt.ps1 (Remove-AiCitationMarkers).

The legacy regex drops markers such as 【2†L58-L62】 or 【0†source】: fullwidth
brackets around a dagger. The spaces around a marker go too when it sat before
punctuation.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

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


def builtin_tool_sources(message: Mapping[str, Any]) -> list[str]:
    """Deterministic source lines from Groq browser-search payload data.

    Groq chat completions can expose search results in
    ``message.executed_tools[].search_results.results[]``. Newer compatible
    response shapes may instead use OpenAI-style ``url_citation`` annotations;
    the older Groq SDK shape nests ``citations[]`` inside an annotation. Only
    URLs actually present in the payload are returned — nothing is fabricated.
    """
    citations: list[Mapping[str, Any]] = []
    for annotation in message.get("annotations") or []:
        if not isinstance(annotation, Mapping):
            continue
        url_citation = annotation.get("url_citation")
        if isinstance(url_citation, Mapping):
            citations.append(url_citation)
        citations.extend(
            item for item in annotation.get("citations") or []
            if isinstance(item, Mapping)
        )

    for tool in message.get("executed_tools") or []:
        if not isinstance(tool, Mapping):
            continue
        search_results = tool.get("search_results")
        if not isinstance(search_results, Mapping):
            continue
        citations.extend(
            item for item in search_results.get("results") or []
            if isinstance(item, Mapping)
        )

    lines: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        url = citation.get("url")
        if not isinstance(url, str) or not url or url in seen:
            continue
        seen.add(url)
        title = citation.get("title")
        lines.append(f"- [{title}]({url})" if title else f"- {url}")
    return lines
