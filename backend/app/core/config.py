from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    cors_origins: str = "http://localhost:5173"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    refresh_token_reuse_grace_seconds: int = 30
    environment: str = "development"
    # Secure-Flag des Refresh-Token-Cookies (casa_rt). None = automatisch:
    # True in production (TLS am Proxy), False in development (http://localhost).
    # Nur explizit setzen, wenn Produktion ohne HTTPS getestet wird (AUTH_COOKIE_SECURE=false).
    auth_cookie_secure: bool | None = None
    # Speicher-Quota pro Haushalt über alle hochgeladenen Dateien (MB)
    household_storage_quota_mb: int = 1024
    # Web Push (VAPID). Leer = Push deaktiviert. Generieren: python -m scripts.generate_vapid_keys
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"
    # KI-Assistent (optional). Leer = deaktiviert, die App läuft unverändert.
    # Der Schlüssel bleibt im Backend; das Frontend ruft den Anbieter nie direkt.
    anthropic_api_key: str = ""
    # Kostenschutz: Aufrufe pro Haushalt und Tag (UTC), zusätzlich zum IP-Limit
    ai_daily_limit_per_household: int = 50
    # Timeout pro API-Versuch in Sekunden; das SDK wiederholt höchstens einmal
    ai_request_timeout_seconds: float = 90.0
    # Gleichzeitige KI-Aufrufe im Prozess (jeder belegt einen Worker-Thread)
    ai_max_concurrent_requests: int = 4

    # ------------------------------------------------------------------
    # E-Mail (Passwort zurücksetzen, E-Mail-Verifizierung)
    #
    # MAIL_BACKEND: "auto" (SMTP, wenn SMTP_HOST gesetzt ist; sonst in der
    # Entwicklung Konsole, in Produktion aus), "smtp", "console" oder "off".
    # Ohne Versand bleiben die Funktionen ausgeblendet; die App läuft unverändert.
    # ------------------------------------------------------------------
    mail_backend: str = "auto"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # "starttls" (Port 587), "ssl" (Port 465) oder "none" (nur lokale Relays)
    smtp_tls: str = "starttls"
    smtp_timeout_seconds: float = 20.0
    mail_from: str = "Haushalt App <noreply@example.com>"
    # Öffentliche Adresse der App für Links in E-Mails (z. B. https://casa.example.com).
    # Leer = erster Eintrag aus CORS_ORIGINS.
    app_base_url: str = ""
    password_reset_token_minutes: int = 60
    email_verification_token_hours: int = 48

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def refresh_cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.environment == "production"

    @property
    def ai_available(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def effective_mail_backend(self) -> str:
        backend = self.mail_backend.strip().lower()
        if backend != "auto":
            return backend
        if self.smtp_host.strip():
            return "smtp"
        return "console" if self.environment != "production" else "off"

    @property
    def mail_enabled(self) -> bool:
        return self.effective_mail_backend in ("smtp", "console")

    @property
    def public_base_url(self) -> str:
        base = self.app_base_url.strip()
        if not base:
            origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
            base = origins[0] if origins else "http://localhost:5173"
        return base.rstrip("/")

    class Config:
        env_file = ".env"


settings = Settings()
