"""
Outgoing API shapes. The DTOs the dashboard receives.

Note: when the API returns triage data, we reuse TriageOutput from dtos/llm.py
directly. The LLM contract IS the API contract for that shape — no separate
TriageResponse needed.
"""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

from dtos.llm import TriageOutput


class TicketResponse(BaseModel):  # A ticket with its triage (or null if not yet triaged)
    id: str = Field(
        ...,
        description="Ticket ID, e.g. ticket_001.",
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
    )
    from_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
    )
    from_email: EmailStr = Field(
        ...,
    )
    created_at: datetime = Field(
        ...,
    )
    triage: TriageOutput | None = None  # Reuses the LLM DTO directly — same shape


class OverviewResponse(BaseModel):  # The dashboard's main payload — total + 3 breakdowns
    total_tickets: int = Field(   # Headline KPI shown on the dashboard ("300 tickets in last 30 days")
        ...,
        description="Total tickets in the dashboard window.",
    )
    by_priority: dict[str, int] = Field(   # dict[str, int] = map of string keys → int values, e.g., {"high": 47, "medium": 22}. Feeds the priority chart.
        ...,
        description="Triaged ticket counts per priority.",
    )
    by_category: dict[str, int] = Field(   # Counts per category — feeds the category breakdown chart (billing / technical / feature_request / complaint / general)
        ...,
        description="Triaged ticket counts per category.",
    )
    by_sentiment: dict[str, int] = Field(   # Counts per sentiment — feeds the sentiment chart (positive / neutral / negative / angry)
        ...,
        description="Triaged ticket counts per sentiment.",
    )
