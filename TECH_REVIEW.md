# Tech Lead Review — PR Agent

## Verdict First

The code is well-structured and readable. The pipeline abstraction is clean, validation is correct, and the node pattern makes stages easy to add. **But the current architecture has three production-blocking gaps** and carries dead dependencies that suggest the intended architecture was never finished. This document names the gaps, then compares five realistic approaches so you can choose what fits your scale and ops budget.

---

## What Is Actually Good

Before the critique: these decisions are solid and should be kept in any rewrite.

- **Pipeline as nodes** (`pr_pipeline/nodes/`) — each stage is self-contained, independently testable, and skips gracefully when status is `ignored/rejected`. This is the right abstraction.
- **HMAC validation** — `hmac.compare_digest` with proper constant-time comparison. Not an afterthought.
- **Idempotent webhook ingest** — `INSERT OR IGNORE` on `(provider, delivery_id)` means replayed webhooks are silently dropped. Correct.
- **Multi-provider LLM via litellm** — provider-agnostic interface. The auto-selection logic (Claude for critical, Gemini for large, OpenAI as default) is a reasonable policy.
- **Pydantic state model** — `PRAgentState` gives the pipeline a typed, immutable-ish contract between stages. Much better than passing dicts.

---

## Critical Production Gaps

### Gap 1 — `asyncio.create_task()` is not a job queue

```python
# webhooks.py
asyncio.create_task(_process(envelope))
return WebhookAck(...)
```

`create_task` schedules the coroutine on the current event loop. If the server process restarts, crashes, or is killed by a deploy — the task is gone. No retry. No visibility until it completes. No dead-letter queue. In production, any webhook fired during a deploy or crash is silently lost.

**Risk:** Every deployment drops in-flight PR analyses with no indication to the caller.

---

### Gap 2 — New SQLite connection per operation

```python
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))  # opens every call
    ...
```

Every `insert_analysis`, `get_findings`, `insert_pipeline_events` opens and closes a fresh file handle. SQLite also serializes all writers — one write at a time across the entire database. Under 50 concurrent webhook deliveries, DB writes queue up and stage 8 becomes the bottleneck.

**Risk:** Under moderate load, persistence latency blows out LLM timeout budgets and the event loop stalls.

---

### Gap 3 — Dead dependencies that were never wired in

`requirements.txt` installs: `langgraph`, `langchain`, `SQLAlchemy`, `psycopg2-binary`, `redis`, `prometheus-client`, `PyGithub`.

None of these are used by the active code path. The pipeline is 8 sequential `await node.run(state)` calls — no graph. The DB layer uses stdlib `sqlite3` — no ORM. This tells you the intended architecture (LangGraph DAG, PostgreSQL via SQLAlchemy, Redis-backed job queue, Prometheus metrics) was designed but never built. The current code is a prototype running on a production-shaped skeleton.

**Risk:** ~400MB of unused packages on every deploy. Attack surface from unpatched dependencies. Confusion about what the system actually does.

---

## Secondary Issues

| Issue | Severity | Detail |
|---|---|---|
| CORS `allow_origins=["*"]` | Medium | Fine for local dev; must be locked down for production |
| No auth on GET endpoints | Medium | Anyone knowing the URL can read all PR analyses |
| Manual schema migrations | Low | `_ensure_provider_schema()` is hand-rolled; breaks under concurrent startup |
| No tests | High | No test files anywhere in the project |
| LLM has no fallback | Medium | If Claude rate-limits, that stage silently fails; no retry |
| Metadata + diff nodes are sequential | Low | Both make GitHub API calls; they could run in parallel |
| `asynccontextmanager` lifespan calls sync `init_db()` | Low | Blocks the event loop at startup; should be `run_in_executor` |

---

## Five Approaches Compared

---

### Approach A — Current: FastAPI + `asyncio.create_task` + SQLite

**Stack:** FastAPI · uvicorn · asyncio · stdlib sqlite3 · litellm

**How it works:** Webhook handler fires a background coroutine on the same event loop. SQLite stores results. REST API reads them.

```
Webhook → FastAPI → asyncio.create_task → 8-stage pipeline → SQLite
```

**Pros:**
- Zero infrastructure — runs with `uvicorn app.main:app`
- Fast to prototype and iterate
- No external services to configure

**Cons:**
- Tasks lost on restart or crash (no persistence before processing)
- SQLite write serialization bottleneck under concurrent load
- No retry on LLM failure or GitHub API rate limit
- Not horizontally scalable (SQLite is file-local)

**Fits when:** Single-server hobby project, internal tool with < 20 webhooks/hour, no uptime requirement.

---

