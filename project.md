# PR Agent — Complete Project Reference

## What Is This?

**PR Agent** is a webhook-driven pull/merge request risk analysis service. When a developer opens or updates a PR on GitHub or GitLab, a webhook fires at this service, which runs an 8-stage analysis pipeline, computes a risk score (0–100), generates an AI-written summary, optionally posts inline review comments, and stores everything in SQLite. Clients query a REST API for the results.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI + Uvicorn |
| Data validation | Pydantic v2 + pydantic-settings |
| HTTP client | httpx (async) |
| LLM integration | litellm (multi-provider), langchain, langgraph (listed; not actively used) |
| GitHub SDK | PyGithub (stub only; pipeline uses httpx directly) |
| Database | SQLite via stdlib `sqlite3` |
| Config | python-dotenv + pydantic-settings |
| LLM providers | OpenAI GPT-4o, Anthropic Claude, Google Gemini, Ollama |
| Monitoring (wired) | prometheus-client, redis (in requirements; not connected) |

---

## Directory Structure

```
pr-agent/
├── app/
│   ├── main.py                   # FastAPI app, lifespan, routers, /health, /dashboard
│   ├── config.py                 # All settings via pydantic-settings + .env
│   ├── database.py               # SQLite schema creation + CRUD helpers
│   ├── schemas.py                # Pydantic response models
│   ├── scoring.py                # Risk scoring engine (0–100)
│   ├── rules_loader.py           # Rule resolution: DB → file → hardcoded defaults
│   ├── llm_agents.py             # LLM provider selection + LLMAgent class (litellm)
│   ├── github_client.py          # Async GitHub REST client (httpx)
│   ├── gitlab_client.py          # Async GitLab REST client (httpx)
│   ├── connectors/
│   │   └── github_connector.py   # PyGithub stub (not used by pipeline)
│   ├── orchestrator/
│   │   └── workflow.py           # PROrchestrator stub (minimal placeholder)
│   ├── routers/
│   │   ├── webhooks.py           # POST /webhooks/github and /webhooks/gitlab
│   │   └── analysis.py           # GET /pr-analysis/... endpoints
│   ├── pr_pipeline/
│   │   ├── graph.py              # run_pr_pipeline(): sequential node runner
│   │   ├── state.py              # All Pydantic state models shared across nodes
│   │   └── nodes/
│   │       ├── ingest.py         # Stage 1 — validate + filter webhook event
│   │       ├── metadata.py       # Stage 2 — collect PR metadata via API
│   │       ├── diff.py           # Stage 3 — extract file diffs via API
│   │       ├── rules.py          # Stage 4 — load scoring rules
│   │       ├── risk.py           # Stage 5 — compute risk score
│   │       ├── llm_summary.py    # Stage 6 — generate AI summary
│   │       ├── review_comments.py # Stage 7 — generate + optionally post review comments
│   │       └── persist.py        # Stage 8 — write results to SQLite
│   └── static/
│       └── dashboard.html        # Live pipeline status dashboard (served at /dashboard)
├── rules/
│   ├── default_rules.json        # Default scoring rules + review patterns
│   └── review_guidelines.md      # Guidelines fed to LLM reviewer
├── requirements.txt
├── sample_env.txt
├── README.md
├── SETUP.md
└── SUMMARY.md
```

---

## 8-Stage Pipeline

Each stage is a class with `async def run(state) -> state`. Stages run sequentially in `graph.py`.

