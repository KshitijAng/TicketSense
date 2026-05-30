"""Create all DB tables from the current SQLAlchemy models.

Run once after bringing Postgres up:
    venv/bin/python -m scripts.init_db

Idempotent — re-running is safe; existing tables are left untouched.

scripts/init_db.py uses:
- models/ticket.py
- db/session.py

Python runs the entire models/ticket.py file. That file contains the class Ticket(Base): definition.
Running it = registering the table.

So by the time from models.ticket import Base returns, Base.metadata already contains the tickets table
— even though we only imported Base, not Ticket.
"""

import asyncio

from db.session import engine
from models.ticket import Base


async def main() -> None:
    async with engine.begin() as conn:
        # `create_all` issues CREATE TABLE IF NOT EXISTS for every model
        # registered with Base.metadata. Safe to re-run.
        await conn.run_sync(Base.metadata.create_all)
    print(f"Tables ensured: {list(Base.metadata.tables.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
