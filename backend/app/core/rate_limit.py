"""Zentrales Rate-Limiting-Modul (slowapi).

Eigenes Modul, um Circular Imports zwischen main.py und Routern zu vermeiden.

Proxy-Hinweis:
    ``get_remote_address`` liest ``request.client.host``.  In Produktion
    läuft die Kette Client → Nginx Proxy Manager → Frontend-Nginx → uvicorn.

    - Das Frontend-Nginx (``frontend/nginx.conf``) ermittelt per
      ``ngx_http_realip_module`` die Client-IP aus dem *letzten*, von NPM
      angehängten ``X-Forwarded-For``-Eintrag (``real_ip_recursive off``) und
      *überschreibt* den Header mit genau dieser einen IP.  Vom Client
      gefälschte Einträge erreichen das Backend nicht.
    - uvicorn läuft mit ``--proxy-headers`` und ``--forwarded-allow-ips`` auf
      private Netze beschränkt (``backend/Dockerfile``) und setzt
      ``request.client.host`` auf den rechtesten nicht-vertrauenswürdigen
      Hop.  Niemals ``'*'`` verwenden: dann gewinnt der *linkeste*,
      client-kontrollierte Eintrag und jeder Request bekommt einen frischen
      Bucket (Brute-Force auf Login möglich).

    Siehe ``tests/test_rate_limit_proxy.py`` und ``docs/deployment.md``.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
