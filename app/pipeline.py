"""Research, draft, fact-check, and rewrite one company."""

from __future__ import annotations

import logging

from app import db
from app.claim_gate import gate_email, has_unverified
from app.config_loader import proof_library
from app.proof import select_proof
from app.providers.llm import get_llm, normalize_draft
from app.providers.search import detect_existing_customer, detect_installed_tech, get_search
from app.validators import validate_email

log = logging.getLogger("ohio_desk")
MAX_REWRITES = 2


def process_company(company_id: int, search=None, llm=None) -> None:
    company = db.get_company(company_id)
    if not company:
        return
    search = search or get_search()
    llm = llm or get_llm()
    try:
        _run(company, search, llm)
    except Exception as exc:
        log.exception("company %s failed", company_id)
        db.set_progress(company_id, "error", "Failed", str(exc)[:500])


def _run(company: dict, search, llm) -> None:
    company_id = company["id"]
    db.set_progress(company_id, "researching", "Searching public sources")
    sources = search.search(company)
    db.replace_sources(company_id, sources)
    existing, note = detect_existing_customer(company["name"], sources)
    tech = detect_installed_tech(sources)
    db.save_research_flags(company_id, existing_customer=existing, note=note, detected_tech=tech)
    if existing:
        db.set_progress(company_id, "existing_customer", "Existing Bastian/TAL customer — skipped", "")
        return
    if not sources:
        db.set_progress(company_id, "needs_review", "No sources returned", "")
        db.save_email(
            company_id,
            _contact_id(company),
            {
                "subject": "",
                "body": "",
                "followup_subject": "",
                "followup_body": "",
                "trigger_source_url": "",
                "proof_point_id": "",
                "status": "needs_review",
            },
            [],
            {"ok": False, "errors": ["No sources returned."], "warnings": []},
            0,
        )
        return

    proof = select_proof(company.get("industry_tags") or [], tech)
    contact = company.get("primary_contact") or (company.get("contacts") or [{}])[0]
    feedback: list[str] = []
    final_draft: dict = {}
    final_claims: list[dict] = []
    final_validation: dict = {}
    status = "needs_review"
    attempts = 0
    for attempt in range(MAX_REWRITES + 1):
        attempts = attempt + 1
        db.set_progress(
            company_id,
            "writing" if attempt == 0 else "rewriting",
            "Writing draft" if attempt == 0 else f"Rewriting ({attempt} of {MAX_REWRITES})",
        )
        payload = _payload(company, contact, sources, proof, tech, feedback, attempt)
        try:
            raw = llm.write_email(payload)
            draft = normalize_draft(raw, payload)
        except Exception as exc:
            feedback = [f"The writer did not return usable JSON ({exc})."]
            final_draft = {
                "subject": "",
                "body": "",
                "followup_subject": "",
                "followup_body": "",
                "trigger_source_url": "",
                "proof_point_id": proof.get("id"),
            }
            final_validation = {"ok": False, "errors": feedback, "warnings": []}
            final_claims = []
            continue

        validation = validate_email(
            draft,
            company_name=company["name"],
            facility_city=company.get("facility_city") or "",
        )
        db.set_progress(company_id, "fact_checking", "Fact-checking claims")
        try:
            llm_claims = (llm.fact_check({"draft": draft, "sources": sources, "library": proof_library()}) or {}).get(
                "claims"
            ) or []
        except Exception as exc:
            llm_claims = []
            validation.errors.append(f"Fact-check model failed ({exc}). Code gate still ran.")
            validation.ok = False
        claims = gate_email(
            body=draft.get("body") or "",
            followup=draft.get("followup") or draft.get("followup_body") or "",
            sources=sources,
            company_name=company["name"],
            llm_claims=llm_claims,
        )
        unverified = [claim for claim in claims if claim["label"] == "UNVERIFIED"]
        feedback = list(validation.errors) + [f"Unverified, remove or source this: {claim['claim']}" for claim in unverified]
        final_draft = draft
        final_claims = claims
        final_validation = validation.as_dict()
        if validation.ok and not unverified:
            status = "verified"
            break

    final_draft["status"] = status
    db.save_email(company_id, _contact_id(company), final_draft, final_claims, final_validation, attempts)
    if status == "verified":
        db.set_progress(company_id, "verified", "Verified", "")
    else:
        db.set_progress(company_id, "needs_review", "Needs review", "")


def rescore_saved_email(company_id: int, fields: dict) -> dict:
    """Re-run code checks after a hand edit. Does not call the model."""
    company = db.get_company(company_id)
    if not company or not company.get("email"):
        raise ValueError("No draft to update.")
    urls = {source["url"] for source in company["sources"] if source.get("url")}
    draft = {
        "subject": fields.get("subject") or "",
        "body": fields.get("body") or "",
        "followup_subject": fields.get("followup_subject") or "",
        "followup_body": fields.get("followup_body") or "",
        "trigger_source_url": fields.get("trigger_source_url") or "",
        "proof_point_id": company["email"].get("proof_point_id") or "",
    }
    validation = validate_email(
        draft,
        company_name=company["name"],
        facility_city=company.get("facility_city") or "",
    )
    if draft["trigger_source_url"] and urls and draft["trigger_source_url"] not in urls:
        validation.errors.append("Trigger source must be one of the saved research URLs.")
        validation.ok = False
    claims = gate_email(
        body=draft["body"],
        followup=draft["followup_body"],
        sources=company["sources"],
        company_name=company["name"],
    )
    status = "verified" if validation.ok and not has_unverified(claims) else "needs_review"
    draft["status"] = status
    attempts = int(company["email"].get("attempts") or 1)
    db.save_email(company_id, company["email"].get("contact_id"), draft, claims, validation.as_dict(), attempts)
    db.set_progress(company_id, status, "Verified" if status == "verified" else "Needs review", "")
    return db.get_company(company_id)


def _payload(company, contact, sources, proof, tech, feedback, attempt) -> dict:
    return {
        "attempt": attempt,
        "company_name": company["name"],
        "website": company.get("website") or "",
        "facility_city": company.get("facility_city") or "",
        "state": company.get("state") or "",
        "primary_industry": company.get("primary_industry") or "",
        "primary_sub_industry": company.get("primary_sub_industry") or "",
        "industry_tags": company.get("industry_tags") or [],
        "contact": contact or {},
        "detected_tech": tech,
        "proof": proof,
        "sources": sources,
        "feedback": feedback,
    }


def _contact_id(company: dict) -> int | None:
    contact = company.get("primary_contact")
    if contact and contact.get("id"):
        return contact["id"]
    return None
