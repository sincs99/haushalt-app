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

limiter = Limiter(key_func=get_remote_address)
