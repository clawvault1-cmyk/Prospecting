"""SQLite storage. A process-wide lock keeps the worker and the web process from colliding."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_lock = threading.RLock()
_path: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  created_at TEXT NOT NULL,
  company_count INTEGER NOT NULL DEFAULT 0,
  included_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  website TEXT,
  city TEXT,
  state TEXT,
  country TEXT,
  facility_city TEXT,
  ohio_via TEXT,
  revenue_000s INTEGER,
  revenue_range TEXT,
  employees INTEGER,
  employee_range TEXT,
  primary_industry TEXT,
  primary_sub_industry TEXT,
  all_industries TEXT,
  industry_tags TEXT,
  fit_score REAL,
  rank_score REAL,
  score_notes TEXT,
  included INTEGER NOT NULL DEFAULT 0,
  exclude_reason TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  step TEXT NOT NULL DEFAULT '',
  error TEXT,
  existing_customer INTEGER NOT NULL DEFAULT 0,
  existing_customer_note TEXT,
  detected_tech TEXT,
  FOREIGN KEY (batch_id) REFERENCES batches(id)
);

CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  first_name TEXT,
  last_name TEXT,
  title TEXT,
  email TEXT,
  management_level TEXT,
  job_function TEXT,
  department TEXT,
  person_city TEXT,
  person_state TEXT,
  persona_score REAL,
  persona_notes TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  query_id TEXT,
  query TEXT,
  title TEXT,
  url TEXT,
  snippet TEXT,
  published TEXT,
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL UNIQUE,
  contact_id INTEGER,
  subject TEXT,
  body TEXT,
  followup_subject TEXT,
  followup_body TEXT,
  trigger_source_url TEXT,
  proof_point_id TEXT,
  status TEXT,
  validation_json TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  section TEXT,
  claim TEXT,
  label TEXT,
  source_url TEXT,
  source_quote TEXT,
  attempt INTEGER,
  FOREIGN KEY (company_id) REFERENCES companies(id)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def set_path(path: Path) -> None:
    global _path
    path.parent.mkdir(parents=True, exist_ok=True)
    _path = path


def get_path() -> Path:
    if _path is None:
        raise RuntimeError("Database is not initialized")
    return _path


def init_db(path: Path | None = None) -> None:
    if path is None:
        from app.settings import get_settings

        path = Path(get_settings().data_dir) / "app.db"
    set_path(path)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = sqlite3.connect(get_path(), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _parse_company(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("industry_tags", "detected_tech"):
        raw = data.get(key) or "[]"
        try:
            data[key] = json.loads(raw)
        except json.JSONDecodeError:
            data[key] = []
    return data


def _parse_email(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    raw = data.get("validation_json") or "{}"
    try:
        data["validation"] = json.loads(raw)
    except json.JSONDecodeError:
        data["validation"] = {}
    return data


def insert_batch(filename: str, companies: list[dict]) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO batches (filename, created_at, company_count, included_count) VALUES (?, ?, ?, ?)",
            (
                filename,
                utcnow(),
                len(companies),
                sum(1 for company in companies if company["included"]),
            ),
        )
        batch_id = int(cur.lastrowid)
        for company in companies:
            company_id = _insert_company(conn, batch_id, company)
            for contact in company["contacts"]:
                _insert_contact(conn, company_id, contact)
        return batch_id


def _insert_company(conn: sqlite3.Connection, batch_id: int, company: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO companies (
          batch_id, name, website, city, state, country, facility_city, ohio_via,
          revenue_000s, revenue_range, employees, employee_range, primary_industry,
          primary_sub_industry, all_industries, industry_tags, fit_score, rank_score,
          score_notes, included, exclude_reason, status, step
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '')
        """,
        (
            batch_id,
            company["name"],
            company.get("website") or "",
            company.get("city") or "",
            company.get("state") or "",
            company.get("country") or "",
            company.get("facility_city") or "",
            company.get("ohio_via") or "",
            company.get("revenue_000s"),
            company.get("revenue_range") or "",
            company.get("employees"),
            company.get("employee_range") or "",
            company.get("primary_industry") or "",
            company.get("primary_sub_industry") or "",
            company.get("all_industries") or "",
            json.dumps(company.get("industry_tags") or []),
            company.get("fit_score") or 0,
            company.get("rank_score") or 0,
            company.get("score_notes") or "",
            1 if company.get("included") else 0,
            company.get("exclude_reason") or "",
        ),
    )
    return int(cur.lastrowid)


