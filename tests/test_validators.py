from app.providers.llm import compose_mock_email
from app.providers.search import MockSearch
from app.proof import select_proof
from app.validators import validate_email


def _good():
    proof = select_proof(["dc"], [])
    sources = MockSearch().search({"name": "Northline Distribution", "facility_city": "Columbus", "state": "Ohio"})
    return compose_mock_email(
        {
            "company_name": "Northline Distribution",
            "facility_city": "Columbus",
            "contact": {"first_name": "Maya"},
            "proof": proof,
            "sources": sources,
            "attempt": 0,
        }
    )


def test_good_draft_passes():
    result = validate_email(_good(), company_name="Northline Distribution", facility_city="Columbus")
    assert result.ok, result.errors
    assert 60 <= result.body_words <= 90
    assert result.followup_words < 40
    assert result.you_count > result.we_count


def test_banned_word_subject_and_meeting_fail():
    draft = _good()
    draft["body"] = draft["body"].replace("usually", "usually synergy")
    draft["subject"] = "Pick Rates?"
    draft["followup_body"] = "Can we schedule a call?"
    result = validate_email(draft, company_name="Northline Distribution", facility_city="Columbus")
    assert not result.ok
    text = " ".join(result.errors).lower()
    assert "banned" in text
    assert "lowercase" in text or "question" in text
    assert "meeting" in text or "call" in text


def test_subject_rules_and_link_and_address():
    draft = _good()
    draft["subject"] = "one two three four five"
    draft["followup_subject"] = "shift 2"
    draft["body"] = "See https://example.com and 100 Fixture Lane in Columbus for Northline Distribution " + draft["body"]
    result = validate_email(draft, company_name="Northline Distribution", facility_city="Columbus")
    assert not result.ok
    text = " ".join(result.errors).lower()
    assert "4 words" in text or "1-4" in text or "words" in text
    assert "number" in text
    assert "link" in text
    assert "street" in text


def test_long_body_fails():
    draft = _good()
    draft["body"] = draft["body"] + " " + " ".join(["walk"] * 80)
    result = validate_email(draft, company_name="Northline Distribution", facility_city="Columbus")
    assert any("under" in error for error in result.errors)
