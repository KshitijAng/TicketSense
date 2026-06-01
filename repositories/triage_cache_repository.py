"""Async Redis repository for triage results.

Key pattern: triage:ticket:{ticket_id}
Value:       JSON-serialized TriageOutput
TTL:         7 days

repositories/triage_cache_repository.py uses:
- dtos/llm.py → TriageOutput (for serialize on set / parse on get)
"""

from datetime import timedelta

from redis.asyncio import Redis

from dtos.llm import TriageOutput


TRIAGE_KEY_PREFIX = "triage:ticket"
TRIAGE_TTL = timedelta(days=7)


def _key(ticket_id: str) -> str:
    """Build the Redis key for a given ticket."""
    return f"{TRIAGE_KEY_PREFIX}:{ticket_id}"


class TriageCacheRepository:
    def __init__(self, client: Redis):
        self._client = client                  # Client is injected — same DI pattern as TicketRepository

    async def set(self, ticket_id: str, triage: TriageOutput) -> None:
        """Cache a triage result for a ticket. Overwrites any existing value. Resets TTL."""
        payload = triage.model_dump_json()     # Pydantic → JSON string for Redis storage
        await self._client.set(
            _key(ticket_id),
            payload,
            ex=int(TRIAGE_TTL.total_seconds()),   # `ex` = expiry in seconds (7 days = 604_800)
        )

    async def get(self, ticket_id: str) -> TriageOutput | None:
        """Read a cached triage for a ticket. Returns None if missing or expired."""
        raw = await self._client.get(_key(ticket_id))
        if raw is None:
            return None
        return TriageOutput.model_validate_json(raw)   # JSON string → validated TriageOutput

    async def exists(self, ticket_id: str) -> bool:
        """True if a triage exists for this ticket (and hasn't expired)."""
        return await self._client.exists(_key(ticket_id)) == 1

    async def get_all(self) -> list[TriageOutput]:
        """Read every triage currently in the cache.

        Used by OverviewService.refresh_overview() to recompute aggregates.
        Uses MGET (Multi-GET) so all keys are fetched in one Redis round-trip — much
        faster than calling get() in a loop.

        scan_iter is the safe, non-blocking way to iterate over Redis keys.
        """
        keys = [k async for k in self._client.scan_iter(match=f"{TRIAGE_KEY_PREFIX}:*")]
        if not keys:
            return []
        # One round-trip batch read. Returns a list of JSON strings (same order as keys);
        # entries are None for keys that vanished between SCAN and MGET.
        raw_values = await self._client.mget(*keys)
        return [
            TriageOutput.model_validate_json(v)   # JSON string → typed TriageOutput (Pydantic validates schema)
            for v in raw_values
            if v is not None                       # Defensive: skip any key that vanished mid-scan
        ]