### Approach B — FastAPI + ARQ + Redis + PostgreSQL

**Stack:** FastAPI · ARQ (async job queue) · Redis · PostgreSQL · SQLAlchemy · Alembic

**How it works:** Webhook handler enqueues a job to Redis immediately. ARQ workers pick up jobs and run the pipeline. PostgreSQL stores results. Multiple worker processes can run in parallel.

```
Webhook → FastAPI → Redis job queue → ARQ worker → 8-stage pipeline → PostgreSQL
                                    ↑
                              (retry on failure)
```

**Why ARQ over Celery:** ARQ is natively async (no threading overhead), lighter, and a natural fit for an async FastAPI codebase. Celery requires a sync bridge unless you use `celery[gevent]` or `celery[eventlet]`, which adds complexity.

**Pros:**
- Jobs survive server restarts (persisted in Redis before processing)
- Automatic retry with exponential backoff on failure
- Horizontally scalable — add more workers without changing the API
- PostgreSQL handles concurrent writes without serialization
- Alembic handles schema migrations safely

**Cons:**
- Requires Redis and PostgreSQL to be running (Docker Compose or managed services)
- Slightly more operational complexity than Approach A
- ARQ is less mature than Celery (smaller community)

**Infrastructure needed:** Redis (job queue), PostgreSQL (results), 1+ ARQ worker processes.

**Fits when:** Production system, team with basic infra (Docker Compose or k8s), expected volume > 50 webhooks/hour.

**Effort to migrate from current:** Medium. The 8 pipeline nodes stay identical. Replace `asyncio.create_task` with `await queue.enqueue(...)`. Swap `sqlite3` calls for SQLAlchemy models. Add Alembic for migrations.

---

### Approach C — Use LangGraph as Intended

**Stack:** FastAPI · LangGraph · ARQ · PostgreSQL

**How it works:** Replace the manual `await node.run(state)` loop in `graph.py` with a real LangGraph `StateGraph`. Define edges, conditional branches, and parallel execution. LangGraph handles the orchestration; the node classes stay the same.

```python
# graph.py (current — sequential manual loop)
state = await IngestWebhookNode().run(state)
state = await CollectMetadataNode().run(state)
state = await ExtractDiffsNode().run(state)
...

# graph.py (LangGraph — parallel where possible)
graph = StateGraph(PRAgentState)
graph.add_node("ingest", ingest_node)
graph.add_node("metadata", metadata_node)
graph.add_node("diff", diff_node)
graph.add_edge("ingest", ["metadata", "diff"])   # parallel API calls
graph.add_node("rules", rules_node)
graph.add_edge(["metadata", "diff"], "rules")    # fan-in
...
```

Metadata collection (Stage 2) and diff extraction (Stage 3) are both GitHub API calls with no data dependency between them. Running them in parallel cuts ~40–60% of wall-clock pipeline time for most PRs.

**Pros:**
- Parallel execution of independent stages (real latency win)
- Conditional edges (skip LLM stages if risk is low, reducing cost)
- Built-in checkpointing (pipeline can resume from a checkpoint after failure)
- LangGraph's LangSmith integration gives free observability for LLM calls
- Already a declared dependency — zero new packages

**Cons:**
- LangGraph API changes frequently (breaking changes between minor versions)
- Adds abstraction — harder to debug than a plain sequential loop
- Checkpointing requires a persistence backend (Redis or PostgreSQL)

**Fits when:** LLM call latency is a pain point, or you want to skip expensive LLM stages for low-risk PRs. Use alongside Approach B (ARQ for job durability, LangGraph for pipeline orchestration).

**Effort to migrate from current:** Low-Medium. Node classes are unchanged. Only `graph.py` is rewritten to define the StateGraph.

---

### Approach D — GitHub Actions (No Server)

**Stack:** GitHub Actions YAML · Python script · GitHub Checks API · DynamoDB or PlanetScale (optional)

**How it works:** No webhook server. A GitHub Actions workflow fires on `pull_request` events. The action runs the analysis script directly in the runner, then posts a Check Run result (with the risk score and findings) back to the PR.

