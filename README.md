# TicketSense

> **An LLM-powered support ticket triage tool that classifies incoming emails by priority, category, and sentiment — then surfaces results in a real-time dashboard.**

![TicketSense dashboard](assets/dashboard.png)

Built with FastAPI-style layered architecture (DTOs / repositories / services), two storage tiers (Postgres for durable data, Redis for cached LLM results), production-grade LLM resilience (retry + model fallback), and a pre-computed overview pattern that scales the read path independently of dataset size.

---

## What it does

Customer-support teams receive hundreds of tickets daily — most routine, some critical, a few toxic. Reading every one to figure out which is which costs hours.

TicketSense reads incoming emails and labels them automatically along three dimensions:

- **Priority** — `low` / `medium` / `high` / `critical`
- **Category** — `billing` / `technical` / `feature_request` / `complaint` / `general`
- **Sentiment** — `positive` / `neutral` / `negative` / `angry`

Plus a one-sentence summary and 2–5 free-form tags per ticket.

A dashboard surfaces the aggregate (counts per dimension) and a random sample of triaged tickets so support managers can spot trends and high-priority items in seconds rather than minutes.

---

## Architecture

```
                                     ┌─────────────────────────────────┐
data/batch_{1-6}.json                │  Streamlit dashboard (:8501)    │
(300 synthetic seed tickets)         │  • 4 KPI cards                  │
              │                      │  • 3 breakdown charts           │
              │ scripts/load_seed    │  • 10-row random sample table   │
              ▼                      └────────────────┬────────────────┘
   ┌──────────────────────┐                           │
   │  Postgres (:5432)    │                           │ 1 Redis GET
   │  table: tickets      │                           ▼
   │  300 immutable rows  │           ┌──────────────────────────────┐
   └──────────┬───────────┘           │  Redis (:6379)               │
              │                       │                              │
              │ scripts/triage_all    │  triage:ticket:{id} × 300   │
              ▼                       │  (per-ticket TriageOutput,   │
   ┌──────────────────────┐           │   7-day TTL)                 │
   │  TriageService       │ writes →  │                              │
   │  • Primary: Llama 4  │           │  triage:overview             │
   │    Scout 17B MoE     │ ←  reads  │  (pre-computed aggregate,    │
   │  • Fallback: Llama   │   from    │   24-hour TTL)               │
   │    3.1 8B Instant    │           └──────────────────────────────┘
   │  • Retry + backoff   │
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  Groq API (free tier)│
   │  Structured output   │
   │  via LangChain       │
   └──────────────────────┘
```

**Three layers, deliberately split by lifecycle:**

| Layer | Tool | What it stores | Lifecycle |
|---|---|---|---|
| **Durable data** | Postgres | Raw ticket rows | Forever — source of truth |
| **Cached analysis** | Redis (`triage:ticket:*`) | LLM-produced labels per ticket | 7-day TTL — regenerable if lost |
| **Read-optimized aggregate** | Redis (`triage:overview`) | Pre-computed counts for the dashboard | 24-hour TTL — refreshed after bulk triage |

The dashboard reads **one** Redis key per page load (`triage:overview`) — constant-time regardless of dataset size.

---

## Tech stack

| Concern | Tool |
|---|---|
| Language | Python 3.14 |
| Validation / DTOs | Pydantic 2.x + pydantic-settings |
| ORM | SQLAlchemy 2.x (async) |
| Relational DB | Postgres 16 (Docker) |
| Cache | Redis 7 (Docker) |
| LLM | Groq (Llama 4 Scout primary, Llama 3.1 8B Instant fallback) |
| LLM framework | LangChain + langchain-groq |
| HTTP API | FastAPI + Uvicorn |
| Dashboard | Streamlit |
| Container orchestration | Docker Compose |

### Services & ports

| Service | Port | Where it runs | URL when running |
|---|---|---|---|
| **Postgres** | `5432` | Docker container (`triage_postgres`) | `postgresql://localhost:5432/triage` |
| **Redis** | `6379` | Docker container (`triage_redis`) | `redis://localhost:6379/0` |
| **FastAPI** | `8000` | Local Python process (Uvicorn) | http://localhost:8000 — docs at /docs |
| **Streamlit dashboard** | `8501` | Local Python process | http://localhost:8501 |

