from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from urllib.parse import urlparse


class Settings(BaseSettings):
    app_name: str = "Crypto Bot SaaS"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/cryptobot"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change_this"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    encryption_key: str
    cors_origins: str = "http://localhost:3000"


    @model_validator(mode="after")
    def enforce_production_security(self):
        if self.app_env.lower() not in {"production", "prod"}:
            return self
        if self.debug:
            raise ValueError("DEBUG must be disabled in production")
        if not self.jwt_secret or self.jwt_secret == "change_this" or len(self.jwt_secret) < 32:
            raise ValueError("Production JWT secret must be unique and at least 32 characters")
        if self.jwt_algorithm != "HS256":
            raise ValueError("Unexpected JWT algorithm; review token signing configuration")
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        if not origins or any(
            origin == "*" or urlparse(origin).scheme != "https"
            or not urlparse(origin).hostname or urlparse(origin).username
            for origin in origins
        ):
            raise ValueError("Production CORS must specify explicit HTTPS origins")
        if self.database_url.startswith("postgresql") and (
            "postgres:postgres@" in self.database_url or "localhost" in self.database_url
        ):
            raise ValueError("Production database must not use development credentials or localhost")
        return self

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache
def get_settings():
    return Settings()
