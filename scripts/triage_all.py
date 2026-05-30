"""Bulk-triage every ticket in Postgres → write result to Redis.

scripts/triage_all.py uses:
- db/session.py                              → Postgres SessionLocal
- db/redis_client.py                         → shared async Redis client
- repositories/ticket_repository.py          → list tickets
- repositories/triage_cache_repository.py    → set / exists / count in Redis
- services/triage_service.py                 → the LLM pipeline (primary + fallback)

Run via:
    python -m scripts.triage_all                    # all untriaged tickets
    python -m scripts.triage_all --limit 5          # first 5 untriaged
    python -m scripts.triage_all --id ticket_001    # one specific ticket
    python -m scripts.triage_all --force            # re-triage even if cached

Idempotent: tickets already present in Redis are skipped unless --force is set.
"""

import argparse
import asyncio
import logging
import time

from db.redis_client import redis_client
from db.session import SessionLocal
from repositories.ticket_repository import TicketRepository
from repositories.triage_cache_repository import TriageCacheRepository
from services.overview_service import OverviewService
from services.triage_service import TriageService


logger = logging.getLogger(__name__)


# Sleep between successive LLM calls to keep request rate well under
# Groq's free-tier ceiling of ~30 req/min for the chosen models.
PACING_SECONDS = 2.0


async def main(limit: int | None, ticket_id: str | None, force: bool) -> None:
    # ─── 1. Load the ticket(s) we want to triage from Postgres ───
    async with SessionLocal() as session:
        ticket_repo = TicketRepository(session)

        if ticket_id is not None:
            # Single-ticket mode: lookup by ID
            ticket = await ticket_repo.get_by_id(ticket_id)
            if ticket is None:
                logger.error("Ticket %r not found in Postgres", ticket_id)
                return
            tickets = [ticket]
        else:
            # Bulk mode: list_all (newest first). list_all's default cap of 100
            # would clip our 300 tickets, so we pass an explicit large limit
            # when the caller didn't request one.
            tickets = await ticket_repo.list_all(limit=limit or 10_000, offset=0)

    total = len(tickets)
    logger.info("Loaded %d ticket(s) from Postgres", total)

    # ─── 2. Set up the cache repo + LLM service (one instance for the whole run) ───
    cache_repo = TriageCacheRepository(redis_client)
    service = TriageService()    # Reads GROQ_API_KEY from settings

    triaged = 0
    skipped = 0
    failed = 0
    start = time.time()

    # ─── 3. Loop over tickets ───
    for i, ticket in enumerate(tickets, start=1):
        # Idempotency: skip tickets that already have a cached triage,
        # unless the caller explicitly wants to re-triage.
        if not force and await cache_repo.exists(ticket.id):
            skipped += 1
            continue

        try:
            result = await service.triage(ticket.subject, ticket.body)
            await cache_repo.set(ticket.id, result)
            triaged += 1
            print(
                f"  [{i:>3}/{total}] {ticket.id} → "
                f"{result.priority:>8} / {result.category:<16} / {result.sentiment}"
            )
        except Exception as e:
            failed += 1
            logger.error(
                "Triage failed for %s (%s: %s)",
                ticket.id, type(e).__name__, e,
            )

        # Pace requests — sleep AFTER each call so the next iteration doesn't burst Groq's rate limit. 
        await asyncio.sleep(PACING_SECONDS)

    elapsed = time.time() - start
    total_cached = await cache_repo.count()

    # ─── 4. Final summary ───
    print()
    print(f"Triaged: {triaged}")
    print(f"Skipped (already cached): {skipped}")
    print(f"Failed: {failed}")
    print(f"Total triage keys in Redis now: {total_cached}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed / max(triaged, 1):.2f}s per triage)")

    # ─── 5. Refresh the pre-computed overview ───
    # Keep the dashboard fresh without forcing it to recompute on every load.
    # Done at the end of the run since aggregating mid-run would be wasted work.
    async with SessionLocal() as session:
        overview_service = OverviewService(
            TicketRepository(session),
            cache_repo,
            redis_client,
        )
        await overview_service.refresh_overview()
    logger.info("Overview refreshed and cached under key 'triage:overview'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk-triage tickets via Groq LLM.")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N tickets.")
    parser.add_argument("--id", dest="ticket_id", default=None, help="Triage one specific ticket by ID.")
    parser.add_argument("--force", action="store_true", help="Re-triage even if a cached triage exists.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(main(args.limit, args.ticket_id, args.force))
