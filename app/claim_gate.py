"""Authoritative fact check.

A claim is VERIFIED only when a stored snippet or a proof-point wording supports it.
The model may propose labels, but it cannot mark a claim verified without that evidence.
"""

from __future__ import annotations

import re

from app.config_loader import proof_library
from app.textutil import norm_ws, numbers, numbers_supported, tokens

HEDGE_RE = re.compile(r"\b(often|usually|typically|tends to)\b", re.I)
RISKY = {
    "revenue", "profit", "saving", "savings", "dollar", "dollars", "employees",
    "people", "percent", "percentage", "storage", "square", "feet", "miles",
    "orders", "lines", "shifts", "shift", "hours", "hour", "customers",
}

GENERIC_NAME = {
    "distribution", "logistics", "retail", "manufacturing", "foods", "food", "parts",
    "company", "inc", "llc", "group", "industries", "industrial", "warehouse",
    "warehousing", "supply", "services", "international", "america", "american",
    "ohio", "the", "and", "goods", "tools", "quality",
}


def gate_email(
    *,
    body: str,
    followup: str,
    sources: list[dict],
    company_name: str,
    library: list[dict] | None = None,
    llm_claims: list[dict] | None = None,
) -> list[dict]:
    library = library or proof_library()
    claims = _code_claims(body, followup, sources, company_name, library)
    return _upgrade_with_quotes(claims, llm_claims or [], sources, library)


def _code_claims(body: str, followup: str, sources: list[dict], company_name: str, library: list[dict]) -> list[dict]:
    claims = []
    for section, text in (("body", body), ("followup", followup)):
        for sentence in _sentences(text):
            claims.append(_label_sentence(sentence, section, sources, company_name, library))
    return claims


def _label_sentence(sentence: str, section: str, sources: list[dict], company_name: str, library: list[dict]) -> dict:
    if _is_soft_ask(sentence):
        return _claim(sentence, section, "GENERAL", "", "Interest question or offer; not a new fact.")

    proof_hit = _proof_claim(sentence, library)
    if proof_hit is not None:
        return _claim(sentence, section, proof_hit[0], proof_hit[1], proof_hit[2])

    if HEDGE_RE.search(sentence) and not numbers(sentence) and not _names_company(sentence, company_name):
        return _claim(sentence, section, "GENERAL", "", "Hedged pattern (often/usually/typically), not a fact about this company.")

    source, score = _best_source(sentence, sources)
    if source and score >= 0.62 and numbers_supported(sentence, f"{source.get('title', '')} {source.get('snippet', '')}"):
        return _claim(sentence, section, "VERIFIED", source.get("url") or "", source.get("snippet") or "")
    return _claim(sentence, section, "UNVERIFIED", "", "No stored snippet supports this sentence.")


def _proof_claim(sentence: str, library: list[dict]) -> tuple[str, str, str] | None:
    mentioned = [proof for proof in library if _anchored(sentence, proof)]
    if not mentioned:
        return None
    sentence_numbers = numbers(sentence)
    if sentence_numbers:
        def coverage(proof: dict) -> int:
            blob = _proof_blob(proof)
            return sum(1 for number in sentence_numbers if numbers_supported(number, blob))

        best = max(mentioned, key=lambda proof: (coverage(proof), -int(proof.get("order") or 99)))
    else:
        best = max(mentioned, key=lambda proof: (_token_overlap(sentence, _proof_blob(proof)), -int(proof.get("order") or 99)))

    blob = _proof_blob(best)
    for phrase in best.get("forbidden") or []:
        if phrase.lower() in sentence.lower():
            return ("UNVERIFIED", "", f"Uses forbidden wording for {best.get('name')}: {phrase}.")
    if not numbers_supported(sentence, blob):
        return ("UNVERIFIED", "", "A number in the proof sentence is not in the proof-point wording.")
    extra_risky = [token for token in tokens(sentence) if token in RISKY and token not in set(tokens(blob))]
    if extra_risky:
        return ("UNVERIFIED", "", f"Adds {', '.join(extra_risky)} which the proof point does not state.")
    overlap = _token_overlap(sentence, blob)
    # A fragment such as "At AAP's St." overlaps the name but is not the proof.
    if not sentence_numbers and (overlap < 0.45 or len(tokens(sentence)) < 6):
        return ("UNVERIFIED", "", "Names a proof point without its published facts.")
    url = (best.get("sources") or [""])[0]
    return ("VERIFIED", url, best.get("search_text") or best.get("wording") or "")


