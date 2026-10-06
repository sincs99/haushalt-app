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

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def refresh_cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.environment == "production"

    class Config:
        env_file = ".env"


settings = Settings()
