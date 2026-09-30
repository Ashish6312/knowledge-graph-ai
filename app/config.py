import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_VARIABLES = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


class ConfigError(Exception):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: SecretStr
    neo4j_database: str = "neo4j"

    query_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_result_rows: int = Field(default=100, ge=1, le=1000)

    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    anthropic_workspace_id: str | None = None

    @field_validator("neo4j_uri")
    @classmethod
    def _check_uri_scheme(cls, value: str) -> str:
        if not value.startswith(("bolt://", "bolt+s://", "neo4j://", "neo4j+s://")):
            raise ValueError("must start with bolt://, bolt+s://, neo4j:// or neo4j+s://")
        return value


def load_settings(env_file: Path | None = PROJECT_ROOT / ".env") -> Settings:
    if env_file is not None and env_file.exists():
        load_dotenv(env_file, override=False)

    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if missing:
        raise ConfigError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in."
        )

    optional = {
        "neo4j_database": os.environ.get("NEO4J_DATABASE"),
        "query_timeout_seconds": os.environ.get("QUERY_TIMEOUT_SECONDS"),
        "max_result_rows": os.environ.get("MAX_RESULT_ROWS"),
        "llm_model": os.environ.get("LLM_MODEL"),
        "anthropic_workspace_id": os.environ.get("ANTHROPIC_WORKSPACE_ID"),
    }
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    try:
        return Settings.model_validate(
            {
                "neo4j_uri": os.environ["NEO4J_URI"],
                "neo4j_user": os.environ["NEO4J_USER"],
                "neo4j_password": os.environ["NEO4J_PASSWORD"],
                "anthropic_api_key": api_key or None,
                **{key: value for key, value in optional.items() if value},
            }
        )
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"Invalid configuration: {problems}") from exc
