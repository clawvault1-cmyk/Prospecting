from pathlib import Path

from app.ingest import rows_from_path, rows_from_upload
from app.scoring import parse_employees, score_rows
from openpyxl import Workbook

FIXTURE = Path(__file__).parent / "fixtures" / "fake_zoominfo.csv"


def _by_name(companies):
    return {company["name"]: company for company in companies}


def test_fixture_scores_ohio_industry_and_persona():
    companies = score_rows(rows_from_path(FIXTURE))
    found = _by_name(companies)
    included = {name for name, company in found.items() if company["included"]}
    excluded = {name for name, company in found.items() if not company["included"]}

    assert included == {
        "Northline Distribution",
        "Redhook Parts",
        "Cedar & Pine Retail",
        "Pinnacle Logistics",
        "Harborline Foods",
        "Little Bolt Co",
        "Millwright Goods",
    }
    assert excluded == {"Summit Software", "Gulf Marine Supply"}
    assert "Blank" not in found

    northline = found["Northline Distribution"]
    primary = northline["contacts"][0]
    assert primary["is_primary"]
    assert primary["first_name"] == "Maya"
    assert primary["email"] == "maya.chen@northline.example"
    assert "Fixture" not in northline["score_notes"]
    assert northline["facility_city"] == "Columbus"

    redhook = found["Redhook Parts"]
    assert redhook["contacts"][0]["first_name"] == "Luis"
    assert "parts" in redhook["industry_tags"]
    assert "dc" in redhook["industry_tags"]

    pinnacle = found["Pinnacle Logistics"]
    assert pinnacle["contacts"][0]["first_name"] == "Samir"
    assert pinnacle["state"] == "Kentucky"
    assert pinnacle["facility_city"] == "Cincinnati"
    assert "Ohio" in pinnacle["ohio_via"]

    millwright = found["Millwright Goods"]
    assert millwright["contacts"][0]["first_name"] == "Noah"
    assert millwright["contacts"][0]["email"] == ""

    assert "outside Ohio" in found["Gulf Marine Supply"]["exclude_reason"]
    assert "Industry" in found["Summit Software"]["exclude_reason"]

    ranks = [company["rank_score"] for company in companies if company["included"]]
    assert found["Little Bolt Co"]["rank_score"] == min(ranks)
    assert found["Redhook Parts"]["rank_score"] > found["Little Bolt Co"]["rank_score"]


def test_employee_range_and_ohio_abbreviation():
    assert parse_employees("", "Employees.250to499") == 250
    assert parse_employees("", "Employees.10000plus") == 10000
    assert parse_employees("410", "Employees.250to499") == 410
    companies = score_rows(
        [
            {
                "company": "Abbrev Goods",
                "company_state": "OH",
                "company_city": "Akron",
                "employees": "",
                "employee_range": "Employees.250to499",
                "revenue_000s": "30000",
                "primary_industry": "Manufacturing",
                "first_name": "Rita",
                "last_name": "Cole",
                "title": "Warehouse Supervisor",
                "management_level": "",
                "email": "rita@abbrev.example",
                "person_state": "OH",
                "person_city": "Akron",
            }
        ]
    )
    company = companies[0]
    assert company["included"]
    assert company["employees"] == 250
    assert company["contacts"][0]["persona_score"] > 40


def test_xlsx_matches_csv_shape():
    rows = rows_from_path(FIXTURE)
    book = Workbook()
    sheet = book.active
    headers = list(rows[0].keys())
    # Rebuild a sheet from the original file so headers match ZoomInfo names.
    import csv

    with FIXTURE.open(encoding="utf-8") as handle:
        reader = csv.reader(handle)
        original_headers = next(reader)
        original_rows = list(reader)
    sheet.append(original_headers)
    for original in original_rows:
        sheet.append(original)
    from io import BytesIO

    buffer = BytesIO()
    book.save(buffer)
    xlsx_rows = rows_from_upload("list.xlsx", buffer.getvalue())
    assert len(xlsx_rows) == len(rows)
    assert xlsx_rows[0]["company"] == "Northline Distribution"
    assert xlsx_rows[0]["email"] == "maya.chen@northline.example"
    assert "company_street" not in xlsx_rows[0]
    assert headers  # mapped keys exist on the csv path
    assert "company" in rows[0]
