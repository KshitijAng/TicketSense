"""Recompute the pre-computed overview and cache it in Redis.

scripts/refresh_overview.py uses:
- db/session.py                              → Postgres SessionLocal
- db/redis_client.py                         → shared async Redis client
- repositories/ticket_repository.py          → ticket count from Postgres
- repositories/triage_cache_repository.py    → read all individual triages
- services/overview_service.py               → orchestrates the refresh
- dtos/response.py                           → OverviewResponse for the printout

Run via:
    python -m scripts.refresh_overview

Typical use:
- After scripts/triage_all.py finishes (auto-called by the bulk runner)
- Manually after re-triage or a model swap, to refresh dashboard data
"""

import asyncio
import logging

from db.redis_client import redis_client
from db.session import SessionLocal
from repositories.ticket_repository import TicketRepository
from repositories.triage_cache_repository import TriageCacheRepository
from services.overview_service import OverviewService


logger = logging.getLogger(__name__)


async def main() -> None:
    async with SessionLocal() as session:
        ticket_repo = TicketRepository(session)
        cache_repo = TriageCacheRepository(redis_client)
        service = OverviewService(ticket_repo, cache_repo, redis_client)

        overview = await service.refresh_overview()

    print("\n=== Overview recomputed and cached ===")
    print(f"Total tickets: {overview.total_tickets}")
    print(f"\nby_priority:  {overview.by_priority}")
    print(f"by_category:  {overview.by_category}")
    print(f"by_sentiment: {overview.by_sentiment}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(main())
