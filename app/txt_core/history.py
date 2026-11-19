"""Historial: the last texts of the Editor, newest first.

The list lives in settings.json ("history", "history_limit"), shared with
txt.ps1 (Add-TextHistory). Rules, the same in both apps:
- an empty text is never saved;
- a text already in the list is not saved again and the order stays;
- any other text goes on top with its date, and the list keeps only the
  newest `limit` entries; so a loaded text that was changed comes back as a
  new entry on top.
Texts are stored with "\n" line ends and no trailing blanks.
The date is "yyyy-MM-dd HH:mm:ss", never ISO with a "T": PowerShell 7's
ConvertFrom-Json would turn that into a DateTime.
"""
from __future__ import annotations

from datetime import datetime

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 50
LABEL_CHARS = 60


def clean_limit(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(MIN_LIMIT, min(MAX_LIMIT, number))


def normalize(text) -> str:
    return str(text or "").replace("\r\n", "\n").rstrip()


def clean_entries(raw) -> list[dict]:
    """Stored entries as {text, saved_at}; anything malformed is dropped."""
    entries = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and normalize(item.get("text")).strip():
                entries.append({"text": normalize(item.get("text")),
                                "saved_at": str(item.get("saved_at") or "")})
    return entries


def add(entries: list[dict], text, limit, now: datetime | None = None) -> tuple[list[dict], bool]:
    """(new list, whether the text was added)."""
    body = normalize(text)
    if not body.strip() or any(entry["text"] == body for entry in entries):
        return entries, False
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return ([{"text": body, "saved_at": stamp}] + list(entries))[:clean_limit(limit)], True


def count_text(count: int) -> str:
    """Configuración, next to the trash button."""
    if count == 0:
        return "Sin textos guardados."
    return "1 texto guardado." if count == 1 else f"{count} textos guardados."


def label(entry: dict) -> str:
    """«19/11 14:05 · first line of the text» for the Historial menu."""
    stamp = str(entry.get("saved_at") or "")
    when = f"{stamp[8:10]}/{stamp[5:7]} {stamp[11:16]}" if len(stamp) >= 16 else ""
    first = next((line.strip() for line in entry["text"].split("\n") if line.strip()), "")
    if len(first) > LABEL_CHARS:
        first = first[:LABEL_CHARS - 1].rstrip() + "…"
    return f"{when} · {first}" if when else first
