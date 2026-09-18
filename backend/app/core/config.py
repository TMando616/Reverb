"""環境変数から読み込むアプリケーション設定（Pydantic Settings）。"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 非同期エンジン用の PostgreSQL DSN（postgresql+asyncpg://）。design.md §4-4
    database_url: str = "postgresql+asyncpg://reverb:reverb@localhost:5432/reverb"
    # 今後の署名用途のために確保している値。オペークなセッショントークン自体は
    # sha256 でハッシュ化するだけ（design.md §4-1）。local 以外では必ず上書きする。
    secret_key: str = "change-me-in-local"
    # 本番判定フラグ。Secure Cookie の管理は BFF 側の責務（design.md §12-1）。
    # このAPIは内部エラー文の非表示など、本番限定の挙動をこれで判定する。
    environment: Environment = "local"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