```yaml
# .github/workflows/pr-analysis.yml
on: [pull_request]
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python analyze_pr.py
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

**Pros:**
- Zero infrastructure — no server, no DB, no queue
- GitHub handles scaling, retries, and availability
- Results posted as native GitHub Check Runs (visible in PR UI)
- Free for public repos; included minutes for private repos

**Cons:**
- GitHub-only — GitLab support requires a separate GitLab CI pipeline
- No central DB of historical analyses across repos
- Cold start latency (~15–30 seconds to spin up runner)
- Cannot post back to third-party systems easily
- Action minutes cost money at scale

**Fits when:** GitHub-only, single-platform, you don't need a queryable API or historical data, and you want zero ops overhead.

**Effort to migrate from current:** High — requires restructuring the pipeline to run as a CLI script rather than a server, but the scoring logic is reusable as-is.

---

### Approach E — Serverless (AWS Lambda + SQS + RDS)

**Stack:** AWS Lambda · API Gateway · SQS · RDS PostgreSQL · Mangum (ASGI adapter)

**How it works:** The FastAPI app is deployed as a Lambda function via Mangum. Webhooks hit API Gateway → Lambda, which pushes to SQS. A second Lambda (consumer) pulls from SQS and runs the pipeline.

```
Webhook → API Gateway → Lambda (producer) → SQS → Lambda (consumer) → RDS
```

**Pros:**
- Scales to zero (no cost when idle)
- SQS provides durable job queue with built-in retry and DLQ
- No server management
- Infinite horizontal scale

**Cons:**
- Cold start latency (Lambda + heavy dependencies like litellm = 3–8 second cold starts)
- SQLite impossible — must use RDS or DynamoDB (adds cost)
- LLM calls can exceed Lambda's 15-minute timeout for very large PRs
- Vendor lock-in (AWS-specific deployment, IAM, VPC)
- Local development requires LocalStack or mocking

**Fits when:** You need massive scale (thousands of webhooks/hour), have existing AWS infrastructure, and the team has AWS expertise.

**Effort to migrate from current:** High — deployment model, local dev workflow, and DB layer all change.

---

## Side-by-Side Comparison

| Criterion | A: Current | B: ARQ + PG | C: LangGraph | D: GH Actions | E: Serverless |
|---|---|---|---|---|---|
| Job durability (survives restart) | No | Yes | Yes (with backend) | Yes (GitHub handles) | Yes (SQS) |
| Concurrent scale | Low (SQLite) | High | High | Auto (GitHub) | Auto (Lambda) |
| Retry on failure | No | Yes | Yes | Yes (Actions) | Yes (SQS) |
| Parallel pipeline stages | No | No | Yes | No | No |
| GitLab support | Yes | Yes | Yes | No | Yes |
| Historical query API | Yes | Yes | Yes | No | Yes |
| Infra to run | None | Redis + PG | Redis + PG | None | AWS |
| Local dev complexity | Low | Medium | Medium | Low | High |
| Dead dependency cleanup needed | Yes | Yes | Partial | N/A | Yes |
| Migration effort from current | — | Medium | Low | High | High |

---

## Recommendation

**For a production system serving multiple teams: Approach B + C together.**

1. **Approach B (ARQ + PostgreSQL)** fixes the two critical gaps: job durability and concurrent write bottleneck. The migration is mechanical — the pipeline nodes are unchanged.

2. **Approach C (LangGraph)** then gives you parallel execution of the metadata + diff fetch stages (immediate latency win) and the ability to skip LLM stages for low-risk PRs (immediate cost win).

3. **Delete the dead dependencies** (`psycopg2-binary` replaces the unused import; remove `PyGithub`, `langchain` chain modules, standalone `SQLAlchemy` once it's wired in properly).

**For a single-team internal tool with < 50 webhooks/hour: stay with Approach A but fix Gap 1.**

The minimum fix is: before firing `asyncio.create_task`, insert a `status=pending` row into `pr_pipeline_events`. On task completion (or failure), update the row. This gives you visibility and a manual re-run path without adding Redis.

**Avoid Approach D (GitHub Actions) unless GitLab is out of scope** — you'd lose the central query API and historical data, and you'd need a separate CI pipeline for GitLab support.

**Avoid Approach E (serverless) unless the team already lives in AWS** — the cold start latency and 15-minute timeout ceiling are real constraints for LLM-heavy pipelines.

---

## Immediate Actions (regardless of approach chosen)

1. **Add tests.** No test files exist. At minimum: unit test `scoring.py` (pure function, easy to test), mock-test `IngestWebhookNode` (signature validation logic), integration test the full pipeline with a fixture webhook payload.

2. **Lock down CORS.** `allow_origins=["*"]` must be replaced with an explicit list before any external exposure.

3. **Add auth to GET endpoints.** A simple API key header check (`X-API-Key`) is enough to start.

4. **Remove unused dependencies.** `langgraph`, `langchain`, `SQLAlchemy`, `psycopg2-binary`, `redis`, `prometheus-client`, `PyGithub` — remove any that are imported nowhere in active code. Reinstall only when the feature that needs them is actually built.

5. **Add LLM fallback.** If the selected provider fails, try the next configured provider before letting the stage fail silently.
