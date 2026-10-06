from app.claim_gate import gate_email, has_unverified, quote_supports
from app.proof import proof_library, select_proof


SNIPPET = "Northline Distribution is expanding its Columbus, Ohio operation and adding warehouse associates this year."
SOURCES = [{"url": "https://example.com/mock/northline/expansion", "title": "Expansion", "snippet": SNIPPET}]


def test_copied_fact_is_verified_and_hedge_is_general():
    proof = select_proof(["dc"], [])
    body = (
        "Maya - saw Northline Distribution is expanding its Columbus, Ohio operation and adding warehouse associates this year.\n\n"
        "When a site adds people or SKUs, overtime and long pick walks usually show up before throughput does.\n\n"
        f"{proof['email_line']}\n\n"
        "Would a one-page summary of that result be useful on your side?"
    )
    claims = gate_email(body=body, followup="Maya - want the one-page note on that Columbus operation for your planning file?", sources=SOURCES, company_name="Northline Distribution")
    labels = {claim["claim"][:24]: claim["label"] for claim in claims}
    assert not has_unverified(claims), claims
    assert any(claim["label"] == "VERIFIED" and "expanding" in claim["claim"] for claim in claims)
    assert any(claim["label"] == "GENERAL" and "usually" in claim["claim"] for claim in claims)
    assert any(claim["label"] == "VERIFIED" and "Polaris" in claim["claim"] for claim in claims)
    assert labels


def test_invented_number_is_unverified():
    body = "Maya - saw Northline Distribution opened a 999,000 square foot building in Columbus."
    claims = gate_email(body=body, followup="", sources=SOURCES, company_name="Northline Distribution")
    assert claims[0]["label"] == "UNVERIFIED"


def test_aap_sentence_stays_intact():
    from app.textutil import iter_sentences

    line = "At AAP's St. Mary's, OH wheel plant, Bastian built an AS/RS storage buffer and conveyor with Exacta that cut forklift traffic and manual handling and improved inventory visibility."
    assert iter_sentences(line) == [line]
    claims = gate_email(body=line, followup="", sources=SOURCES, company_name="Little Bolt Co")
    assert claims[0]["label"] == "VERIFIED"


def test_storage_capacity_is_rejected_for_polaris():
    body = "Polaris tripled storage capacity and saw about 150% faster pick rate."
    claims = gate_email(body=body, followup="", sources=SOURCES, company_name="Northline Distribution")
    assert claims[0]["label"] == "UNVERIFIED"


def test_false_verified_quote_does_not_upgrade():
    body = "Northline Distribution doubled revenue last spring."
    claims = gate_email(
        body=body,
        followup="",
        sources=SOURCES,
        company_name="Northline Distribution",
        llm_claims=[
            {
                "claim": body,
                "label": "VERIFIED",
                "source_url": "https://example.com/nowhere",
                "source_quote": "Northline Distribution doubled revenue last spring",
            }
        ],
    )
    assert claims[0]["label"] == "UNVERIFIED"


def test_real_quote_can_upgrade_a_paraphrase():
    sentence = "The warehouse associates this year include a picnic."
    quote = "warehouse associates this year"
    assert quote_supports(sentence, quote, SOURCES, proof_library())
    claims = gate_email(
        body=sentence,
        followup="",
        sources=SOURCES,
        company_name="Northline Distribution",
        llm_claims=[{"claim": sentence, "source_url": SOURCES[0]["url"], "source_quote": quote}],
    )
    assert claims[0]["label"] == "VERIFIED"
    assert claims[0]["source_quote"] == quote
