from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./vote.db"
    secret_key: str = "dev-secret-change-me"
    admin_username: str = "admin"
    admin_password: str = "admin123"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    media_dir: str = "./uploads"
    frontend_dist: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-northeast-2"
    s3_bucket: str | None = None
    s3_key_prefix: str = "vote"
    cloudfront_url: str | None = None
    access_token_expire_minutes: int = 60 * 24
    seed_mock_data: bool | None = None
    redis_url: str | None = None
    auth_mode: str = "both"  # local | oidc | both
    keycloak_issuer: str | None = None
    keycloak_client_id: str | None = None
    # App access role (not a global poll superadmin). Empty = any valid company token.
    keycloak_admin_role: str = "vote-admin"

    @property
    def should_seed_mock_data(self) -> bool:
        if self.seed_mock_data is not None:
            return self.seed_mock_data
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def s3_enabled(self) -> bool:
        return bool(
            self.s3_bucket
            and self.aws_access_key_id
            and self.aws_secret_access_key
            and self.cloudfront_url
        )

    @property
    def media_path(self) -> Path:
        return Path(self.media_dir)

    @property
    def keycloak_enabled(self) -> bool:
        return bool(self.keycloak_issuer and self.keycloak_client_id)

    @property
    def frontend_dist_path(self) -> Path | None:
        if not self.frontend_dist:
            return None
        return Path(self.frontend_dist)


@lru_cache
def get_settings() -> Settings:
    return Settings()
