from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Classroom Assessment Platform"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://classroom:classroom@localhost:5433/classroom_assessment"
    web_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000/api/v1"
    jwt_secret: str = "development-only-change-me"
    access_token_expire_minutes: int = 480
    allow_dev_submission: bool = True
    seed_demo_password: str = ""

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[2] / ".env", ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_base_url.split(",") if origin.strip()]

    def validate_runtime(self) -> None:
        if self.app_env.lower() in {"production", "prod"}:
            if self.jwt_secret == "development-only-change-me" or len(self.jwt_secret) < 32:
                raise RuntimeError("JWT_SECRET must be a random value of at least 32 characters in production")
            if self.allow_dev_submission:
                raise RuntimeError("ALLOW_DEV_SUBMISSION must be false in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
