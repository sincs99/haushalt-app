"""Schwärzt Tag-Tokens in Log-Meldungen.

Tag-Tokens stehen im URL-Pfad (``/api/tags/resolve/<token>``,
``/api/tags/<token>/execute``). uvicorns Access-Log und slowapis
„ratelimit exceeded“-Warnung schreiben den Pfad mit. Der Filter ersetzt den
Token durch ``***``, bevor die Meldung formatiert wird.
"""

import logging
import re

REDACTED = "***"
_TOKEN = r"[^/?#\s\"]+"
_PATTERNS = (
    (re.compile(rf"/api/tags/resolve/{_TOKEN}"), f"/api/tags/resolve/{REDACTED}"),
    (re.compile(rf"/api/tags/{_TOKEN}/execute"), f"/api/tags/{REDACTED}/execute"),
)


def redact_tag_tokens(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class TagTokenRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_tag_tokens(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_tag_tokens(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact_tag_tokens(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


# Logger, die Request-Pfade ausgeben
REDACTED_LOGGERS = ("uvicorn.access", "uvicorn.error", "slowapi")


def install_tag_token_redaction() -> None:
    for name in REDACTED_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, TagTokenRedactionFilter) for f in logger.filters):
            logger.addFilter(TagTokenRedactionFilter())
