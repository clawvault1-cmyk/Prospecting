"""Search and chat providers. Mock is the default when API keys are absent."""

from app.providers.llm import get_llm
from app.providers.search import get_search

__all__ = ["get_llm", "get_search"]
