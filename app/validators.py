"""Code checks for subject lines, length, banned words, links, and meeting asks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config_loader import style_rules
from app.textutil import word_count, words, you_we_counts

LINK_RE = re.compile(r"https?://|www\.", re.I)
ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.'-]+\s+"
    r"(st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|pkwy|parkway)\b",
    re.I,
)
GENERIC_NAME = {
    "distribution", "logistics", "retail", "manufacturing", "foods", "food", "parts",
    "company", "inc", "llc", "group", "industries", "industrial", "warehouse",
    "warehousing", "supply", "services", "international", "america", "american",
    "ohio", "the", "and", "goods", "tools", "quality",
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    body_words: int = 0
    followup_words: int = 0
    you_count: int = 0
    we_count: int = 0

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "body_words": self.body_words,
            "followup_words": self.followup_words,
            "you_count": self.you_count,
            "we_count": self.we_count,
        }


def validate_email(
    draft: dict,
    *,
    company_name: str = "",
    facility_city: str = "",
    rules: dict | None = None,
) -> ValidationResult:
    rules = rules or style_rules()
    errors: list[str] = []
    warnings: list[str] = []
    subject = (draft.get("subject") or "").strip()
    body = (draft.get("body") or "").strip()
    follow_subject = (draft.get("followup_subject") or "").strip()
    follow_body = (draft.get("followup_body") or "").strip()

    errors.extend(_subject_errors(subject, "Subject", rules))
    errors.extend(_subject_errors(follow_subject, "Follow-up subject", rules))

    body_words = word_count(body)
    follow_words = word_count(follow_body)
    if body_words > int(rules["body_max_words"]):
        errors.append(f"Body is {body_words} words. Keep it under {rules['body_max_words']}.")
    elif body_words < int(rules["body_min_words"]):
        errors.append(f"Body is {body_words} words. It needs the reason, problem, proof, and CTA.")
    elif body_words < int(rules["body_target_min"]) or body_words > int(rules["body_target_max"]):
        warnings.append(
            f"Body is {body_words} words. Aim for {rules['body_target_min']}-{rules['body_target_max']}."
        )
    if follow_words > int(rules["followup_max_words"]):
        errors.append(f"Follow-up is {follow_words} words. Keep it under {rules['followup_max_words']}.")
    elif follow_words < int(rules["followup_min_words"]):
        errors.append("Follow-up is too short to be useful.")

    combined = "\n".join([subject, body, follow_subject, follow_body])
    for phrase in rules.get("banned") or []:
        if _phrase_in(phrase, combined):
            errors.append(f"Banned word or phrase: {phrase}.")
    for pattern in rules.get("meeting_patterns") or []:
        if re.search(pattern, combined, flags=re.I):
            errors.append("The draft asks for a meeting or a call. Use an interest question or a one-page offer.")
            break
    if LINK_RE.search(combined):
        errors.append("Remove links from the subject, body, and follow-up.")
    if ADDRESS_RE.search(body) or ADDRESS_RE.search(follow_body):
        errors.append("A street address is in the draft. Leave it out.")

    you_count, we_count = you_we_counts(f"{body}\n{follow_body}")
    if we_count > 0 and you_count <= we_count:
        errors.append(f"Use more you/your ({you_count}) than I/we/our ({we_count}).")

    opening = " ".join(words(body)[:10]).lower()
    if re.match(r"^(my name|i am|i'm|we are|we're|this is)\b", opening):
        errors.append("Open with the trigger, not with who you are.")
    if company_name or facility_city:
        opening_words = [word.lower() for word in words(body)[:10]]
        tokens = _distinctive(company_name) + _distinctive(facility_city)
        if tokens and not any(token in opening_words for token in tokens):
            errors.append("Put the company or facility city in the first 10 words.")

    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        body_words=body_words,
        followup_words=follow_words,
        you_count=you_count,
        we_count=we_count,
    )


def _subject_errors(subject: str, label: str, rules: dict) -> list[str]:
    errors = []
    if not subject:
        return [f"{label} is empty."]
    pieces = subject.split()
    if not (int(rules["subject_min_words"]) <= len(pieces) <= int(rules["subject_max_words"])):
        errors.append(f"{label} must be {rules['subject_min_words']}-{rules['subject_max_words']} words.")
    if subject != subject.lower():
        errors.append(f"{label} must be all lowercase.")
    if re.search(r"\d", subject):
        errors.append(f"{label} cannot contain a number.")
    if "?" in subject:
        errors.append(f"{label} cannot be a question.")
    return errors


def _phrase_in(phrase: str, text: str) -> bool:
    parts = [re.escape(part) for part in phrase.split()]
    pattern = r"\b" + r"\s+".join(parts) + r"\b"
    return re.search(pattern, text, flags=re.I) is not None


def _distinctive(name: str) -> list[str]:
    out = []
    for word in words(name):
        low = word.lower()
        if len(low) <= 3 or low in GENERIC_NAME:
            continue
        out.append(low)
    return out


def banned_for_prompt(rules: dict | None = None) -> str:
    rules = rules or style_rules()
    banned = ", ".join(rules.get("banned") or [])
    return (
        "Enforced banned list (do not use these words or phrases): "
        + banned
        + ". Do not ask for a meeting, a call, a calendar hold, or anyone's time."
    )
