# Ohio Desk

Prospect research and cold-email drafts for an Ohio sales engineer at Toyota Automated Logistics (TAL, formerly Bastian Solutions).

Upload a ZoomInfo-style Excel or CSV export. The app keeps companies with an Ohio facility and a fit in manufacturing, distribution/wholesale, 3PL, retail/ecommerce, or parts, and ranks the best warehouse, distribution, logistics, supply chain, plant, or operations contact. You choose which companies to research. For each one it searches the web, writes a short plain-text email from those sources plus a fixed proof-point library, fact-checks every claim, and exports a mail-merge workbook and a Word document.

Without API keys the same path runs in **mock mode**: snippets and drafts are simulated, then the real validators and fact-check gate still run. That is the demo.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `APP_PASSWORD` in `.env` to a long password. Then:

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000, sign in, and choose **Load the fictional sample**. The sample uses ZoomInfo column names and invented people. Do not commit a real export.

Check the companies you want and click **Process selected**. In mock mode a company finishes in a second. With live keys, plan on one to two minutes each. The progress page updates on its own. Open a draft to edit it; saving runs the checks again. **Download Excel** or **Download Word** from the drafts page.

Existing Bastian/TAL customers found in research are skipped and left out of both exports. A draft that still has an unsourced claim is marked `needs review`. It is never exported as `verified`.

Tests:

```bash
pytest
```

## Environment

| Variable | Purpose |
| --- | --- |
| `APP_PASSWORD` | Shared password. Required. |
| `APP_SECRET` | Session cookie signing key. Defaults to the password. |
| `DATA_DIR` | Directory for the SQLite file. Default `data/`. |
| `LLM_PROVIDER` | `auto`, `openai`, `anthropic`, or `mock`. |
| `OPENAI_API_KEY` | Key for any OpenAI-compatible chat API. |
| `OPENAI_BASE_URL` | Default `https://api.openai.com/v1`. For xAI use `https://api.x.ai/v1`. |
| `OPENAI_MODEL` | Model id, for example `gpt-4o-mini` or a Grok model. |
| `OPENAI_JSON_MODE` | `true` asks for a JSON object. Set `false` if the endpoint rejects `response_format`. |
| `ANTHROPIC_API_KEY` | Used when `LLM_PROVIDER=anthropic`, or in `auto` when no OpenAI key is set. |
| `ANTHROPIC_MODEL` | Default `claude-sonnet-4-5`. |
| `SEARCH_PROVIDER` | `auto`, `tavily`, or `mock`. |
| `TAVILY_API_KEY` | Tavily search key. Sent as `Authorization: Bearer`. |
| `HTTP_TIMEOUT` | Seconds for search and model calls. Default 45. |
| `JOBS_SYNC` | Leave unset. `1` runs each company inside the web request (tests only). |

`auto` uses a live provider when its key is present and falls back to mock otherwise. Search and the writer can fall back independently. The banner on each page says which mode you are in.

## What the checks enforce

Rules live in config and are re-read for every company, so you can edit them without a restart.

- `config/system_prompt.md` — who TAL is, Ohio only, no invented facts, don't pitch equipment the prospect already runs.
- `config/email_rules.md` — reason, hedged problem, one proof point, one soft CTA. No meeting ask. Subject is 1–4 lowercase words with no numbers.
- `config/style.yaml` — word limits and the banned list. This is what the code enforces, and the same list is appended to the writer prompt.
- `config/factcheck_prompt.md` — instructions for the fact-check model.
- `config/proof_points.yaml` — the only proof the writer may use, with tags, source URLs, and an approved sentence. Polaris wording must stay SKU capacity, not storage capacity.
- `config/scoring.yaml` — Ohio, industry keywords, size tiers, and persona weights.
- `config/research.yaml` — the Tavily queries. `time_boxed` queries look back about 18 months. The automation query is not time-boxed, so an older install still shows up.
- `config/export_columns.yaml` — mail-merge headers, in order. `field` must be one of `first_name`, `last_name`, `full_name`, `email`, `title`, `company`, `subject`, `body`, `followup_subject`, `followup_body`, `trigger_source`, `status`, `proof_point`, `city`.

Body target is 60–90 words, hard cap 100. The day-3 follow-up is under 40 words. `status` in the workbook is exactly `verified` or `needs review`. Body cells keep real line breaks.

The fact-check model proposes claims. Code then requires every `VERIFIED` label to match a stored snippet or a proof-point wording, including every number. Anything still unverified after two rewrites stays `needs review`, and the claim table is kept on the review page and in the Word file.

## Deploy

Render is the right host. A company can take a minute or two, which does not fit a short serverless timeout, so this app is a long-running web process rather than a Vercel function.

`render.yaml` starts `uvicorn app.main:app --host 0.0.0.0 --port $PORT` and checks `/health`. Set `APP_PASSWORD`, `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`, and `TAVILY_API_KEY` in the Render dashboard. SQLite on the default disk disappears on redeploy. Mount a persistent disk and set `DATA_DIR` to that path (the blueprint uses `/var/data`).

Docker:

```bash
docker build -t ohio-desk .
docker run --env-file .env -p 8000:8000 ohio-desk
```

## Cost

Mock mode makes no paid calls.

Live mode sends the queries in `config/research.yaml` (four by default). Tavily's `advanced` depth is 2 credits per request. Then each company uses a draft call and a fact-check call, and up to two rewrites that each get another fact-check, so two to six chat calls. A small model is usually cents per company; a larger model costs more. Check current Tavily and model prices before running a long list. The review screen shows how many searches a selection will start, and nothing is searched until you click Process.

## Data

The password protects the whole app because the database holds names and emails. Exports are for your machine or a mail-merge folder, not for git. The fictional fixture at `tests/fixtures/fake_zoominfo.csv` is the only prospect file in the repo.
