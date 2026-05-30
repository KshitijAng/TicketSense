"""SQLAlchemy ORM model for the `tickets` table.

Stores raw ticket data only. Triage results are persisted to Redis under
`triage:ticket:{id}` keys and joined at the service layer.
"""

from datetime import datetime
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):  # Every ORM model in the project inherits from this
    pass


class Ticket(Base):
    __tablename__ = "tickets"   # The actual table name in Postgres

    # `Mapped[T]` = Mapped is a special generic class provided by SQLAlchemy
    # `mapped_column(...)` = SQL column definition (type, constraints, indexes).

    id: Mapped[str] = mapped_column(    # SQLAlchemy-managed attribute that returns a str
        String(20),               # Postgres VARCHAR(20) — fits 'ticket_001' through 'ticket_300' with room
        primary_key=True,         # The unique identifier for each row
    )
    subject: Mapped[str] = mapped_column(
        String(500),              # VARCHAR(500), matches the DTO's max_length
        nullable=False,           # SQL `NOT NULL` constraint
    )
    body: Mapped[str] = mapped_column(
        Text,                     # Postgres TEXT — variable-length, no upper limit at the SQL level
        nullable=False,
    )
    from_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    from_email: Mapped[str] = mapped_column(
        String(300),              # 300 chars is generous; real email max is 254 per RFC 5321
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),  # TIMESTAMPTZ — stores timezone info (UTC for us)
        nullable=False,
    )

    def __repr__(self) -> str:  # Useful for debugging — shows up in print() and tracebacks
        return f"<Ticket id={self.id!r} subject={self.subject!r}>"
