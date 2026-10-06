"""Environment settings. Secrets come from the process environment or a local .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    app_password: str
    app_secret: str
    data_dir: Path
    llm_provider: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    openai_json_mode: bool
    anthropic_api_key: str
    anthropic_model: str
    tavily_api_key: str
    search_provider: str
    jobs_sync: bool
    request_timeout: float

    @property
    def llm_mode(self) -> str:
        choice = (self.llm_provider or "auto").strip().lower()
        if choice == "mock":
            return "mock"
        if choice == "anthropic":
            return "anthropic" if self.anthropic_api_key else "mock"
        if choice in {"openai", "openai-compatible", "xai"}:
            return "openai" if self.openai_api_key else "mock"
        if self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        return "mock"

    @property
    def search_mode(self) -> str:
        choice = (self.search_provider or "auto").strip().lower()
        if choice == "mock":
            return "mock"
        if choice == "tavily":
            return "tavily" if self.tavily_api_key else "mock"
        return "tavily" if self.tavily_api_key else "mock"

    @property
    def mock_mode(self) -> bool:
        return self.llm_mode == "mock" and self.search_mode == "mock"


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    data_dir = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).expanduser()
    if not data_dir.is_absolute():
        data_dir = (ROOT / data_dir).resolve()
    password = os.environ.get("APP_PASSWORD", "")
    secret = os.environ.get("APP_SECRET") or password or "dev-secret-change-me"
    json_mode = os.environ.get("OPENAI_JSON_MODE", "true").strip().lower() not in {"0", "false", "no"}
    return Settings(
        app_password=password,
        app_secret=secret,
        data_dir=data_dir,
        llm_provider=os.environ.get("LLM_PROVIDER", "auto"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        openai_json_mode=json_mode,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
        search_provider=os.environ.get("SEARCH_PROVIDER", "auto"),
        jobs_sync=os.environ.get("JOBS_SYNC", "").strip().lower() in {"1", "true", "yes"},
        request_timeout=float(os.environ.get("HTTP_TIMEOUT", "45")),
    )
