"""Load the project .env regardless of the caller's working directory."""

from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Mapping

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(ValueError):
    pass


def positive_integer(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be a positive integer.") from None
    if value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer.")
    return value


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str
    max_calls: int
    window_seconds: int
    timeout_seconds: int
    max_output_tokens: int
    search_timeout: int
    search_max_results: int
    rate_limit_db: Path

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "Settings":
        if env is None:
            load_dotenv(PROJECT_ROOT / ".env", override=False)
            env = os.environ
        api_key = env.get("OPENAI_API_KEY", "").strip()
        if not api_key or api_key == "your_openai_api_key_here":
            raise ConfigurationError("Set OPENAI_API_KEY in the project .env file.")
        model = env.get("LLM_MODEL", "gpt-4o-mini").strip()
        if model.startswith("openai/"):
            model = model.removeprefix("openai/")
        if not model or "/" in model or any(c.isspace() for c in model):
            raise ConfigurationError("LLM_MODEL must be an OpenAI model name.")
        db = Path(env.get("RATE_LIMIT_DB", ".runtime/rate_limit.sqlite3"))
        if not db.is_absolute():
            db = PROJECT_ROOT / db
        return cls(
            api_key=api_key,
            model=model,
            max_calls=positive_integer(env, "RATE_LIMIT_MAX_CALLS", 20),
            window_seconds=positive_integer(env, "RATE_LIMIT_WINDOW_SECONDS", 60),
            timeout_seconds=positive_integer(env, "LLM_TIMEOUT_SECONDS", 45),
            max_output_tokens=positive_integer(env, "LLM_MAX_OUTPUT_TOKENS", 1500),
            search_timeout=positive_integer(env, "SEARCH_TIMEOUT_SECONDS", 15),
            search_max_results=min(positive_integer(env, "SEARCH_MAX_RESULTS", 5), 10),
            rate_limit_db=db,
        )
