"""Chat providers. OpenAI-compatible first, Anthropic beside it, mock when no key is set."""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from app.config_loader import load_text, proof_library
from app.proof import proof_by_id
from app.settings import Settings, get_settings
from app.validators import banned_for_prompt

PROBLEMS = {
    "polaris_wilmington": "When a site adds people or SKUs, overtime and long pick walks usually show up before throughput does.",
    "garmin_olathe": "When volume stays high, a second full shift usually costs more than the building can staff.",
    "aap_st_marys": "Plant teams usually feel that growth first as forklift traffic and manual handling between the line and the dock.",
    "cnh_indianapolis": "As order lines grow, walking each shelf usually caps throughput before the dock does.",
}


class ChatProvider(Protocol):
    name: str

    def write_email(self, payload: dict) -> dict: ...

    def fact_check(self, payload: dict) -> dict: ...


class MockChat:
    name = "mock"

    def write_email(self, payload: dict) -> dict:
        return compose_mock_email(payload)

    def fact_check(self, payload: dict) -> dict:
        # The code gate is authoritative. Returning no model claims keeps the
        # demo deterministic and still stores a claim table.
        return {"claims": []}


class OpenAIChat:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 45,
        json_mode: bool = True,
        post=None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.json_mode = json_mode
        self.post = post or _post_json

    def write_email(self, payload: dict) -> dict:
        raw = self._chat(system_prompt(), email_user_prompt(payload))
        return parse_json_object(raw)

    def fact_check(self, payload: dict) -> dict:
        raw = self._chat(load_text("factcheck_prompt.md"), factcheck_user_prompt(payload))
        data = parse_json_object(raw)
        data.setdefault("claims", [])
        return data

    def _chat(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        if self.json_mode:
            try:
                data = self.post(url, {**body, "response_format": {"type": "json_object"}}, headers, self.timeout)
            except Exception:
                data = self.post(url, body, headers, self.timeout)
        else:
            data = self.post(url, body, headers, self.timeout)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible response did not include a message.") from exc


class AnthropicChat:
    name = "anthropic"

    def __init__(self, *, api_key: str, model: str, timeout: float = 45, post=None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.post = post or _post_json

    def write_email(self, payload: dict) -> dict:
        raw = self._chat(system_prompt(), email_user_prompt(payload))
        return parse_json_object(raw)

    def fact_check(self, payload: dict) -> dict:
        raw = self._chat(load_text("factcheck_prompt.md"), factcheck_user_prompt(payload))
        data = parse_json_object(raw)
        data.setdefault("claims", [])
        return data

    def _chat(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "max_tokens": 2500,
            "temperature": 0.2,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        data = self.post("https://api.anthropic.com/v1/messages", body, headers, self.timeout)
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Anthropic response did not include text.") from exc


def get_llm(settings: Settings | None = None) -> ChatProvider:
    settings = settings or get_settings()
    if settings.llm_mode == "anthropic":
        return AnthropicChat(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout=settings.request_timeout,
        )
    if settings.llm_mode == "openai":
        return OpenAIChat(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            timeout=settings.request_timeout,
            json_mode=settings.openai_json_mode,
        )
    return MockChat()


def system_prompt() -> str:
    return load_text("system_prompt.md") + "\n\n" + load_text("email_rules.md") + "\n\n" + banned_for_prompt()


def email_user_prompt(payload: dict) -> str:
    proof = payload["proof"]
    sources = payload.get("sources") or []
    source_lines = []
    for index, source in enumerate(sources, start=1):
        source_lines.append(
            f"{index}. URL: {source.get('url')}\nTitle: {source.get('title')}\nSnippet: {source.get('snippet')}"
        )
    feedback = payload.get("feedback") or []
    feedback_block = ""
    if feedback:
        feedback_block = "The previous draft failed checks. Fix every item and drop unverified claims:\n- " + "\n- ".join(
            feedback
        )
    warning = ""
    if proof.get("blocked_by_existing_tech"):
        warning = (
            "Research suggests this prospect may already run technology in this proof point. "
            "Do not claim they lack it, and do not recommend that system. Use a labor or flow observation only if the proof wording supports it.\n"
        )
    contact = payload.get("contact") or {}
    return f"""TASK: write_email
Attempt: {payload.get("attempt", 0)}

Company name: {payload.get("company_name")}
Website: {payload.get("website") or "unknown"}
Ohio facility city: {payload.get("facility_city")}
Company state: {payload.get("state")}
Industry: {payload.get("primary_industry")} / {payload.get("primary_sub_industry")}
Industry tags: {", ".join(payload.get("industry_tags") or [])}
Contact: {contact.get("first_name")} {contact.get("last_name")}, {contact.get("title")}
Contact city/state: {contact.get("person_city")}, {contact.get("person_state")}
No street address is provided. Do not invent one.

Technology already indicated in research (do not pitch these): {", ".join(payload.get("detected_tech") or []) or "none"}
{warning}
Proof point id: {proof.get("id")}
Proof wording (do not add facts): {proof.get("wording")}
Approved sentence you may copy: {proof.get("email_line")}
Proof source URLs (do not put these in the email body): {", ".join(proof.get("sources") or [])}

Research sources, the only place prospect facts may come from:
{chr(10).join(source_lines) if source_lines else "(none)"}

{feedback_block}
"""


def factcheck_user_prompt(payload: dict) -> str:
    draft = payload["draft"]
    sources = payload.get("sources") or []
    source_lines = [
        f"URL: {source.get('url')}\nSnippet: {source.get('snippet')}" for source in sources
    ]
    proof_lines = []
    for proof in payload.get("library") or proof_library():
        proof_lines.append(f"{proof.get('id')}: {proof.get('search_text') or proof.get('wording')}")
    return f"""TASK: fact_check

Subject: {draft.get("subject")}
Body:
{draft.get("body")}

Follow-up subject: {draft.get("followup_subject")}
Follow-up:
{draft.get("followup_body")}

Research snippets:
{chr(10).join(source_lines)}

Proof-point wording:
{chr(10).join(proof_lines)}
"""


def compose_mock_email(payload: dict) -> dict:
    company = payload.get("company_name") or "The company"
    contact = payload.get("contact") or {}
    first = (contact.get("first_name") or "Hello").strip()
    city = payload.get("facility_city") or "Ohio"
    proof = payload["proof"]
    sources = payload.get("sources") or []
    trigger = next((source for source in sources if source.get("query_id") == "news"), sources[0] if sources else {})
    snippet = (trigger.get("snippet") or f"{company} is expanding its {city}, Ohio operation.").rstrip(".")
    attempt = int(payload.get("attempt") or 0)
    name_l = company.lower()
    subject = _subject(city, proof.get("id") or "")
    follow_subject = _subject(city, "note")
    if "drafty" in name_l and attempt == 0:
        return {
            "subject": "quick synergy",
            "body": (
                f"{first} - saw {company} is expanding its {city}, Ohio operation and adding warehouse associates this year.\n\n"
                "This synergy will revolutionize a 999% faster dock.\n\n"
                f"{proof.get('email_line')}\n\n"
                "Can we schedule a call next week?"
            ),
            "followup_subject": follow_subject,
            "followup_body": f"{first} - just checking in on that call.",
            "trigger_source_url": trigger.get("url") or "",
            "proof_point_id": proof.get("id"),
        }
    if "unsourced" in name_l:
        reason = f"{first} - saw {company} opened a 999,000 square foot building in {city}"
    else:
        reason = f"{first} - saw {snippet}"
    problem = PROBLEMS.get(proof.get("id") or "", PROBLEMS["polaris_wilmington"])
    body = (
        f"{reason}.\n\n"
        f"{problem}\n\n"
        f"{proof.get('email_line')}\n\n"
        "Would a one-page summary of that result be useful on your side?"
    )
    follow = f"{first} - want the one-page note on that {city} operation for your planning file?"
    return {
        "subject": subject,
        "body": body,
        "followup_subject": follow_subject,
        "followup_body": follow,
        "trigger_source_url": trigger.get("url") or "",
        "proof_point_id": proof.get("id"),
    }


def _subject(city: str, topic: str) -> str:
    city_words = re.findall(r"[a-z]+", (city or "ohio").lower())[:1] or ["ohio"]
    topics = {
        "polaris_wilmington": ["pick", "walks"],
        "garmin_olathe": ["shift", "labor"],
        "aap_st_marys": ["plant", "flow"],
        "cnh_indianapolis": ["order", "lines"],
        "note": ["note"],
    }.get(topic, ["warehouse", "work"])
    return " ".join((city_words + topics)[:4])


def parse_json_object(text: str) -> dict:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("Model did not return JSON.")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("Model JSON was not an object.")
    return data


def normalize_draft(draft: dict, payload: dict) -> dict:
    proof = payload["proof"]
    sources = payload.get("sources") or []
    urls = {source.get("url") for source in sources if source.get("url")}
    trigger = (draft.get("trigger_source_url") or "").strip()
    if trigger not in urls:
        news = next((source for source in sources if source.get("query_id") == "news" and source.get("url")), None)
        trigger = (news or (sources[0] if sources else {})).get("url") or ""
    proof_id = draft.get("proof_point_id")
    if not proof_by_id(proof_id or ""):
        proof_id = proof.get("id")
    return {
        "subject": (draft.get("subject") or "").strip(),
        "body": (draft.get("body") or "").strip(),
        "followup_subject": (draft.get("followup_subject") or "").strip(),
        "followup_body": (draft.get("followup_body") or "").strip(),
        "trigger_source_url": trigger,
        "proof_point_id": proof_id,
    }


def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Chat API returned an unexpected payload.")
    return data
