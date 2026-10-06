"""Client-Factory und strukturierter Aufruf der Claude API.

Alle Features gehen durch ``call_structured``: ein einzelner, nicht gestreamter
Request mit ``client.beta.messages.parse()``. Das Pydantic-Modell wird vom SDK als
JSON-Schema in ``output_config.format`` geschickt und die Antwort dagegen validiert —
es wird kein Freitext geparst.

- Modell ``claude-opus-5-5``; Denken ist dort immer an, die Tiefe steuert
  ``output_config.effort`` (kein ``thinking``-Parameter, kein ``budget_tokens``).
- Serverseitige Fallbacks (``fallbacks="default"``): lehnt ein Sicherheits-Klassifikator
  ab, beantwortet die API die Anfrage im selben Aufruf mit dem empfohlenen Ersatzmodell.
  Lehnt auch dieses ab, kommt ``stop_reason == "refusal"`` → ``AiRefused``.
- Der Schlüssel kommt nur aus ``settings.anthropic_api_key`` (``ANTHROPIC_API_KEY``)
  und wird explizit übergeben, damit das SDK keine anderen Quellen (Profile o. ä.) nutzt.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Generic, Literal, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.services.ai.errors import (
    AiBusy,
    AiInvalidOutput,
    AiNotConfigured,
    AiRefused,
    AiUnavailable,
    AiUsageInfo,
)

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Das SDK wiederholt 408/409/429/5xx und Verbindungsfehler selbst — einmal reicht,
# sonst wartet der Nutzer bis zu timeout × (max_retries + 1)
MAX_RETRIES = 1

Effort = Literal["low", "medium", "high"]
T = TypeVar("T", bound=BaseModel)

# Jeder Aufruf belegt einen Worker-Thread (sync Endpoint) für mehrere Sekunden.
# Begrenzen, damit KI-Anfragen den Rest der App nicht ausbremsen.
_slots = threading.BoundedSemaphore(max(1, settings.ai_max_concurrent_requests))


@lru_cache(maxsize=1)
def _build_client(api_key: str, timeout: float) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=MAX_RETRIES)


def get_client() -> anthropic.Anthropic:
    """Liefert den (gecachten) SDK-Client oder wirft ``AiNotConfigured``."""
    if not settings.ai_available:
        raise AiNotConfigured("ANTHROPIC_API_KEY is not set")
    return _build_client(settings.anthropic_api_key.strip(), settings.ai_request_timeout_seconds)


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    output: T
    usage: AiUsageInfo


def call_structured(
    *,
    system: str,
    user_content: str,
    output_model: type[T],
    effort: Effort,
    max_tokens: int,
) -> StructuredResult[T]:
    """Ein Request, Antwort validiert als ``output_model``. Wirft nur ``AiError``-Unterklassen."""
    client = get_client()
    if not _slots.acquire(blocking=False):
        raise AiBusy("Too many concurrent AI requests")
    try:
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_config={"effort": effort},
            output_format=output_model,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except ValidationError as exc:
        # JSON passt nicht ins Schema (praktisch nur bei Abbruch durch max_tokens)
        logger.warning("AI output failed schema validation: %s", exc.error_count())
        raise AiInvalidOutput("Output did not match schema")
    except anthropic.RateLimitError as exc:
        logger.warning("AI rate limited by provider (request_id=%s)", exc.request_id)
        raise AiBusy("Provider rate limit")
    except anthropic.APIConnectionError as exc:  # inkl. APITimeoutError
        logger.warning("AI connection error: %s", type(exc).__name__)
        raise AiUnavailable("Connection error")
    except anthropic.APIStatusError as exc:
        # 401/403 (Schlüssel), 400 (Request), 5xx (nach Retry) — Details nur ins Log
        logger.error("AI API error status=%s request_id=%s", exc.status_code, exc.request_id)
        raise AiUnavailable(f"Provider error {exc.status_code}")
    finally:
        _slots.release()

    usage = AiUsageInfo(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        model=response.model,
    )
    # stop_reason vor dem Inhalt prüfen: eine Ablehnung hat keinen (vollständigen) Inhalt
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        logger.info("AI request refused (category=%s, model=%s)", category, response.model)
        raise AiRefused(usage, category)

    parsed = response.parsed_output
    if response.stop_reason == "max_tokens" or parsed is None:
        logger.warning("AI output incomplete (stop_reason=%s)", response.stop_reason)
        raise AiInvalidOutput("Output incomplete", usage)

    logger.info(
        "AI call ok model=%s input_tokens=%s output_tokens=%s",
        usage.model,
        usage.input_tokens,
        usage.output_tokens,
    )
    return StructuredResult(output=parsed, usage=usage)
