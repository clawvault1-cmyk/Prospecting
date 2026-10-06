import os

os.environ["APP_PASSWORD"] = "test-pass"
os.environ["APP_SECRET"] = "test-secret"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["SEARCH_PROVIDER"] = "mock"
os.environ["JOBS_SYNC"] = "1"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = ""

import pytest

from app.db import init_db
from app.jobs import stop_worker
from app.settings import get_settings


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    monkeypatch.setenv("JOBS_SYNC", "1")
    get_settings.cache_clear()
    init_db()
    yield
    stop_worker()
    get_settings.cache_clear()