| # | Node class | What it does |
|---|---|---|
| 1 | `IngestWebhookNode` | Validates HMAC/secret, ignores non-PR events; only processes `opened`, `synchronize`, `reopened` (GitHub) or `open`, `update`, `reopen` (GitLab) |
| 2 | `CollectMetadataNode` | Parses webhook for owner/repo/PR number/author/SHAs/counts; enriches via API call |
| 3 | `ExtractDiffsNode` | Fetches changed files + patches via API (paginated); stores up to 12 KB of patch per file |
| 4 | `LoadRulesNode` | Resolves rules: DB repo-specific override → `default_rules.json` → hardcoded defaults |
| 5 | `CalculateRiskNode` | Runs scoring engine → score (0–100), level, per-rule findings |
| 6 | `GenerateLLMSummaryNode` | Calls LLM for a 2-sentence risk summary |
| 7 | `GenerateReviewCommentsNode` | Matches regex patterns against added lines; calls LLM for narrative review; posts review comments back to GitHub/GitLab when `POST_COMMENTS_ENABLED=true` |
| 8 | `PersistResultNode` | Inserts rows into `pr_analyses`, `pr_findings`, `pr_pipeline_events` |

---

## Risk Scoring Engine (`app/scoring.py`)

Score starts at 0. Each triggered rule adds points:

| Rule | Points | Trigger condition |
|---|---|---|
| `high_file_count` | +15 | files changed ≥ 20 |
| `high_churn` | +15 | (additions + deletions) ≥ 800 |
| `sensitive_paths` | +25 | any file starts with `auth/`, `security/`, `payments/`, `infra/`, `.github/workflows/` |
| `no_tests_changed` | +15 | non-test files changed but no test file detected |

**Risk levels:** 0–24 = low · 25–49 = medium · 50–74 = high · 75+ = critical

---

## LLM Auto-Selection (`app/llm_agents.py`)

When `LLM_PROVIDER` is not pinned, provider is chosen per-PR:

1. **Claude** — `critical` or `high` risk PRs
2. **Gemini** — large PRs (≥ 20 files or ≥ 800 churn lines)
3. **OpenAI** — default fallback

All calls go through `litellm.acompletion()`.

---

## Database Schema (SQLite)

| Table | Purpose |
|---|---|
| `pr_events` | Raw webhook deliveries; idempotent via `INSERT OR IGNORE` on `(provider, delivery_id)` |
| `pr_analyses` | Computed risk results per PR (score, level, summary, SHAs, counts) |
| `pr_findings` | Individual rule violations linked to an analysis |
| `repo_rules` | Per-repo rule overrides (unique on `owner+repo`) |
| `pr_pipeline_events` | Ordered stage-by-stage execution trail for observability |

Schema migrations applied at startup via `_ensure_provider_schema()`.

---

## REST API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service status + config summary |
| GET | `/dashboard` | Live HTML pipeline status dashboard |
| POST | `/webhooks/github` | Receive GitHub webhook → async pipeline (202) |
| POST | `/webhooks/gitlab` | Receive GitLab webhook → async pipeline (202) |
| GET | `/pr-analysis/recent` | Last N pipeline run summaries |
| GET | `/pr-analysis/events/{delivery_id}` | Pipeline stage trail by webhook delivery ID |
| GET | `/pr-analysis/{owner}/{repo}/{pr_number}` | Latest analysis for a PR |
| GET | `/pr-analysis/{owner}/{repo}/{pr_number}/events` | Pipeline stage trail for a PR |
| GET | `/pr-analysis/{analysis_id}` | Analysis by DB primary key |

---

## Environment Variables

