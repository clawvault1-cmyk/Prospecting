"""Score ZoomInfo rows for an Ohio warehouse-automation conversation."""

from __future__ import annotations

import re
from collections import defaultdict

from app.config_loader import scoring_rules

OHIO = {"oh", "ohio"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def score_rows(rows: list[dict], rules: dict | None = None) -> list[dict]:
    rules = rules or scoring_rules()
    grouped: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for row in rows:
        name = re.sub(r"\s+", " ", (row.get("company") or "").strip())
        if not name:
            continue
        key = name.casefold()
        if key not in grouped:
            order.append(key)
        grouped[key].append({**row, "company": name})

    companies = [_score_company(grouped[key], rules) for key in order]
    companies.sort(key=lambda company: (company["included"], company["rank_score"]), reverse=True)
    return companies


def _score_company(rows: list[dict], rules: dict) -> dict:
    first = rows[0]
    contacts = [_score_contact(row, rules) for row in rows]
    contacts.sort(key=lambda contact: (contact["persona_score"], contact["has_email"], contact["in_ohio"]), reverse=True)
    if contacts:
        contacts[0]["is_primary"] = True

    industry_points, tags, industry_hits = _industry_score(_industry_blob(first), rules)
    employees = parse_employees(first.get("employees"), first.get("employee_range"))
    revenue = parse_revenue_000s(first.get("revenue_000s"))
    size_points, size_note = _size_score(employees, revenue, rules)

    company_ohio = is_ohio(first.get("company_state"))
    ohio_contact = next((contact for contact in contacts if contact["in_ohio"]), None)
    if company_ohio:
        ohio_points = int(rules["ohio_company_points"])
        ohio_via = "Company state is Ohio"
        facility_city = (first.get("company_city") or "").strip()
    elif ohio_contact:
        ohio_points = int(rules["ohio_contact_points"])
        who = f"{ohio_contact['first_name']} {ohio_contact['last_name']}".strip()
        ohio_via = f"Contact {who} is in Ohio"
        facility_city = (ohio_contact.get("person_city") or "").strip()
    else:
        ohio_points = 0
        ohio_via = ""
        facility_city = (first.get("company_city") or "").strip()

    if not facility_city and ohio_contact:
        facility_city = (ohio_contact.get("person_city") or "").strip()

    industry_points = min(industry_points, int(rules["industry_cap"]))
    fit = ohio_points + industry_points + size_points
    primary = contacts[0] if contacts else None
    persona = primary["persona_score"] if primary else 0
    rank = fit + persona * float(rules["persona"]["rank_weight"])

    included = True
    reason = ""
    if rules.get("require_ohio", True) and ohio_points <= 0:
        included = False
        reason = "No Ohio facility. Company state and every contact state are outside Ohio."
    elif industry_points < int(rules["min_industry_points"]):
        included = False
        reason = "Industry is outside the fit list (manufacturing, distribution/wholesale, 3PL, retail/ecommerce, parts)."

    notes = [part for part in (ohio_via, industry_hits, size_note) if part]
    if primary:
        notes.append(f"Contact: {primary['persona_notes']}")

    return {
        "name": first["company"],
        "website": (first.get("website") or "").strip(),
        "city": (first.get("company_city") or "").strip(),
        "state": (first.get("company_state") or "").strip(),
        "country": (first.get("company_country") or "").strip(),
        "facility_city": facility_city,
        "ohio_via": ohio_via,
        "revenue_000s": revenue,
        "revenue_range": (first.get("revenue_range") or "").strip(),
        "employees": employees,
        "employee_range": (first.get("employee_range") or "").strip(),
        "primary_industry": (first.get("primary_industry") or "").strip(),
        "primary_sub_industry": (first.get("primary_sub_industry") or "").strip(),
        "all_industries": (first.get("all_industries") or "").strip(),
        "industry_tags": sorted(tags),
        "fit_score": fit,
        "rank_score": round(rank, 2),
        "score_notes": " · ".join(notes),
        "included": included,
        "exclude_reason": reason,
        "contacts": contacts,
    }


def _score_contact(row: dict, rules: dict) -> dict:
    persona = rules["persona"]
    title = row.get("title") or ""
    level_name = row.get("management_level") or ""
    function = row.get("job_function") or ""
    department = row.get("department") or ""
    blob = " ".join([title, level_name, function, department]).lower()
    points = _level_points(blob, persona["levels"])
    notes = [f"level {points}"]
    for phrase, value in persona["keywords"].items():
        if phrase in blob:
            points += int(value)
            notes.append(f"{phrase} +{value}")
    in_ohio = is_ohio(row.get("person_state"))
    email = (row.get("email") or "").strip()
    has_email = bool(EMAIL_RE.match(email))
    if in_ohio:
        points += int(persona["ohio_bonus"])
        notes.append(f"Ohio +{persona['ohio_bonus']}")
    if has_email:
        points += int(persona["email_bonus"])
        notes.append(f"email +{persona['email_bonus']}")
    else:
        points += int(persona["no_email_penalty"])
        notes.append(f"no email {persona['no_email_penalty']}")
    return {
        "first_name": (row.get("first_name") or "").strip(),
        "last_name": (row.get("last_name") or "").strip(),
        "title": title.strip(),
        "email": email if has_email else "",
        "management_level": level_name.strip(),
        "job_function": function.strip(),
        "department": department.strip(),
        "person_city": (row.get("person_city") or "").strip(),
        "person_state": (row.get("person_state") or "").strip(),
        "persona_score": points,
        "persona_notes": ", ".join(notes),
        "is_primary": False,
        "has_email": has_email,
        "in_ohio": in_ohio,
    }


def _level_points(blob: str, levels: dict) -> int:
    if re.search(r"\b(vp|vice president)\b", blob):
        return int(levels["vp"])
    if "director" in blob:
        return int(levels["director"])
    if "manager" in blob:
        return int(levels["manager"])
    if re.search(r"\b(supervisor|superintendent|head|lead)\b", blob):
        return int(levels["supervisor"])
    return int(levels["other"])


def _industry_blob(row: dict) -> str:
    parts = [
        row.get("primary_industry"),
        row.get("primary_sub_industry"),
        row.get("all_industries"),
        row.get("all_sub_industries"),
    ]
    return " ".join(part or "" for part in parts).lower()


def _industry_score(blob: str, rules: dict) -> tuple[int, set[str], str]:
    points = 0
    tags: set[str] = set()
    hits: list[str] = []
    for name, spec in (rules.get("categories") or {}).items():
        if any(keyword.lower() in blob for keyword in spec.get("keywords") or []):
            points += int(spec["points"])
            tags.update(spec.get("tags") or [])
            hits.append(name.replace("_", " "))
    note = f"Industry: {', '.join(hits)}" if hits else "Industry: no match"
    return points, tags, note


def _size_score(employees: int | None, revenue_000s: int | None, rules: dict) -> tuple[int, str]:
    employee_points = _tier(employees, rules["employee_tiers"]) if employees is not None else None
    revenue_points = _tier(revenue_000s, rules["revenue_tiers_000s"]) if revenue_000s is not None else None
    candidates = [value for value in (employee_points, revenue_points) if value is not None]
    points = max(candidates) if candidates else 4
    bits = []
    if employees is not None:
        bits.append(f"{employees} employees")
    if revenue_000s is not None:
        bits.append(f"revenue ${revenue_000s / 1000:.1f}M")
    detail = ", ".join(bits) if bits else "size unknown"
    return points, f"Size: {detail}"


def _tier(value: int, tiers: list[dict]) -> int:
    ordered = sorted(tiers, key=lambda tier: int(tier["min"]), reverse=True)
    for tier in ordered:
        if value >= int(tier["min"]):
            return int(tier["points"])
    return 0


def is_ohio(state: str | None) -> bool:
    return (state or "").strip().lower() in OHIO


def parse_intish(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"-?\d[\d,]*", text)
    if not match:
        return None
    return int(match.group().replace(",", ""))


def parse_employees(employees: str | None, employee_range: str | None) -> int | None:
    direct = parse_intish(employees)
    if direct is not None:
        return direct
    text = (employee_range or "").lower()
    between = re.search(r"(\d+)\s*to\s*(\d+)", text)
    if between:
        return int(between.group(1))
    plus = re.search(r"(\d+)\s*plus", text)
    if plus:
        return int(plus.group(1))
    return None


def parse_revenue_000s(value: str | None) -> int | None:
    return parse_intish(value)
