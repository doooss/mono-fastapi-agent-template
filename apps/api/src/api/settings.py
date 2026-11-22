from pathlib import Path
from tempfile import gettempdir
from typing import Literal

from pydantic import Field, SecretStr

from fastapi_common import BaseAppSettings

BackendName = Literal["messages", "agent_sdk", "managed"]


class Settings(BaseAppSettings):
    # SQLAlchemy async URL. Postgres: postgresql+asyncpg://… (add asyncpg).
    DATABASE_URL: str = "sqlite+aiosqlite:///./database.sqlite"
    # Run `alembic upgrade head` at startup. Default = not production (single-instance SQLite).
    DB_MIGRATE_ON_START: bool | None = None

    # Read here (not by the SDKs from os.environ) so `.env.<APP_ENV>` works for every backend.
    ANTHROPIC_API_KEY: SecretStr | None = None
    AGENT_BACKEND: BackendName = "messages"
    AGENT_MODEL: str = "claude-opus-5-5"
    SUBAGENT_MODEL: str = "claude-haiku-5-5"
    MANAGED_ENVIRONMENT_NAME: str = "agent-template"
    # One run (subagents included) is cut at this; a `running` row older than twice this is
    # treated as left behind by a dead process and no longer blocks its session.
    RUN_TIMEOUT_SECONDS: int = Field(default=600, ge=10)
    AGENT_SDK_WORKDIR: Path = Path(gettempdir()) / "agent-sdk"

    @property
    def migrate_on_start(self) -> bool:
        if self.DB_MIGRATE_ON_START is None:
            return not self.is_production
        return self.DB_MIGRATE_ON_START

    @property
    def anthropic_api_key(self) -> str | None:
        return self.ANTHROPIC_API_KEY.get_secret_value() if self.ANTHROPIC_API_KEY else None
