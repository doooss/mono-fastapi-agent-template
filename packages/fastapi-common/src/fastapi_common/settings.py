"""Env shared by every app. Apps subclass `BaseAppSettings` and add their own keys."""

import os
from enum import StrEnum
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DOCS_PASSWORD = "admin"  # noqa: S105 — rejected outside local by _guard_deploy_env

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class AppEnv(StrEnum):
    LOCAL = "local"
    DEV = "dev"
    QA = "qa"
    PRODUCTION = "production"


def parse_allowed_origins(value: str) -> list[str]:
    """`ALLOWED_ORIGINS` (comma list) -> origin list. Empty items dropped."""
    return [origin.strip() for origin in value.split(",") if origin.strip()]


class BaseAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        # Same convention as the NestJS template: `.env.<APP_ENV>` in the app directory.
        env_file=f".env.{os.getenv('APP_ENV', AppEnv.LOCAL.value)}",
        extra="ignore",
        # `PORT=` means unset, so the default applies.
        env_ignore_empty=True,
    )

    APP_ENV: AppEnv = AppEnv.LOCAL
    SERVICE_NAME: str = "api"
    LOG_LEVEL: LogLevel | None = None

    # CORS. production must list origins explicitly ('*' rejected).
    ALLOWED_ORIGINS: str = "*"

    # Basic auth for /api (Swagger) · /api-json · /docs (ReDoc).
    DOCS_USER: str = "admin"
    DOCS_PASSWORD: SecretStr = SecretStr(DEFAULT_DOCS_PASSWORD)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV is AppEnv.PRODUCTION

    @property
    def allowed_origins(self) -> list[str]:
        return parse_allowed_origins(self.ALLOWED_ORIGINS)

    @property
    def log_level(self) -> LogLevel:
        return self.LOG_LEVEL or ("INFO" if self.is_production else "DEBUG")

    @model_validator(mode="after")
    def _guard_deploy_env(self) -> Self:
        errors: list[str] = []
        if (
            self.APP_ENV is not AppEnv.LOCAL
            and self.DOCS_PASSWORD.get_secret_value() == DEFAULT_DOCS_PASSWORD
        ):
            errors.append(
                f"DOCS_PASSWORD: {self.APP_ENV} 에서는 기본값(admin)이 아닌 값이어야 한다"
            )
        if self.is_production and (not self.allowed_origins or "*" in self.allowed_origins):
            errors.append('ALLOWED_ORIGINS: production 에서는 명시해야 한다 (comma list, "*" 불가)')
        if errors:
            raise ValueError("; ".join(errors))
        return self
