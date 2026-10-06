"""Hilfsfunktionen, um Modell-Texte in die Grenzen der App-Schemas zu bringen."""

from __future__ import annotations


def clip(text: str | None, max_len: int) -> str:
    """Whitespace normalisieren und auf ``max_len`` Zeichen kürzen."""
    if not text:
        return ""
    return " ".join(text.split())[:max_len].rstrip()


def clip_or_none(text: str | None, max_len: int) -> str | None:
    return clip(text, max_len) or None


def in_range(value: int | None, low: int, high: int) -> int | None:
    if value is None or value < low or value > high:
        return None
    return value