All loaded from `.env` via pydantic-settings. Copy `sample_env.txt` to `.env` to start.

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8010` | Server port |
| `GITHUB_WEBHOOK_SECRET` | `""` | HMAC-SHA256 secret for `X-Hub-Signature-256` header |
| `GITHUB_API_TOKEN` | `""` | GitHub PAT for metadata + diff API calls |
| `GITHUB_API_BASE_URL` | `https://api.github.com` | GitHub API base |
| `GITLAB_WEBHOOK_SECRET` | `""` | Shared secret for `X-Gitlab-Token` header |
| `GITLAB_API_TOKEN` | `""` | GitLab PAT for metadata + diff API calls |
| `GITLAB_API_BASE_URL` | `https://gitlab.com/api/v4` | GitLab API base |
| `DATABASE_PATH` | `./data/pr_agent.db` | SQLite file location (auto-created) |
| `DEFAULT_RULES_FILE` | `./rules/default_rules.json` | Fallback scoring rules |
| `REVIEW_GUIDELINES_FILE` | `./rules/review_guidelines.md` | LLM review guidelines |
| `POST_COMMENTS_ENABLED` | `false` | Post review comments back to GitHub/GitLab |
| `MAX_INLINE_COMMENTS` | `0` | Max inline rule-hit comments per review (`0` = unlimited) |
| `REVIEW_MIN_INLINE_SEVERITY` | `medium` | Minimum severity required before a comment is posted inline |
| `LLM_PROVIDER` | `openai` | Pin LLM: `openai`, `claude`, `gemini`, or auto-select |
| `LLM_TIMEOUT_SECONDS` | `30` | LLM request timeout |
| `OPENAI_API_KEY` | `""` | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `ANTHROPIC_API_KEY` | `""` | Anthropic API key |
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20241022` | Claude model |
| `GEMINI_API_KEY` | `""` | Gemini API key |
| `GEMINI_MODEL` | `gemini/gemini-1.5-pro` | Gemini model |
| `OLLAMA_ENABLED` | `false` | Enable local Ollama |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `ollama/llama3` | Ollama model |

---

## How to Run

```bash
# Python 3.13+ required
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp sample_env.txt .env             # then edit .env
# Minimum: set GITHUB_API_TOKEN and GITHUB_WEBHOOK_SECRET

uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload

# Verify
curl http://127.0.0.1:8010/health
```

SQLite DB is auto-created at `./data/pr_agent.db` on first start.

---

## Rules Configuration (`rules/default_rules.json`)

Five sections:

| Section | Purpose |
|---|---|
| `weights` | Point values per risk factor |
| `thresholds` | Numeric risk-level boundaries |
| `sensitive_path_prefixes` | Path prefixes that trigger the sensitive-paths check |
| `test_path_markers` | Substrings identifying test files (e.g. `test`, `tests`, `spec`) |
| `review_patterns` | Regex rules for inline comment generation |

**Built-in review patterns:** `debug_print`, `todo_marker`, `hardcoded_secret` (high), `bare_except`, `wildcard_import`, `debugger_stmt`

Per-repo rule overrides can be stored in the `repo_rules` DB table and take precedence over the JSON file.

---

## Key Design Decisions & Known Gaps

| Topic | Detail |
|---|---|
| **No external queue** | Webhooks processed via `asyncio.create_task()` — tasks are lost on server restart |
| **LangGraph not active** | Imported as a dependency but `graph.py` runs a plain sequential loop; no DAG |
| **`github_connector.py` is a stub** | PyGithub wrapper not wired into the pipeline; pipeline uses `github_client.py` (httpx) |
| **Redis + Prometheus** | In `requirements.txt` but not connected to active code |
| **PostgreSQL listed but unused** | `psycopg2-binary` installed; all persistence uses stdlib `sqlite3` |
| **Graceful degradation** | Every API + LLM call has try/except; pipeline continues on failure with a warning event |
| **CORS** | Wide open (`allow_origins=["*"]`) — tighten for production |

---

## Data Flow (End-to-End)

```
GitHub/GitLab webhook
        │
        ▼
POST /webhooks/{provider}
  └─ Validate secret (HMAC-SHA256 or shared token)
  └─ Immediately return 202 WebhookAck
  └─ asyncio.create_task(run_pr_pipeline(state))
                │
                ▼
        8-stage pipeline
          1. Ingest  →  filter non-PR / unsupported actions
          2. Metadata →  owner, repo, PR#, author, SHA, counts
          3. Diffs    →  file patches (up to 12 KB each)
          4. Rules    →  load scoring rules
          5. Risk     →  score 0–100, level, findings
          6. LLM summary → 2-sentence AI write-up
          7. Review comments → regex + LLM; optionally post to GitLab
          8. Persist  →  SQLite: pr_analyses, pr_findings, pr_pipeline_events
                │
                ▼
        GET /pr-analysis/{owner}/{repo}/{pr_number}
          └─ returns score, level, summary, findings, timestamps
```
