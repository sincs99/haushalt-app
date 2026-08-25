from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    cors_origins: str = "http://localhost:5173"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
