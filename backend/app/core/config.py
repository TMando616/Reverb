"""環境変数から読み込むアプリケーション設定（Pydantic Settings）。"""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "production"]

_DEFAULT_SECRET_KEY = "change-me-in-local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 非同期エンジン用の PostgreSQL DSN（postgresql+asyncpg://）。design.md §4-4
    database_url: str = "postgresql+asyncpg://reverb:reverb@localhost:5432/reverb"
    # 今後の署名用途のために確保している値。オペークなセッショントークン自体は
    # sha256 でハッシュ化するだけ（design.md §4-1）。local 以外では必ず上書きする。
    secret_key: str = _DEFAULT_SECRET_KEY
    # 本番判定フラグ。Secure Cookie の管理は BFF 側の責務（design.md §12-1）。
    # このAPIは内部エラー文の非表示など、本番限定の挙動をこれで判定する。
    environment: Environment = "local"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _reject_default_secret_in_production(self) -> "Settings":
        # 既定値はリポジトリに入っている既知の文字列。本番で渡し忘れたときに
        # 黙って起動されるのが一番まずいので、起動時に落とす。
        if self.is_production and self.secret_key == _DEFAULT_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set when ENVIRONMENT=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
