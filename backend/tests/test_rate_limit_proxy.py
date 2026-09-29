"""Tests: Rate-Limiter keyt auf die echte Client-IP — nicht auf gefälschte XFF-Einträge.

Produktionskette: Client → Nginx Proxy Manager → Frontend-Nginx → uvicorn.

Die Tests schicken Requests durch uvicorns echte ``ProxyHeadersMiddleware``
mit genau der ``--forwarded-allow-ips``-Konfiguration aus ``backend/Dockerfile``
und simulieren als Verbindungs-Peer das Frontend-Nginx im Docker-Netzwerk.
Der Limiter nutzt dabei seine echte ``key_func`` (``get_remote_address``).

Zusätzlich wird ``frontend/nginx.conf`` geprüft: Dort wird die Client-IP per
``ngx_http_realip_module`` aus dem *letzten* (von NPM angehängten) XFF-Eintrag
gewonnen und der Header mit genau dieser IP überschrieben.  Beide Ebenen
schliessen den Bypass jeweils für sich.
"""

import re
import shlex
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.rate_limit import limiter
from app.database import get_db
from app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "backend" / "Dockerfile"
_NGINX_CONF = _REPO_ROOT / "frontend" / "nginx.conf"

# IP des Frontend-Nginx-Containers im Docker-Netzwerk (Verbindungs-Peer)
_NGINX_PEER = ("172.18.0.3", 40000)
# IP von Nginx Proxy Manager im Docker-Netzwerk
_NPM_IP = "172.19.0.2"

_LOGIN_DATA = {"username": "nobody@example.com", "password": "wrong"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _forwarded_allow_ips() -> str:
    """Liest den ``--forwarded-allow-ips``-Wert aus dem Backend-Dockerfile."""
    text = _DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"--forwarded-allow-ips[= ](\S+?)\"\]", text)
    assert match, "--forwarded-allow-ips nicht im Dockerfile-CMD gefunden"
    (value,) = shlex.split(match.group(1))
    return value


def _nginx_directives() -> list[str]:
    """Nginx-Direktiven ohne Kommentare, whitespace-normalisiert."""
    lines = _NGINX_CONF.read_text(encoding="utf-8").splitlines()
    return [" ".join(line.split("#", 1)[0].split()) for line in lines if line.split("#", 1)[0].strip()]


def _login(client: TestClient, xff: str):
    return client.post("/api/auth/login", data=_LOGIN_DATA, headers={"X-Forwarded-For": xff})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_limiter():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


@pytest.fixture()
def proxied_client(db):
    """TestClient hinter uvicorns ProxyHeadersMiddleware (Produktions-Config)."""
    app.dependency_overrides[get_db] = lambda: db
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=_forwarded_allow_ips())
    with TestClient(wrapped, client=_NGINX_PEER) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Backend-Ebene (uvicorn --forwarded-allow-ips)
# ---------------------------------------------------------------------------


class TestUvicornProxyHeaders:
    def test_dockerfile_does_not_trust_all_forwarders(self):
        assert _forwarded_allow_ips() != "*", (
            "'*' lässt uvicorn den linkesten, client-kontrollierten XFF-Eintrag nutzen"
        )

    def test_spoofed_leftmost_xff_does_not_yield_fresh_bucket(self, proxied_client):
        """Angreifer rotiert den linkesten XFF-Eintrag — bleibt trotzdem im selben Bucket.

        Header wie bei der alten, anhängenden Nginx-Config:
        ``<gefälscht>, <echte Client-IP (von NPM)>, <NPM-IP (vom Frontend-Nginx)>``.
        """
        for i in range(5):
            resp = _login(proxied_client, f"198.51.100.{i}, 203.0.113.7, {_NPM_IP}")
            assert resp.status_code != 429, f"Request {i + 1} darf noch nicht limitiert sein"

        resp = _login(proxied_client, f"198.51.100.99, 203.0.113.7, {_NPM_IP}")
        assert resp.status_code == 429, "Gefälschter linkester XFF-Eintrag darf keinen neuen Bucket öffnen"

    def test_lan_client_with_private_ip_is_keyed_on_its_ip(self, proxied_client):
        """Frontend-Nginx sendet genau eine IP — auch private LAN-IPs werden korrekt genutzt."""
        for _ in range(5):
            assert _login(proxied_client, "192.168.1.50").status_code != 429
        assert _login(proxied_client, "192.168.1.50").status_code == 429
        assert _login(proxied_client, "192.168.1.51").status_code != 429

    def test_different_ips_get_separate_buckets(self, proxied_client):
        """6. Request von IP A → 429, gleichzeitig IP B → kein 429."""
        for i in range(5):
            assert _login(proxied_client, "203.0.113.1").status_code != 429, (
                f"Request {i + 1} von Client A sollte nicht limitiert sein"
            )
        assert _login(proxied_client, "203.0.113.1").status_code == 429
        assert _login(proxied_client, "203.0.113.2").status_code != 429

    def test_rate_limit_returns_structured_error(self, proxied_client):
        """429-Response enthält strukturierten Error-Code RATE_LIMITED."""
        for _ in range(5):
            _login(proxied_client, "203.0.113.99")

        resp = _login(proxied_client, "203.0.113.99")
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# Nginx-Ebene (frontend/nginx.conf)
# ---------------------------------------------------------------------------


class TestFrontendNginxConfig:
    """Statische Prüfung der Nginx-Config.

    Mit ``real_ip_header X-Forwarded-For`` + ``real_ip_recursive off`` ersetzt
    Nginx ``$remote_addr`` durch den *letzten* XFF-Eintrag — den, den NPM
    angehängt hat.  Beispiel: Client sendet ``X-Forwarded-For: 1.2.3.4``,
    NPM leitet ``1.2.3.4, 203.0.113.7`` weiter → ``$remote_addr = 203.0.113.7``.
    Da der Header anschliessend mit ``$remote_addr`` überschrieben wird,
    erreicht ``1.2.3.4`` das Backend nie.
    """

    def test_realip_takes_last_hop_only(self):
        directives = _nginx_directives()
        assert "real_ip_header X-Forwarded-For;" in directives
        assert "real_ip_recursive off;" in directives
        assert any(d.startswith("set_real_ip_from ") for d in directives)

    def test_xff_is_overwritten_not_appended(self):
        directives = _nginx_directives()
        xff = [d for d in directives if d.startswith("proxy_set_header X-Forwarded-For ")]
        assert xff, "X-Forwarded-For wird nicht gesetzt"
        assert all(d == "proxy_set_header X-Forwarded-For $remote_addr;" for d in xff), xff
