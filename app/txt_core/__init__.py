"""TXT Preview platform-neutral core: logic ported from the legacy txt.ps1.

Public surface: citations, prompts, groq, bridges, models.
"""
from .citations import strip_citation_markers
from .prompts import consult_prompt, correct_prompt, summarize_prompt, translate_prompt

__all__ = [
    "strip_citation_markers",
    "consult_prompt",
    "correct_prompt",
    "summarize_prompt",
    "translate_prompt",
]
