"""Async repository for the `tickets` table.

Wraps SQLAlchemy queries so the service layer doesn't write SQL directly.
Caller owns the AsyncSession (commit, rollback, close) — the repo only
issues statements against it.

repositories/ticket_repository.py uses:
- models/ticket.py → Ticket ORM class
"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.ticket import Ticket


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self._session = session  # Session is injected, not created here — caller manages lifecycle

    async def insert(self, ticket: Ticket) -> Ticket:
        """Stage an insert and flush so DB constraints fire immediately.

        Does NOT commit — caller decides when to end the transaction.
        """
        self._session.add(ticket)       # Add the object to the session (pending insert)
        await self._session.flush()     # Sends the INSERT statement to Postgres, still inside the transaction
        return ticket

    async def get_by_id(self, ticket_id: str) -> Ticket | None:
        """Fetch one ticket by primary key, or None if not found."""
        return await self._session.get(Ticket, ticket_id)

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Ticket]:
        """Paginated list, newest first."""
        stmt = (
            select(Ticket)                            # SELECT * FROM tickets
            .order_by(Ticket.created_at.desc())       # ORDER BY created_at DESC
            .limit(limit)                             # LIMIT N
            .offset(offset)                           # OFFSET M
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())          # scalars() = rows of Ticket objects; .all() = collect into list

    async def count(self) -> int:
        """Total tickets in the table."""
        stmt = select(func.count()).select_from(Ticket)   # SELECT COUNT(*) FROM tickets
        result = await self._session.execute(stmt)
        return result.scalar_one()                         # scalar_one() = exactly one scalar value (int)

    async def exists(self, ticket_id: str) -> bool:
        """Quick existence check. Useful for idempotent seed loading."""
        stmt = (
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.id == ticket_id)            # WHERE id = :ticket_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one() > 0
