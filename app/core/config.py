from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


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


    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache
def get_settings():
    return Settings()
