"""Load the 300 seed tickets from data/batch_{1-6}.json into Postgres.

Run via:
    venv/bin/python -m scripts.load_seed

Idempotent — tickets already present (by id) are skipped, not duplicated.

scripts/load_seed.py uses:
- data/batch_{1-6}.json
- dtos/request.py
- models/ticket.py
- db/session.py
- repositories/ticket_repository.py

Browse the loaded data:
    docker compose exec postgres psql -U triage -d triage
"""

import asyncio
import json
from pathlib import Path

from db.session import SessionLocal
from dtos.request import TicketSeedRequest
from models.ticket import Ticket
from repositories.ticket_repository import TicketRepository


# Path constants
DATA_DIR = Path(__file__).parent.parent / "data"
BATCH_FILES = [DATA_DIR / f"batch_{i}.json" for i in range(1, 7)]


def load_raw_tickets() -> list[dict]:
    """Read all 6 batch JSON files and flatten into one list of raw dicts."""
    all_tickets: list[dict] = []
    for path in BATCH_FILES:
        with open(path) as f:
            all_tickets.extend(json.load(f))
    return all_tickets


def dto_to_orm(request: TicketSeedRequest) -> Ticket:
    """Convert a validated Pydantic DTO into a SQLAlchemy ORM instance.

    The DTO is what we validate at the boundary; the ORM is what we persist.
    This adapter is the small bridge between layers.
    """
    return Ticket(
        id=request.id,
        subject=request.subject,
        body=request.body,
        from_name=request.from_name,
        from_email=str(request.from_email),  # EmailStr → plain str for the DB column
        created_at=request.created_at,
    )


async def main() -> None:
    # Step 1: read and validate everything BEFORE touching the DB
    raw = load_raw_tickets()
    print(f"Read {len(raw)} tickets from {len(BATCH_FILES)} JSON files")

    validated = [TicketSeedRequest(**r) for r in raw]   # fails fast on any bad ticket
    print(f"Validated {len(validated)} tickets against TicketSeedRequest")

    # Step 2: insert into Postgres (idempotent — skip if id already exists)
    inserted = 0
    skipped = 0

    async with SessionLocal() as session:
        repo = TicketRepository(session)

        for request in validated:
            if await repo.exists(request.id):
                skipped += 1
                continue
            await repo.insert(dto_to_orm(request))
            inserted += 1

        await session.commit()    # single transaction for all 300 inserts

        # Step 3: report final state
        total = await repo.count()
        print(f"\nInserted: {inserted}")
        print(f"Skipped (already existed): {skipped}")
        print(f"Total tickets in DB: {total}")


if __name__ == "__main__":
    asyncio.run(main())