Two containers + two local processes. No conflicts; all four can run simultaneously.

---

## Quickstart

Requires Docker, Python 3.10+, a Groq API key ([free signup](https://console.groq.com)).

```bash
# 1. Clone + enter
git clone <your-repo-url> ticket-sense
cd ticket-sense

# 2. Python environment
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. Create .env with your credentials
cat > .env <<'EOF'
DATABASE_URL=postgresql+asyncpg://triage:triage_dev@localhost:5432/triage
REDIS_URL=redis://localhost:6379/0
GROQ_API_KEY=your-groq-key-from-console.groq.com
EOF

# 4. Start Postgres + Redis
docker compose up -d

# 5. Bootstrap the schema (creates the `tickets` table)
venv/bin/python -m scripts.init_db

# 6. Load the 300 seed tickets into Postgres
venv/bin/python -m scripts.load_seed

# 7. Triage every ticket via Groq (~12 minutes for all 300)
venv/bin/python -m scripts.triage_all

# 8. Launch the dashboard
venv/bin/streamlit run dashboard.py            # → http://localhost:8501

# 9. (Optional) Launch the HTTP API
venv/bin/uvicorn app.main:app --reload --port 8000   # → http://localhost:8000/docs
```

---

## HTTP API

The FastAPI tier exposes the same services as the dashboard, callable from any HTTP client. Interactive auto-generated OpenAPI docs at **`http://localhost:8000/docs`** (Swagger UI).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe — never touches DB / Redis |
| `GET` | `/overview` | Read the pre-computed dashboard aggregate (1 Redis GET) |
| `POST` | `/overview/refresh` | Recompute the aggregate from Postgres + Redis |
| `POST` | `/tickets` | Create a ticket (caller provides id + sender + timestamp) and auto-triage via LLM. Returns 409 if id exists. |
| `GET` | `/tickets?limit=20&offset=0` | Paginated ticket list with triages attached |
| `GET` | `/tickets/{ticket_id}` | Fetch one ticket with its triage |
| `POST` | `/tickets/{ticket_id}/triage` | Force re-triage (overrides cache) |

### Example: create a ticket and get it triaged

```bash
curl -X POST http://localhost:8000/tickets \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "ticket_301",
    "subject": "Production outage — checkout broken",
    "body": "Our checkout has been failing with HTTP 500 for the past 30 minutes.",
    "from_name": "Jane Doe",
    "from_email": "jane@acmecloud.io",
    "created_at": "2026-05-31T09:00:00Z"
  }' | jq
```

Response (≈ 2-3 seconds, includes one LLM call):

```json
{
  "id": "ticket_301",
  "subject": "Production outage — checkout broken",
  "from_name": "Jane Doe",
  "from_email": "jane@acmecloud.io",
  "created_at": "2026-05-31T09:00:00Z",
  "triage": {
    "priority": "critical",
    "category": "technical",
    "sentiment": "angry",
    "summary": "Production outage — checkout broken",
    "tags": ["production-outage", "checkout-failure", "urgent"]
  }
}
```

### Resilience notes

- **Auto-triage is graceful** — if both LLM models exhaust retries, the ticket is still persisted with `triage: null`. Caller can retry via `POST /tickets/{ticket_id}/triage`.
- **404s on missing IDs** — clear error messages, not 500s.
- **503 on persistent LLM failure** — the re-triage endpoint surfaces "service unavailable" if both models are down, distinct from invalid requests (422) or missing data (404).

### Architecture

```
HTTP request
     │
     ▼
FastAPI app/main.py
     │
     │  routes to →  app/routers/{health,tickets,overview}.py
     │
     ▼
Dependency injection (app/dependencies.py)
     │
     │  per-request session + repos + services
     │
     ▼
services/  →  repositories/  →  Postgres + Redis
```

The routers are thin — they validate input via Pydantic, call services, and serialize responses. All business logic lives in `services/`, all data access in `repositories/`. Same layered split the dashboard uses.

---

## Project layout

```
ticket-sense/
├── data/                          # 300 synthetic seed tickets + provenance README
│   ├── README.md
│   └── batch_{1-6}.json
├── dtos/                          # Pydantic shapes at every boundary
│   ├── request.py                 # TicketSeedRequest (incoming ticket payload)
│   ├── response.py                # TicketResponse, OverviewResponse
│   └── llm.py                     # TriageOutput (Literal-constrained LLM schema)
├── models/
│   └── ticket.py                  # SQLAlchemy ORM model + DeclarativeBase
├── db/
│   ├── session.py                 # Async engine + session factory + Settings
│   └── redis_client.py            # Async Redis client + connection pool
├── repositories/
│   ├── ticket_repository.py       # Postgres reads/writes
│   └── triage_cache_repository.py # Redis CRUD on triage:ticket:{id}
├── services/
│   ├── triage_service.py          # LLM pipeline (primary + fallback + retry)
│   └── overview_service.py        # Pre-computed aggregate read/refresh
├── app/                           # FastAPI HTTP layer
│   ├── main.py                    # FastAPI app + lifespan + CORS
│   ├── dependencies.py            # DI factories (sessions, repos, services)
│   └── routers/                   # Health / tickets / overview endpoints
├── scripts/
│   ├── init_db.py                 # Schema bootstrap (`Base.metadata.create_all`)
│   ├── load_seed.py               # JSON → Postgres
│   ├── triage_all.py              # Bulk triage runner
│   └── refresh_overview.py        # Recompute triage:overview key
├── dashboard.py                   # Streamlit single-file UI
├── docker-compose.yml             # Postgres + Redis services
└── requirements.txt
```

---

## Highlights

### Production-grade LLM resilience

Two layers of fault tolerance for every LLM call:

```
       Ticket → TriageService.triage(subject, body)
                            │
                            ▼
            ┌─────────────────────────────────┐
            │  Primary: Llama 4 Scout (17B MoE)│
            │  with structured_output(TriageOutput)
            └────────────┬────────────────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
        429 rate limit          success → return TriageOutput
              │
              ▼
       Retry: 1s → 2s → 4s
              │
              │ exhausted
              ▼
            ┌─────────────────────────────────┐
            │  Fallback: Llama 3.1 8B Instant │
            │  separate rate-limit pool       │
            └────────────┬────────────────────┘
                         │
                         │ same retry+success flow
                         ▼
                  Final TriageOutput
```

**Why two layers:**
- Retry-with-backoff handles transient 429s (most common failure, recoverable in seconds)
- Model-level fallback handles persistent issues with primary (different rate-limit pool, different infrastructure)
- Combined: ~95% of failures handled invisibly to the caller

### Pre-computed overview for dashboard scalability

The dashboard's main query is **O(1)** regardless of dataset size:

```
Dashboard request
       │
       ▼
   GET triage:overview         ← 1 Redis call, ~0.5ms
       │
       ▼
   OverviewResponse(
     total_tickets=300,
     by_priority={...},
     by_category={...},
     by_sentiment={...},
   )
```

Recompute is decoupled from reads:
- After bulk triage finishes → `OverviewService.refresh_overview()` writes the aggregate
- Or manually: `python -m scripts.refresh_overview`
- Or via the "Refresh" button in the dashboard sidebar

**Scaling profile:** dashboard read latency stays flat whether the system has 300 tickets or 3M.

### Constrained LLM output via Pydantic + Literal

The LLM cannot produce invalid values. The schema is enforced at the API layer:

```python
class TriageOutput(BaseModel):
    priority:  Literal["low", "medium", "high", "critical"]
    category:  Literal["billing", "technical", "feature_request", "complaint", "general"]
    sentiment: Literal["positive", "neutral", "negative", "angry"]
    summary:   str  # max 500 chars
    tags:      list[str]  # 2-5 kebab-case tags
```

Combined with `LangChain.with_structured_output(TriageOutput)`, the LLM is structurally incapable of returning `"super high"` or `"medium-ish"`. Validated round-trip on both write (LLM → Redis) and read (Redis → dashboard).

### Layered architecture

```
Boundary contract  →  DTO          (Pydantic)
DB shape           →  ORM model    (SQLAlchemy)
Data access        →  Repository
Business logic     →  Service
Entry point        →  Script or Streamlit app
```

Each layer has a single concern. Swapping Streamlit for FastAPI, or Postgres for MySQL, or Groq for OpenAI, touches only one layer.

---

## Metrics from the live demo dataset

| Metric | Value |
|---|---|
| Synthetic tickets generated | **300** across 6 thematic batches |
| Failed triages (Groq) | **0 / 300** |
| Per-ticket triage time (Groq Llama 4 Scout) | **~2.5s** average |
| Full dataset triage runtime | **~12 minutes** for 300 tickets |
| Dashboard initial load time | **~50 ms** (single Redis GET + chart render) |
| Pre-computed aggregate Redis key size | **~250 bytes** |
| Lines of application code | **~600** across 13 files |
| Python packages | 11 direct dependencies (see `requirements.txt`) |

### Triage distribution on the seed dataset

After running `scripts/triage_all` on all 300 seed tickets, the LLM produced this distribution (real output, not handcrafted):

| Dimension | Distribution |
|---|---|
| **Priority** | 99 low · 68 medium · 54 high · 79 critical |
| **Category** | 28 billing · 106 technical · 94 feature_request · 30 complaint · 42 general |
| **Sentiment** | 46 positive · 105 neutral · 65 negative · 84 angry |

The distribution **matches the deliberate batch themes** in the seed data — Batch 5 (P0 outages) produced critical/technical/angry as expected, Batch 3 (positive feature requests) produced low/feature_request/positive, etc. Useful end-to-end validation that the LLM is reading content correctly.

---

## Key design decisions

| Decision | Rationale |
|---|---|
| **Two storage layers (Postgres + Redis), not one** | Different lifecycle: tickets are durable, triage results are regenerable. Triage TTL means stale LLM versions evict themselves. |
| **Pre-computed overview, not on-the-fly aggregation** | Decouples dashboard latency from dataset size. Same ~50ms whether 300 or 3M tickets. |
| **Model-level fallback, not just retry** | Different failure modes need different responses. Primary 429s recover with retry; persistent issues need a different model. |
| **TriageOutput reused as API + LLM contract** | The LLM contract IS the API contract for triage data. One Pydantic class, two enforcement points. |
| **`Base.metadata.create_all()` instead of Alembic** | Single environment, settled schema. Alembic is overkill at this scale; one `init_db.py` call suffices. |
| **Skipped FastAPI** | Streamlit reads Postgres + Redis directly. No need for an HTTP layer when there's one consumer. Reduces moving parts. |
| **Inline `logging`, not structlog (for now)** | Stdlib logging covers the demo's needs. structlog migration is a one-file refactor when warranted. |

---

## Dataset

All 300 seed tickets in `data/batch_*.json` are **synthetic**:

1. **Initial generation** — ChatGPT (GPT-5.4) with per-batch theme prompts
2. **Quality rewrite** — Claude (Anthropic) hand-rewrote each ticket to fix templated outputs and ensure realistic edge cases (typos, all-caps rage, forwarded chains, MSA threats, etc.)
3. **Validation** — structurally verified: unique IDs/subjects/body openings, valid ISO 8601 timestamps, valid email format, 30 sender domains, ~150 unique sender names

No real customer data, no scraped data, no copied production records. See `data/README.md` for the full breakdown.

---


## What this project demonstrates

Skills exercised end-to-end:

- **Async Python** — `asyncio`, `async with`, async SQLAlchemy, async Redis
- **Pydantic 2.x** — DTOs, `Literal` constraints, structured output, settings management
- **SQLAlchemy 2.x ORM** — DeclarativeBase, `Mapped[T]`, async session factory, connection pooling
- **LLM systems design** — structured output, retry/backoff, model-level fallback, prompt engineering via field descriptions
- **Cache layer design** — TTL strategy, pre-computed aggregates, key conventions, MGET batching
- **Docker Compose** — multi-container orchestration, named volumes, service-name DNS
- **Layered architecture** — DTOs / ORM / repositories / services / scripts / UI cleanly separated

---
