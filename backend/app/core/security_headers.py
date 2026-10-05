"""HTTP-Security-Header für alle API-Responses.

Reine ASGI-Middleware (kein ``BaseHTTPMiddleware``), damit Streaming-Responses
(FileResponse) und der Socket.IO-Mount unverändert durchgereicht werden.
WebSocket-Verbindungen werden nicht angefasst.

Die API liefert ausschliesslich JSON bzw. Datei-Downloads aus — nie HTML, das
der Browser rendern soll. Deshalb eine maximal restriktive CSP
(``default-src 'none'``). Die CSP der SPA selbst setzt nginx
(``frontend/nginx/security-headers.conf``).

HSTS wird bewusst NICHT hier gesetzt: TLS terminiert vor dem Frontend-nginx
(Nginx Proxy Manager), dort gehört der Header hin.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

# Swagger-UI / ReDoc laden Skripte von einem CDN — dort keine API-CSP setzen.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

_BASE_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        extra: list[tuple[bytes, bytes]] = list(_BASE_HEADERS)
        if not path.startswith(_DOCS_PATHS):
            extra.append((b"content-security-policy", API_CSP.encode()))
        # Token-Responses dürfen in keinem Cache (Browser, Proxy) landen
        no_store = path.startswith("/api/auth/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in extra:
                    if name not in present:
                        headers.append((name, value))
                if no_store:
                    headers = [(n, v) for n, v in headers if n.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
