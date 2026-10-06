from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    cors_origins: str = "http://localhost:5173"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    refresh_token_reuse_grace_seconds: int = 30
    environment: str = "development"
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

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def ai_available(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    class Config:
        env_file = ".env"


settings = Settings()
