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

    # ------------------------------------------------------------------
    # Tarife und Abrechnung (SaaS-Betrieb). BILLING_ENABLED=false (Standard,
    # Self-Hosting): jeder Haushalt hat alle Funktionen mit den globalen Limits
    # oben (HOUSEHOLD_STORAGE_QUOTA_MB, AI_DAILY_LIMIT_PER_HOUSEHOLD).
    # BILLING_ENABLED=true: Haushalte haben einen Tarif (free/premium) mit den
    # Limits unten; Premium kommt über Stripe, später App-Store-Abos oder
    # manuell über den Plattform-Admin.
    # ------------------------------------------------------------------
    billing_enabled: bool = False
    # Limits des Gratis-Tarifs. 0 bei max_members = unbegrenzt; 0 bei ai = KI nicht enthalten
    plan_free_max_members: int = 3
    plan_free_storage_mb: int = 200
    plan_free_ai_daily_limit: int = 0
    # Limits des Premium-Tarifs
    plan_premium_max_members: int = 0
    plan_premium_storage_mb: int = 5120
    plan_premium_ai_daily_limit: int = 50
    # Karenz nach Ablauf einer bezahlten Periode (Zahlungsverzug), bevor der Haushalt
    # auf den Gratis-Tarif fällt
    plan_grace_days: int = 3

    # Stripe (Web-Zahlung). Leer = kein Checkout, Tarife nur manuell/App-Store.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_monthly: str = ""
    stripe_price_id_yearly: str = ""
    stripe_api_base: str = "https://api.stripe.com"
    # Pfade im Frontend, zu denen Stripe nach dem Checkout zurückleitet
    billing_success_path: str = "/household?billing=success"
    billing_cancel_path: str = "/household?billing=cancel"

    # ------------------------------------------------------------------
    # Betrieb mit mehreren Prozessen (uvicorn --workers > 1 oder mehrere Container)
    #
    # Beide Werte zeigen dann auf denselben Redis. Ohne Redis läuft genau ein
    # Prozess: Rate-Limits im Speicher, Socket.IO ohne Message-Queue.
    # ------------------------------------------------------------------
    # slowapi/limits-Storage, z. B. redis://redis:6379/0
    rate_limit_storage_uri: str = "memory://"
    # python-socketio Message-Queue, z. B. redis://redis:6379/1 (leer = ein Prozess)
    socketio_message_queue: str = ""

    # Fehler-Monitoring (optional). Leer = aus. Es werden keine Inhalte der Haushalte
    # und keine Personendaten mitgeschickt (send_default_pii=False).
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0

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
    def stripe_configured(self) -> bool:
        return bool(
            self.stripe_secret_key.strip()
            and self.stripe_webhook_secret.strip()
            and (self.stripe_price_id_monthly.strip() or self.stripe_price_id_yearly.strip())
        )

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
