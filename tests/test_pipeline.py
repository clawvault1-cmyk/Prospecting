from app import db
from app.pipeline import process_company
from app.proof import select_proof
from app.scoring import score_rows


def _batch(rows):
    companies = score_rows(rows)
    return db.insert_batch("unit.csv", companies), companies


def _base_row(**extra):
    row = {
        "company": "Northline Distribution",
        "company_state": "Ohio",
        "company_city": "Columbus",
        "employees": "800",
        "revenue_000s": "120000",
        "primary_industry": "Wholesale",
        "primary_sub_industry": "Distribution",
        "first_name": "Maya",
        "last_name": "Chen",
        "title": "Director, Warehouse",
        "management_level": "Director",
        "email": "maya.chen@northline.example",
        "person_state": "Ohio",
        "person_city": "Columbus",
        "company_street": "100 Fixture Lane",
    }
    row.update(extra)
    return row


def test_mock_pipeline_verifies_and_skips_customer():
    batch_id, _ = _batch(
        [
            _base_row(),
            _base_row(
                company="Harborline Foods",
                company_city="Toledo",
                person_city="Toledo",
                primary_industry="Manufacturing",
                primary_sub_industry="Food",
                first_name="Pat",
                last_name="Kim",
                title="Plant Manager",
                email="pat.kim@harborline.example",
            ),
        ]
    )
    companies = db.list_companies(batch_id)
    by_name = {company["name"]: company for company in companies}
    process_company(by_name["Northline Distribution"]["id"])
    process_company(by_name["Harborline Foods"]["id"])

    north = db.get_company(by_name["Northline Distribution"]["id"])
    assert north["status"] == "verified"
    assert north["email"]["status"] == "verified"
    assert "Fixture" not in north["email"]["body"]
    assert "http" not in north["email"]["body"].lower()
    assert north["sources"]
    assert any(claim["label"] == "VERIFIED" for claim in north["claims"])
    assert all(claim["label"] != "UNVERIFIED" for claim in north["claims"])
    assert select_proof(north["industry_tags"])["id"] == north["email"]["proof_point_id"]

    harbor = db.get_company(by_name["Harborline Foods"]["id"])
    assert harbor["status"] == "existing_customer"
    assert harbor["email"] is None


def test_rewrite_then_verify_and_unsourced_stays_flagged():
    batch_id, _ = _batch(
        [
            _base_row(company="Drafty Tools", company_city="Lima", person_city="Lima", email="ada@drafty.example", first_name="Ada"),
            _base_row(company="Unsourced Metals", company_city="Lima", person_city="Lima", email="ada@unsourced.example", first_name="Ada"),
        ]
    )
    companies = {company["name"]: company for company in db.list_companies(batch_id)}
    process_company(companies["Drafty Tools"]["id"])
    process_company(companies["Unsourced Metals"]["id"])

    drafty = db.get_company(companies["Drafty Tools"]["id"])
    assert drafty["status"] == "verified"
    assert drafty["email"]["attempts"] >= 2
    assert "synergy" not in drafty["email"]["body"].lower()

    unsourced = db.get_company(companies["Unsourced Metals"]["id"])
    assert unsourced["status"] == "needs_review"
    assert unsourced["email"]["status"] == "needs_review"
    assert any(claim["label"] == "UNVERIFIED" and "999" in claim["claim"] for claim in unsourced["claims"])
