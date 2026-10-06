"""Ohio Desk web app."""

from __future__ import annotations

import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import db
from app.exporters import build_export_records, document_bytes, workbook_bytes
from app.ingest import rows_from_upload
from app.jobs import ensure_worker, stop_worker
from app.pipeline import process_company, rescore_saved_email
from app.scoring import score_rows
from app.settings import ROOT, get_settings

log = logging.getLogger("ohio_desk")
TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))
DEMO_FIXTURE = ROOT / "tests" / "fixtures" / "fake_zoominfo.csv"
MAX_UPLOAD = 8 * 1024 * 1024


class NeedsLogin(Exception):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    settings = get_settings()
    if not settings.jobs_sync:
        ensure_worker()
    yield
    stop_worker()


app = FastAPI(title="Ohio Desk", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


def _install_middleware() -> None:
    # Session middleware must wrap the app so request.session exists.
    settings = get_settings()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret,
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 12,
    )


_install_middleware()


@app.exception_handler(NeedsLogin)
async def _needs_login(request: Request, exc: NeedsLogin):
    if request.url.path.startswith("/api"):
        return Response('{"detail":"auth required"}', status_code=401, media_type="application/json")
    return RedirectResponse("/login", status_code=303)


def require_session(request: Request) -> None:
    if not request.session.get("ok"):
        raise NeedsLogin()


def _password_ok(guess: str) -> bool:
    expected = get_settings().app_password
    if not expected:
        return False
    actual = hashlib.sha256(guess.encode()).digest()
    stored = hashlib.sha256(expected.encode()).digest()
    return hmac.compare_digest(actual, stored)


def _mode() -> dict:
    settings = get_settings()
    search = settings.search_mode
    writer = settings.llm_mode
    if search == "mock" and writer == "mock":
        label = "Mock mode"
        detail = "No API keys in use. Research snippets and drafts are simulated, then run through the same checks as a live draft."
    elif search == "mock" or writer == "mock":
        label = "Mixed mode"
        detail = f"Search is {search}. Writer is {writer}. The missing side is simulated."
    else:
        model = settings.anthropic_model if writer == "anthropic" else settings.openai_model
        label = "Live mode"
        detail = f"Search is Tavily. Writer is {writer} ({model})."
    return {"label": label, "detail": detail, "search": search, "writer": writer}


def _render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("mode", _mode())
    context.setdefault("request", request)
    return TEMPLATES.TemplateResponse(request, name, context, status_code=status_code)


def _import(filename: str, payload: bytes) -> int:
    rows = rows_from_upload(filename, payload)
    companies = score_rows(rows)
    if not companies:
        raise ValueError("No company rows found. Check that the file has a Company Name column.")
    return db.insert_batch(filename, companies)


@app.get("/health")
def health():
    settings = get_settings()
    return {"ok": True, "search": settings.search_mode, "writer": settings.llm_mode}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("ok"):
        return RedirectResponse("/", status_code=303)
    missing = not get_settings().app_password
    return _render(request, "login.html", missing=missing, error="")


@app.post("/login")
def login_submit(request: Request, password: str = Form("")):
    if _password_ok(password):
        request.session["ok"] = True
        return RedirectResponse("/", status_code=303)
    missing = not get_settings().app_password
    error = "Set APP_PASSWORD before signing in." if missing else "That password does not match."
    return _render(request, "login.html", status_code=401, missing=missing, error=error)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    require_session(request)
    return _render(request, "home.html", batches=db.list_batches(), error=request.query_params.get("error", ""))


@app.post("/batches")
async def upload_batch(request: Request, file: UploadFile = File(...)):
    require_session(request)
    filename = file.filename or "upload.csv"
    payload = await file.read()
    if len(payload) > MAX_UPLOAD:
        return RedirectResponse("/?error=File+is+larger+than+8+MB.", status_code=303)
    try:
        batch_id = _import(filename, payload)
    except Exception as exc:
        message = str(exc).replace(" ", "+")
        return RedirectResponse(f"/?error={message}", status_code=303)
    return RedirectResponse(f"/batches/{batch_id}", status_code=303)


@app.post("/demo")
def load_demo(request: Request):
    require_session(request)
    if not DEMO_FIXTURE.exists():
        return RedirectResponse("/?error=Demo+fixture+is+missing.", status_code=303)
    batch_id = _import(DEMO_FIXTURE.name, DEMO_FIXTURE.read_bytes())
    return RedirectResponse(f"/batches/{batch_id}", status_code=303)


@app.get("/batches/{batch_id}", response_class=HTMLResponse)
def batch_page(request: Request, batch_id: int):
    require_session(request)
    batch = db.get_batch(batch_id)
    if not batch:
        return RedirectResponse("/?error=That+list+was+not+found.", status_code=303)
    companies = db.list_companies(batch_id)
    included = [company for company in companies if company["included"]]
    excluded = [company for company in companies if not company["included"]]
    return _render(
        request,
        "batch.html",
        batch=batch,
        included=included,
        excluded=excluded,
        query_count=4,
        notice=request.query_params.get("notice", ""),
    )


