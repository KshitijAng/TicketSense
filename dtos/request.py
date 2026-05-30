"""Incoming request DTOs.

Currently one shape: a fully-formed ticket coming in either from the seed
loader (data/batch_*.json) or from POST /tickets in the FastAPI layer. The
caller always provides id + sender + timestamp.

ISO 8601 is the international standard for writing dates and times as strings.
"""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class TicketSeedRequest(BaseModel):  # Used by both the seed loader and POST /tickets — preserves caller-provided id, sender, and timestamp
    id: str = Field(
        ...,
        # The r prefix tells Python: "don't interpret backslash escape sequences in this string."
        pattern=r"^ticket_\d{3}$",   # `pattern=` enforces a regex — must look like ticket_001, ticket_300. The two anchors ^ and $ are the strict gatekeepers.
        description="Pre-assigned ticket ID, must match `ticket_NNN` where NNN is 3 digits.",
    )
    subject: str = Field(
        ...,
        min_length=1,
        max_length=500,
    )
    body: str = Field(
        ...,
        min_length=1,
        max_length=50_000,
        description="Email body text. Plain text or rendered HTML stripped.",
    )
    from_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
    )
    from_email: EmailStr = Field(   # EmailStr validates the format — needs the `email-validator` package
        ...,
        description="Sender's email address; format validated automatically.",
    )
    created_at: datetime = Field(   # Pydantic auto-parses ISO 8601 strings ('2026-04-14T12:15:00Z') into datetime objects
        ...,
        description="When the original email arrived.",
    )
