"""Web research. Tavily is the first live provider; MockSearch keeps the demo offline."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Callable, Protocol

import httpx

from app.config_loader import research_config
from app.settings import Settings, get_settings

Post = Callable[[dict, dict], dict]


class SearchProvider(Protocol):
    name: str

    def search(self, company: dict) -> list[dict]: ...


class TavilySearch:
    name = "tavily"
    url = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout: float = 45, post: Post | None = None, today: date | None = None):
        self.api_key = api_key
        self.timeout = timeout
        self.post = post or _http_post
        self.today = today or date.today()

    def search(self, company: dict) -> list[dict]:
        config = research_config()
        start = (self.today - timedelta(days=int(config.get("window_days") or 548))).isoformat()
        fields = {
            "company": company.get("name") or "",
            "facility_city": company.get("facility_city") or company.get("city") or "Ohio",
            "state": company.get("state") or "Ohio",
            "website": company.get("website") or "",
        }
        found: list[dict] = []
        seen: set[str] = set()
        errors: list[str] = []
        for spec in config.get("queries") or []:
            query = spec["template"].format(**fields)
            body = {
                "query": query,
                "topic": spec.get("topic") or "general",
                "search_depth": config.get("search_depth") or "advanced",
                "max_results": int(config.get("max_results") or 4),
                "include_answer": False,
                "include_raw_content": False,
            }
            if spec.get("time_boxed"):
                body["start_date"] = start
            try:
                payload = self.post(
                    body,
                    {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                )
            except Exception as exc:  # one bad query should not drop the rest
                errors.append(f"{spec.get('id')}: {exc}")
                continue
            for result in payload.get("results") or []:
                url = (result.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                found.append(
                    {
                        "query_id": spec.get("id") or "",
                        "query": query,
                        "title": (result.get("title") or "")[:300],
                        "url": url,
                        "snippet": (result.get("content") or "")[:2000],
                        "published": result.get("published_date") or "",
                    }
                )
        if not found and errors:
            raise RuntimeError("Tavily search failed. " + "; ".join(errors))
        return found


class MockSearch:
    """Deterministic snippets so the fact-check gate has something real to match."""

    name = "mock"

    def search(self, company: dict) -> list[dict]:
        name = company.get("name") or "The company"
        city = company.get("facility_city") or company.get("city") or "Ohio"
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "company"
        base = f"https://example.com/mock/{slug}"
        sources = [
            {
                "query_id": "news",
                "query": f"{name} expansion",
                "title": f"{name} expansion note",
                "url": f"{base}/expansion",
                "snippet": (
                    f"{name} is expanding its {city}, Ohio operation and adding warehouse associates this year."
                ),
                "published": "",
            },
            {
                "query_id": "hiring",
                "query": f"{name} hiring",
                "title": f"{name} hiring note",
                "url": f"{base}/hiring",
                "snippet": f"{name} posted warehouse associate openings in {city}, Ohio.",
                "published": "",
            },
            {
                "query_id": "leadership",
                "query": f"{name} leadership",
                "title": f"{name} operations note",
                "url": f"{base}/leadership",
                "snippet": f"{name} is staffing operations work at the {city}, Ohio site.",
                "published": "",
            },
            {
                "query_id": "automation",
                "query": f"{name} automation",
                "title": f"{name} systems note",
                "url": f"{base}/systems",
                "snippet": (
                    f"{name} public pages in this mock pass do not name an installed AutoStore, Dematic, or Bastian system."
                ),
                "published": "",
            },
        ]
        if "harborline" in name.lower():
            sources[3] = {
                "query_id": "automation",
                "query": f"{name} automation",
                "title": f"{name} existing installation",
                "url": f"{base}/customer",
                "snippet": f"{name} is an existing Bastian Solutions customer at its {city} facility.",
                "published": "",
            }
        return sources


def detect_existing_customer(company_name: str, sources: list[dict]) -> tuple[bool, str]:
    name = (company_name or "").lower()
    customer_re = re.compile(
        r"existing bastian( solutions)? customer"
        r"|bastian( solutions)? customer"
        r"|customer of bastian"
        r"|toyota automated logistics customer"
        r"|current (bastian|tal) customer",
        re.I,
    )
    for source in sources:
        text = f"{source.get('title', '')} {source.get('snippet', '')}"
        if re.search(r"\b(do not|don't|does not|not name|not list|no evidence)\b", text, flags=re.I):
            continue
        if customer_re.search(text):
            return True, (source.get("snippet") or "")[:400]
        low = text.lower()
        for match in re.finditer(r"bastian[^.]*installed|installed[^.]*bastian", low):
            window = low[max(0, match.start() - 80) : min(len(low), match.end() + 80)]
            if name and name in window:
                return True, (source.get("snippet") or "")[:400]
    return False, ""


def detect_installed_tech(sources: list[dict]) -> list[str]:
    rules = [
        ("autostore", r"auto-?store"),
        ("dematic", r"\bdematic\b"),
        ("vanderlande", r"\bvanderlande\b"),
        ("swisslog", r"\bswisslog\b"),
        ("conveyor", r"\bconveyors?\b"),
        ("asrs", r"\bas/?rs\b"),
        ("exacta", r"\bexacta\b"),
        ("sortation", r"\bsortation\b|\bsorters?\b"),
    ]
    found: set[str] = set()
    for source in sources:
        text = f"{source.get('title', '')} {source.get('snippet', '')}"
        if re.search(r"\b(do not|don't|does not|not name|not list|no evidence)\b", text, flags=re.I):
            continue
        if not re.search(r"\b(installed|operates|uses|using|deployed|running)\b", text, flags=re.I):
            continue
        for tech, pattern in rules:
            if re.search(pattern, text, flags=re.I):
                found.add(tech)
    return sorted(found)


def get_search(settings: Settings | None = None) -> SearchProvider:
    settings = settings or get_settings()
    if settings.search_mode == "tavily":
        return TavilySearch(settings.tavily_api_key, timeout=settings.request_timeout)
    return MockSearch()


def _http_post(body: dict, headers: dict) -> dict:
    timeout = get_settings().request_timeout
    with httpx.Client(timeout=timeout) as client:
        response = client.post(TavilySearch.url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Tavily returned an unexpected payload.")
    return data
