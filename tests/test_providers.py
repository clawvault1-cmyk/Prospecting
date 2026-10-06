from datetime import date, timedelta

from app.providers.llm import AnthropicChat, OpenAIChat, parse_json_object
from app.providers.search import TavilySearch
from app.proof import select_proof


def test_tavily_request_shape():
    calls = []

    def post(body, headers):
        calls.append((body, headers))
        return {"results": [{"title": "Story", "url": f"https://news.example/{len(calls)}", "content": "A fact.", "published_date": "2026-03-01"}]}

    search = TavilySearch("tvly-test", post=post, today=date(2026, 10, 6))
    found = search.search({"name": "Acme Parts", "facility_city": "Dayton", "state": "Ohio"})
    assert found
    assert all(headers["Authorization"] == "Bearer tvly-test" for _, headers in calls)
    expected_start = (date(2026, 10, 6) - timedelta(days=548)).isoformat()
    boxed = [body for body, _ in calls if body.get("start_date")]
    open_ended = [body for body, _ in calls if "start_date" not in body]
    assert boxed and open_ended
    assert all(body["start_date"] == expected_start for body in boxed)
    assert all(body["search_depth"] == "advanced" for body, _ in calls)
    assert "Acme Parts" in calls[0][0]["query"]


def test_openai_compatible_request_shape():
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body, headers, timeout))
        return {"choices": [{"message": {"content": '{"subject":"dayton note","body":"Hi","followup_subject":"dayton file","followup_body":"Later","trigger_source_url":"https://news.example/1","proof_point_id":"polaris_wilmington"}'}}]}

    client = OpenAIChat(
        api_key="sk-test",
        base_url="https://api.x.ai/v1",
        model="grok-test",
        json_mode=True,
        post=post,
    )
    draft = client.write_email(
        {
            "attempt": 0,
            "company_name": "Acme Parts",
            "facility_city": "Dayton",
            "state": "Ohio",
            "contact": {"first_name": "Rita", "last_name": "Cole", "title": "Warehouse Manager"},
            "proof": select_proof(["dc"], []),
            "sources": [{"url": "https://news.example/1", "title": "Story", "snippet": "Acme is expanding."}],
            "industry_tags": ["dc"],
            "detected_tech": [],
        }
    )
    assert calls[0][0] == "https://api.x.ai/v1/chat/completions"
    assert calls[0][1]["model"] == "grok-test"
    assert calls[0][1]["response_format"] == {"type": "json_object"}
    assert calls[0][2]["Authorization"] == "Bearer sk-test"
    assert draft["subject"] == "dayton note"


def test_anthropic_request_shape():
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body, headers))
        return {"content": [{"text": '{"claims": []}'}]}

    client = AnthropicChat(api_key="ant-test", model="claude-test", post=post)
    result = client.fact_check(
        {
            "draft": {"subject": "dayton note", "body": "Hello.", "followup_subject": "dayton file", "followup_body": "Later."},
            "sources": [],
            "library": [],
        }
    )
    assert calls[0][0] == "https://api.anthropic.com/v1/messages"
    assert calls[0][1]["model"] == "claude-test"
    assert calls[0][2]["x-api-key"] == "ant-test"
    assert result["claims"] == []


def test_parse_fenced_json():
    data = parse_json_object('```json\n{"subject": "plant flow"}\n```')
    assert data["subject"] == "plant flow"


def test_proof_selection_respects_tags_and_existing_tech():
    assert select_proof(["manufacturing"], [])["id"] == "aap_st_marys"
    assert select_proof(["dc"], [])["id"] == "polaris_wilmington"
    assert select_proof(["dc", "parts"], [])["id"] == "polaris_wilmington"
    assert select_proof(["ecommerce"], [])["id"] == "polaris_wilmington"
    avoided = select_proof(["dc"], ["autostore"])
    assert avoided["id"] == "garmin_olathe"
    assert avoided["blocked_by_existing_tech"] is False
