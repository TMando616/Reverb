"""Application settings loaded from the environment (Pydantic Settings)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL DSN for the async engine (postgresql+asyncpg://). design.md §4-4
    database_url: str = "postgresql+asyncpg://reverb:reverb@localhost:5432/reverb"
    # Reserved for signing needs in later specs; the opaque session token itself
    # is only sha256-hashed (design.md §4-1). Must be overridden outside local.
    secret_key: str = "change-me-in-local"
    # Production toggle. The BFF owns Secure cookies (design.md §12-1); the API
    # uses this to decide prod-only behaviour such as hiding internal error text.
    environment: Environment = "local"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
