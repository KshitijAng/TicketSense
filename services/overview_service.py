"""Pre-computed overview service.

Two operations:
  - refresh_overview(): recompute from Postgres + Redis triage cache, write
    the result back to Redis under a single key (triage:overview).
  - get_overview():     read the pre-computed key in one Redis GET.

This split decouples the read path from the compute path. Dashboards always
hit a constant-time lookup; recompute happens on demand or after bulk triage.

services/overview_service.py uses:
- dtos/response.py                           → OverviewResponse (return shape)
- repositories/ticket_repository.py          → ticket count from Postgres
- repositories/triage_cache_repository.py    → all triages from Redis
- db/redis_client.py                         → direct read/write of overview key
"""

from collections import Counter
from datetime import timedelta

from redis.asyncio import Redis

from dtos.response import OverviewResponse
from repositories.ticket_repository import TicketRepository
from repositories.triage_cache_repository import TriageCacheRepository


# Single canonical key. Same JSON-blob pattern as individual triages.
OVERVIEW_KEY = "triage:overview"

# TTL = stale-safety. If a refresh job fails silently, the cached overview
# auto-expires after 24h so the dashboard knows to refuse / prompt a refresh.
OVERVIEW_TTL = timedelta(hours=24)


class OverviewService:
    def __init__(
        self,
        ticket_repo: TicketRepository,
        cache_repo: TriageCacheRepository,
        redis_client: Redis,
    ):
        self._ticket_repo = ticket_repo
        self._cache_repo = cache_repo
        self._redis = redis_client

    async def get_overview(self) -> OverviewResponse | None:
        """Read the pre-computed overview from Redis.

        Returns None if the key doesn't exist (never been refreshed, or expired).
        The dashboard should then either show an empty state or trigger refresh.
        """
        raw = await self._redis.get(OVERVIEW_KEY)
        if raw is None:
            return None
        return OverviewResponse.model_validate_json(raw)

    async def refresh_overview(self) -> OverviewResponse:
        """Recompute aggregates from Postgres + Redis triages, then cache.

        Returns the freshly-computed overview so callers can use it without
        a second round-trip if they want.
        """
        # ─── 1. Pull source data ───
        total = await self._ticket_repo.count()
        triages = await self._cache_repo.get_all()

        # ─── 2. Tally each label dimension ───
        # Counter(iterable) → {value: count}. dict() turns it into a plain dict
        # for clean JSON serialization (Counter pickles slightly differently).
        by_priority = dict(Counter(t.priority for t in triages))
        by_category = dict(Counter(t.category for t in triages))
        by_sentiment = dict(Counter(t.sentiment for t in triages))

        # ─── 3. Build the response DTO ───
        overview = OverviewResponse(
            total_tickets=total,
            by_priority=by_priority,
            by_category=by_category,
            by_sentiment=by_sentiment,
        )

        # ─── 4. Cache for fast subsequent reads ───
        await self._redis.set(
            OVERVIEW_KEY,
            overview.model_dump_json(),
            ex=int(OVERVIEW_TTL.total_seconds()),
        )
        return overview
