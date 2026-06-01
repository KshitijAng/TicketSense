"""FastAPI dependency-injection factories.

Each router function declares what it needs via Depends(get_xxx); FastAPI
constructs the object per request and injects it. Sessions are auto-closed
when the request ends.

app/dependencies.py uses:
- db/session.py                              → SessionLocal (per-request Postgres session)
- db/redis_client.py                         → shared async Redis client
- repositories/ticket_repository.py          → Postgres data access
- repositories/triage_cache_repository.py    → Redis data access
- services/triage_service.py                 → LLM pipeline
- services/overview_service.py               → pre-computed aggregate
"""

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.redis_client import redis_client
from db.session import SessionLocal
from repositories.ticket_repository import TicketRepository
from repositories.triage_cache_repository import TriageCacheRepository
from services.overview_service import OverviewService
from services.triage_service import TriageService


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session that auto-closes when the request finishes."""
    async with SessionLocal() as session:
        yield session


def get_ticket_repo(
    session: AsyncSession = Depends(get_session),
) -> TicketRepository:
    return TicketRepository(session)


def get_cache_repo() -> TriageCacheRepository:
    return TriageCacheRepository(redis_client)


def get_triage_service() -> TriageService:
    return TriageService()


def get_overview_service(
    ticket_repo: TicketRepository = Depends(get_ticket_repo),
    cache_repo: TriageCacheRepository = Depends(get_cache_repo),
) -> OverviewService:
    return OverviewService(ticket_repo, cache_repo, redis_client)