def _insert_contact(conn: sqlite3.Connection, company_id: int, contact: dict) -> None:
    conn.execute(
        """
        INSERT INTO contacts (
          company_id, first_name, last_name, title, email, management_level,
          job_function, department, person_city, person_state, persona_score,
          persona_notes, is_primary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            contact.get("first_name") or "",
            contact.get("last_name") or "",
            contact.get("title") or "",
            contact.get("email") or "",
            contact.get("management_level") or "",
            contact.get("job_function") or "",
            contact.get("department") or "",
            contact.get("person_city") or "",
            contact.get("person_state") or "",
            contact.get("persona_score") or 0,
            contact.get("persona_notes") or "",
            1 if contact.get("is_primary") else 0,
        ),
    )


def list_batches() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM batches ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def get_batch(batch_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    return dict(row) if row else None


def list_companies(batch_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM companies WHERE batch_id = ? ORDER BY included DESC, rank_score DESC, id",
            (batch_id,),
        ).fetchall()
        companies = []
        for row in rows:
            company = _parse_company(row)
            contact = conn.execute(
                "SELECT * FROM contacts WHERE company_id = ? AND is_primary = 1 ORDER BY id LIMIT 1",
                (company["id"],),
            ).fetchone()
            company["primary_contact"] = dict(contact) if contact else None
            companies.append(company)
        return companies


def get_company(company_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        company = _parse_company(row)
        if not company:
            return None
        contacts = conn.execute(
            "SELECT * FROM contacts WHERE company_id = ? ORDER BY is_primary DESC, persona_score DESC, id",
            (company_id,),
        ).fetchall()
        sources = conn.execute(
            "SELECT * FROM sources WHERE company_id = ? ORDER BY id",
            (company_id,),
        ).fetchall()
        email = conn.execute("SELECT * FROM emails WHERE company_id = ?", (company_id,)).fetchone()
        claims = conn.execute(
            "SELECT * FROM claims WHERE company_id = ? ORDER BY id",
            (company_id,),
        ).fetchall()
    company["contacts"] = [dict(item) for item in contacts]
    company["primary_contact"] = next((item for item in company["contacts"] if item["is_primary"]), None)
    company["sources"] = [dict(item) for item in sources]
    company["email"] = _parse_email(email)
    company["claims"] = [dict(item) for item in claims]
    return company


def set_progress(company_id: int, status: str, step: str, error: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE companies SET status = ?, step = ?, error = ? WHERE id = ?",
            (status, step, error, company_id),
        )


def mark_queued(company_ids: list[int]) -> list[int]:
    if not company_ids:
        return []
    queued: list[int] = []
    with connect() as conn:
        for company_id in company_ids:
            row = conn.execute(
                "SELECT included, status FROM companies WHERE id = ?",
                (company_id,),
            ).fetchone()
            if not row or not row["included"]:
                continue
            if row["status"] in {"queued", "researching", "writing", "fact_checking", "rewriting"}:
                queued.append(company_id)
                continue
            conn.execute(
                "UPDATE companies SET status = 'queued', step = 'Waiting', error = '' WHERE id = ?",
                (company_id,),
            )
            queued.append(company_id)
    return queued


def claim_next() -> int | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM companies
            WHERE status = 'queued'
            ORDER BY rank_score DESC, id
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        cur = conn.execute(
            """
            UPDATE companies
            SET status = 'researching', step = 'Starting', error = ''
            WHERE id = ? AND status = 'queued'
            """,
            (row["id"],),
        )
        if cur.rowcount != 1:
            return None
        return int(row["id"])


def replace_sources(company_id: int, sources: list[dict]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sources WHERE company_id = ?", (company_id,))
        for source in sources:
            conn.execute(
                """
                INSERT INTO sources (company_id, query_id, query, title, url, snippet, published)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_id,
                    source.get("query_id") or "",
                    source.get("query") or "",
                    source.get("title") or "",
                    source.get("url") or "",
                    source.get("snippet") or "",
                    source.get("published") or "",
                ),
            )


def save_research_flags(
    company_id: int,
    *,
    existing_customer: bool,
    note: str,
    detected_tech: list[str],
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE companies
            SET existing_customer = ?, existing_customer_note = ?, detected_tech = ?
            WHERE id = ?
            """,
            (1 if existing_customer else 0, note, json.dumps(detected_tech), company_id),
        )


def save_email(
    company_id: int,
    contact_id: int | None,
    draft: dict,
    claims: list[dict],
    validation: dict,
    attempts: int,
) -> None:
    status = draft.get("status") or "needs_review"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO emails (
              company_id, contact_id, subject, body, followup_subject, followup_body,
              trigger_source_url, proof_point_id, status, validation_json, attempts, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
              contact_id = excluded.contact_id,
              subject = excluded.subject,
              body = excluded.body,
              followup_subject = excluded.followup_subject,
              followup_body = excluded.followup_body,
              trigger_source_url = excluded.trigger_source_url,
              proof_point_id = excluded.proof_point_id,
              status = excluded.status,
              validation_json = excluded.validation_json,
              attempts = excluded.attempts,
              updated_at = excluded.updated_at
            """,
            (
                company_id,
                contact_id,
                draft.get("subject") or "",
                draft.get("body") or "",
                draft.get("followup_subject") or "",
                draft.get("followup_body") or "",
                draft.get("trigger_source_url") or "",
                draft.get("proof_point_id") or "",
                status,
                json.dumps(validation),
                attempts,
                utcnow(),
            ),
        )
        conn.execute("DELETE FROM claims WHERE company_id = ?", (company_id,))
        for claim in claims:
            conn.execute(
                """
                INSERT INTO claims (company_id, section, claim, label, source_url, source_quote, attempt)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_id,
                    claim.get("section") or "",
                    claim.get("claim") or "",
                    claim.get("label") or "",
                    claim.get("source_url") or "",
                    claim.get("source_quote") or "",
                    attempts,
                ),
            )


def list_export_rows(batch_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
              c.id AS company_id,
              e.subject, e.body, e.followup_subject, e.followup_body,
              e.trigger_source_url, e.proof_point_id, e.status AS email_status,
              c.name AS company, c.facility_city, c.status AS company_status,
              c.existing_customer,
              ct.first_name, ct.last_name, ct.email, ct.title
            FROM companies c
            LEFT JOIN emails e ON e.company_id = c.id
            LEFT JOIN contacts ct ON ct.company_id = c.id AND ct.is_primary = 1
            WHERE c.batch_id = ?
              AND c.status NOT IN ('pending', 'queued')
              AND c.existing_customer = 0
            ORDER BY c.rank_score DESC, c.id
            """,
            (batch_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_claims(company_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM claims WHERE company_id = ? ORDER BY id",
            (company_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def batch_has_active(batch_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM companies
            WHERE batch_id = ?
              AND status IN ('queued', 'researching', 'writing', 'fact_checking', 'rewriting')
            """,
            (batch_id,),
        ).fetchone()
    return bool(row["n"])