@app.post("/batches/{batch_id}/process")
async def process_batch(request: Request, batch_id: int):
    require_session(request)
    form = await request.form()
    raw_ids = form.getlist("company_ids")
    company_ids = []
    for raw in raw_ids:
        try:
            company_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    owned = {company["id"] for company in db.list_companies(batch_id)}
    company_ids = [company_id for company_id in company_ids if company_id in owned]
    if not company_ids:
        return RedirectResponse(f"/batches/{batch_id}?notice=Select+at+least+one+company.", status_code=303)
    settings = get_settings()
    if settings.jobs_sync:
        for company_id in company_ids:
            db.mark_queued([company_id])
            claimed = db.claim_next()
            if claimed:
                process_company(claimed)
        return RedirectResponse(f"/batches/{batch_id}/results", status_code=303)
    db.mark_queued(company_ids)
    ensure_worker()
    return RedirectResponse(f"/batches/{batch_id}/progress", status_code=303)


@app.get("/batches/{batch_id}/progress", response_class=HTMLResponse)
def progress_page(request: Request, batch_id: int):
    require_session(request)
    batch = db.get_batch(batch_id)
    if not batch:
        return RedirectResponse("/", status_code=303)
    return _render(request, "progress.html", batch=batch)


@app.get("/api/batches/{batch_id}/progress")
def progress_api(request: Request, batch_id: int):
    require_session(request)
    companies = db.list_companies(batch_id)
    active = {"queued", "researching", "writing", "fact_checking", "rewriting"}
    payload = []
    for company in companies:
        if company["status"] == "pending":
            continue
        contact = company.get("primary_contact") or {}
        payload.append(
            {
                "id": company["id"],
                "name": company["name"],
                "status": company["status"],
                "step": company["step"],
                "error": company["error"] or "",
                "contact": " ".join(part for part in (contact.get("first_name"), contact.get("last_name")) if part),
            }
        )
    return {"done": not any(item["status"] in active for item in payload), "companies": payload}


@app.get("/batches/{batch_id}/results", response_class=HTMLResponse)
def results_page(request: Request, batch_id: int):
    require_session(request)
    batch = db.get_batch(batch_id)
    if not batch:
        return RedirectResponse("/", status_code=303)
    companies = [company for company in db.list_companies(batch_id) if company["status"] != "pending"]
    return _render(request, "results.html", batch=batch, companies=companies)


@app.get("/companies/{company_id}", response_class=HTMLResponse)
def company_page(request: Request, company_id: int):
    require_session(request)
    company = db.get_company(company_id)
    if not company:
        return RedirectResponse("/", status_code=303)
    return _render(request, "company.html", company=company, saved=request.query_params.get("saved", ""))


@app.post("/companies/{company_id}")
async def save_company(request: Request, company_id: int):
    require_session(request)
    form = await request.form()
    try:
        rescore_saved_email(
            company_id,
            {
                "subject": str(form.get("subject") or ""),
                "body": str(form.get("body") or ""),
                "followup_subject": str(form.get("followup_subject") or ""),
                "followup_body": str(form.get("followup_body") or ""),
                "trigger_source_url": str(form.get("trigger_source_url") or ""),
            },
        )
    except ValueError:
        return RedirectResponse(f"/companies/{company_id}", status_code=303)
    return RedirectResponse(f"/companies/{company_id}?saved=1", status_code=303)


@app.post("/companies/{company_id}/process")
def process_one(request: Request, company_id: int):
    require_session(request)
    company = db.get_company(company_id)
    if not company or not company["included"]:
        return RedirectResponse("/", status_code=303)
    settings = get_settings()
    if settings.jobs_sync:
        db.mark_queued([company_id])
        claimed = db.claim_next()
        if claimed:
            process_company(claimed)
        return RedirectResponse(f"/companies/{company_id}", status_code=303)
    db.mark_queued([company_id])
    ensure_worker()
    return RedirectResponse(f"/batches/{company['batch_id']}/progress", status_code=303)


def _export_bundle(batch_id: int):
    rows = db.list_export_rows(batch_id)
    records = build_export_records(rows)
    claims = []
    sources = []
    for row in rows:
        company = db.get_company(row["company_id"])
        claims.append(company["claims"] if company else [])
        sources.append(company["sources"] if company else [])
    return records, claims, sources


@app.get("/batches/{batch_id}/export.xlsx")
def export_xlsx(request: Request, batch_id: int):
    require_session(request)
    if not db.get_batch(batch_id):
        return RedirectResponse("/", status_code=303)
    records, _, _ = _export_bundle(batch_id)
    payload = workbook_bytes(records)
    return Response(
        payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="ohio-desk-batch-{batch_id}.xlsx"'},
    )


@app.get("/batches/{batch_id}/export.docx")
def export_docx(request: Request, batch_id: int):
    require_session(request)
    if not db.get_batch(batch_id):
        return RedirectResponse("/", status_code=303)
    records, claims, sources = _export_bundle(batch_id)
    payload = document_bytes(records, claims, sources)
    return Response(
        payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="ohio-desk-batch-{batch_id}.docx"'},
    )
