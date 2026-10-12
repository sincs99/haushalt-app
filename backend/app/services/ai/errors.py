"""Fachliche Fehler des KI-Assistenten. Der Router übersetzt sie in HTTP-Antworten."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AiUsageInfo:
    """Token-Verbrauch eines Aufrufs (aus ``response.usage``)."""

    input_tokens: int
    output_tokens: int
    model: str


class AiError(Exception):
    """Basisklasse. ``usage`` ist gesetzt, wenn die API geantwortet hat (Kosten angefallen)."""

    def __init__(self, message: str = "", usage: AiUsageInfo | None = None):
        super().__init__(message or self.__class__.__name__)
        self.usage = usage


class AiNotConfigured(AiError):
    """Kein ``ANTHROPIC_API_KEY`` gesetzt."""


class AiDailyLimitReached(AiError):
    """Tageslimit des Haushalts ausgeschöpft."""


class AiUserDailyLimitReached(AiError):
    """Persönliches Tageslimit (über alle Haushalte) ausgeschöpft (PD-A2)."""


class AiBusy(AiError):
    """Zu viele gleichzeitige Aufrufe oder Rate-Limit beim Anbieter."""


class AiUnavailable(AiError):
    """Netzwerkfehler, Timeout oder Fehlerantwort des Anbieters."""


class AiRefused(AiError):
    """Das Modell (inkl. Fallback-Kette) hat die Anfrage abgelehnt (``stop_reason == "refusal"``)."""

    def __init__(self, usage: AiUsageInfo | None, category: str | None = None):
        super().__init__("Request refused", usage)
        self.category = category


class AiInvalidOutput(AiError):
    """Antwort passt nicht ins Schema (z. B. abgeschnitten bei ``max_tokens``)."""


class AiPlantNotRecognized(AiError):
    """Die Eingabe bezeichnet keine Pflanze."""