def _upgrade_with_quotes(claims: list[dict], llm_claims: list[dict], sources: list[dict], library: list[dict]) -> list[dict]:
    corpus = _corpus(sources, library)
    upgraded = []
    for claim in claims:
        if claim["label"] != "UNVERIFIED":
            upgraded.append(claim)
            continue
        quote = _matching_quote(claim["claim"], llm_claims, corpus)
        if quote:
            upgraded.append({**claim, "label": "VERIFIED", "source_url": quote[0], "source_quote": quote[1]})
        else:
            upgraded.append(claim)
    return upgraded


def _matching_quote(claim_text: str, llm_claims: list[dict], corpus: list[tuple[str, str]]) -> tuple[str, str] | None:
    target = norm_ws(claim_text)
    for proposed in llm_claims:
        proposed_text = norm_ws(proposed.get("claim") or proposed.get("text") or "")
        if proposed_text and proposed_text != target and target not in proposed_text and proposed_text not in target:
            continue
        quote = (proposed.get("source_quote") or proposed.get("matched_snippet") or "").strip()
        if _quote_supports(claim_text, quote, corpus):
            url = proposed.get("source_url") or proposed.get("matched_url") or ""
            return url, quote
    return None


def quote_supports(claim_text: str, quote: str, sources: list[dict], library: list[dict] | None = None) -> bool:
    return _quote_supports(claim_text, quote, _corpus(sources, library or proof_library()))


def _quote_supports(claim_text: str, quote: str, corpus: list[tuple[str, str]]) -> bool:
    folded = norm_ws(quote)
    if len(folded) < 12:
        return False
    if not any(folded in norm_ws(text) for _, text in corpus):
        return False
    if not numbers_supported(claim_text, quote):
        return False
    claim_tokens = tokens(claim_text)
    if not claim_tokens:
        return False
    quote_tokens = set(tokens(quote))
    hits = sum(1 for token in claim_tokens if token in quote_tokens)
    return hits / len(claim_tokens) >= 0.6


def _corpus(sources: list[dict], library: list[dict]) -> list[tuple[str, str]]:
    items = []
    for source in sources:
        items.append((source.get("url") or "", f"{source.get('title', '')} {source.get('snippet', '')}"))
    for proof in library:
        text = " ".join(
            part
            for part in (proof.get("search_text"), proof.get("email_line"), proof.get("wording"))
            if part
        )
        url = (proof.get("sources") or [""])[0]
        items.append((url, text))
    return items


def _best_source(sentence: str, sources: list[dict]) -> tuple[dict | None, float]:
    needed = tokens(sentence)
    if not needed:
        return None, 0
    best = None
    best_score = 0.0
    for source in sources:
        blob = set(tokens(f"{source.get('title', '')} {source.get('snippet', '')}"))
        hits = sum(1 for token in needed if token in blob)
        score = hits / len(needed)
        if score > best_score:
            best = source
            best_score = score
    return best, best_score


def _token_overlap(sentence: str, blob: str) -> float:
    needed = tokens(sentence)
    if not needed:
        return 0
    have = set(tokens(blob))
    return sum(1 for token in needed if token in have) / len(needed)


def _anchored(sentence: str, proof: dict) -> bool:
    low = sentence.lower()
    return any(anchor.lower() in low for anchor in proof.get("anchors") or [])


def _proof_blob(proof: dict) -> str:
    return " ".join(part for part in (proof.get("search_text"), proof.get("email_line")) if part)


def _is_soft_ask(sentence: str) -> bool:
    return sentence.rstrip().endswith("?") and not numbers(sentence)


def _names_company(sentence: str, company_name: str) -> bool:
    low = sentence.lower()
    return any(token in low for token in _distinctive(company_name))


def _distinctive(name: str) -> list[str]:
    out = []
    for word in re.findall(r"[A-Za-z0-9]+", name or ""):
        low = word.lower()
        if len(low) <= 3 or low in GENERIC_NAME:
            continue
        out.append(low)
    return out


def _sentences(text: str) -> list[str]:
    from app.textutil import iter_sentences

    return iter_sentences(text)


def _claim(text: str, section: str, label: str, url: str, quote: str) -> dict:
    return {
        "claim": text,
        "section": section,
        "label": label,
        "source_url": url,
        "source_quote": quote,
    }


def has_unverified(claims: list[dict]) -> bool:
    return any(claim.get("label") == "UNVERIFIED" for claim in claims)
