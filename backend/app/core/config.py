"""Application settings loaded from the environment (Pydantic Settings)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://reverb:reverb@localhost:5432/reverb"
    secret_key: str = "change-me-in-local"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
