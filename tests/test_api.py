import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.jobs import ensure_worker
from app.main import app
from app.settings import get_settings

FIXTURE = Path(__file__).parent / "fixtures" / "fake_zoominfo.csv"


def test_login_upload_process_and_export():
    client = TestClient(app)
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/login"

    bad = client.post("/login", data={"password": "nope"}, follow_redirects=False)
    assert bad.status_code == 401

    good = client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert good.status_code == 303

    demo = client.post("/demo", follow_redirects=False)
    assert demo.status_code == 303
    batch_url = demo.headers["location"]
    page = client.get(batch_url)
    assert page.status_code == 200
    assert "Northline Distribution" in page.text
    assert "Summit Software" in page.text
    assert "100 Fixture Lane" not in page.text

    companies = db.list_companies(int(batch_url.rsplit("/", 1)[-1]))
    chosen = [str(company["id"]) for company in companies if company["name"] in {"Northline Distribution", "Harborline Foods"}]
    processed = client.post(f"{batch_url}/process", data={"company_ids": chosen}, follow_redirects=False)
    assert processed.status_code == 303
    results = client.get(processed.headers["location"])
    assert "Verified" in results.text or "verified" in results.text
    assert "Existing" in results.text or "existing" in results.text

    batch_id = batch_url.rsplit("/", 1)[-1]
    sheet = client.get(f"/batches/{batch_id}/export.xlsx")
    assert sheet.status_code == 200
    assert sheet.content[:2] == b"PK"
    doc = client.get(f"/batches/{batch_id}/export.docx")
    assert doc.status_code == 200
    assert doc.content[:2] == b"PK"

    north = next(company for company in db.list_companies(int(batch_id)) if company["name"] == "Northline Distribution")
    editor = client.get(f"/companies/{north['id']}")
    assert "Fact check" in editor.text
    saved = client.post(
        f"/companies/{north['id']}",
        data={
            "subject": north and "bad Subject",
            "body": "I would love 15 minutes for a quick call about synergy.",
            "followup_subject": "hello there",
            "followup_body": "Just checking in with a meeting.",
            "trigger_source_url": "https://example.com/not-a-source",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    updated = db.get_company(north["id"])
    assert updated["email"]["status"] == "needs_review"


def test_background_worker_finishes(monkeypatch):
    monkeypatch.setenv("JOBS_SYNC", "0")
    get_settings.cache_clear()
    from app.scoring import score_rows

    batch_id = db.insert_batch(
        "one.csv",
        score_rows(
            [
                {
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
                    "email": "maya.chen@northline.example",
                    "person_state": "Ohio",
                    "person_city": "Columbus",
                }
            ]
        ),
    )
    company_id = db.list_companies(batch_id)[0]["id"]
    db.mark_queued([company_id])
    ensure_worker()
    status = ""
    for _ in range(50):
        status = db.get_company(company_id)["status"]
        if status in {"verified", "needs_review", "existing_customer", "error"}:
            break
        time.sleep(0.05)
    assert status == "verified"
