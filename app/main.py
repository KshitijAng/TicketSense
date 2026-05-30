"""TicketSense FastAPI application.

Run via:
    venv/bin/uvicorn app.main:app --reload --port 8000

Auto-generated OpenAPI docs:
    http://localhost:8000/docs     (Swagger UI)

app/main.py uses:
- app/routers/health.py     → GET /health
- app/routers/tickets.py    → /tickets endpoints
- app/routers/overview.py   → /overview endpoints
- db/session.py             → engine.dispose() on shutdown
- db/redis_client.py        → redis_client.close() on shutdown
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import health, overview, tickets
from db.redis_client import redis_client
from db.session import engine


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Lifespan — graceful startup / shutdown for shared resources
# ────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting TicketSense API")
    yield
    # Shutdown: close pools so the process exits cleanly
    logger.info("Shutting down — closing connection pools")
    await engine.dispose()
    await redis_client.close()


# ────────────────────────────────────────────────────────────────────────────
# Application instance
# ────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TicketSense API",
    description=(
        "LLM-powered support ticket triage. Classifies incoming emails by "
        "priority, category, and sentiment via Groq's Llama models, with "
        "retry-and-fallback resilience. Results cached in Redis with a "
        "pre-computed overview for fast dashboard reads."
    ),
    version="1.0.0",
    lifespan=lifespan,
    redoc_url=None,    # Disable /redoc — /docs (Swagger UI) covers the same purpose
)

# CORS — permissive for the local demo. Lock down in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(tickets.router)
app.include_router(overview.router)
