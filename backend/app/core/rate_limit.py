"""Zentrales Rate-Limiting-Modul (slowapi).

Eigenes Modul, um Circular Imports zwischen main.py und Routern zu vermeiden.

Proxy-Hinweis:
    ``get_remote_address`` liest ``request.client.host``.  In Produktion
    läuft uvicorn hinter einem Reverse-Proxy (nginx / Traefik) und wird
    mit ``--proxy-headers`` gestartet.  Uvicorn schreibt dann
    ``request.client.host`` automatisch aus dem ``X-Forwarded-For``-Header
    um, sodass ``get_remote_address`` die *echte* Client-IP zurückgibt —
    ohne dass wir den Header manuell parsen müssen.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Storage: ``memory://`` (ein Prozess) oder Redis (``RATE_LIMIT_STORAGE_URI``), damit
# mehrere Worker dieselben Zähler sehen. Fällt Redis aus, zählt der Prozess im
# Speicher weiter (in_memory_fallback), statt alle Anfragen abzulehnen.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.rate_limit_storage_uri.strip() or "memory://",
    in_memory_fallback_enabled=True,
)
