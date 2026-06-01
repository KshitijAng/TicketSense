"""Ticket endpoints.

POST   /tickets                       → create + auto-triage (full payload)
GET    /tickets                       → paginated list (with triage joined)
POST   /tickets/{ticket_id}/triage    → force re-triage (overrides cache)

Auto-triage on POST /tickets is graceful — if the LLM fails entirely, the
ticket is still persisted with `triage=None`. The caller can retry via
POST /tickets/{ticket_id}/triage later.

app/routers/tickets.py uses:
- app/dependencies.py                        → DI factories
- dtos/request.py                            → TicketSeedRequest validation
- dtos/response.py                           → TicketResponse shape
- models/ticket.py                           → Ticket ORM
- repositories/ticket_repository.py          → Postgres CRUD
- repositories/triage_cache_repository.py    → Redis triage cache
- services/triage_service.py                 → LLM pipeline
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_cache_repo,
    get_session,
    get_ticket_repo,
    get_triage_service,
)
from dtos.request import TicketSeedRequest
from dtos.response import TicketResponse
from models.ticket import Ticket
from repositories.ticket_repository import TicketRepository
from repositories.triage_cache_repository import TriageCacheRepository
from services.triage_service import TriageService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _orm_to_response(ticket: Ticket, triage=None) -> TicketResponse:
    """Coerce an ORM Ticket + optional triage into the API response shape."""
    return TicketResponse(
        id=ticket.id,
        subject=ticket.subject,
        body=ticket.body,
        from_name=ticket.from_name,
        from_email=ticket.from_email,
        created_at=ticket.created_at,
        triage=triage,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketResponse,
    summary="Create a ticket with full metadata and triage it via the LLM",
    description=(
        "Caller supplies id + subject + body + from_name + from_email + created_at. "
        "The ticket is persisted in Postgres and triaged via Groq in a single call. "
        "Returns 409 if a ticket with the given id already exists. "
        "If the LLM fails entirely (both primary and fallback exhausted), the ticket "
        "is still persisted; `triage` will be `null` in the response."
    ),
)
async def create_ticket(
    request: TicketSeedRequest,
    session: AsyncSession = Depends(get_session),
    cache_repo: TriageCacheRepository = Depends(get_cache_repo),
    triage_service: TriageService = Depends(get_triage_service),
) -> TicketResponse:
    ticket_repo = TicketRepository(session)

    # 1. Reject duplicates with a clear error.
    if await ticket_repo.exists(request.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ticket {request.id!r} already exists. "
                f"Use POST /tickets/{request.id}/triage to re-triage, "
                f"or POST with a different id."
            ),
        )

    # 2. Build ORM instance from caller-provided fields.
    ticket = Ticket(
        id=request.id,
        subject=request.subject,
        body=request.body,
        from_name=request.from_name,
        from_email=str(request.from_email),    # EmailStr → plain str for the DB column
        created_at=request.created_at,
    )

    # 3. Insert into Postgres (flush; commit at the end).
    await ticket_repo.insert(ticket)

    # 4. Triage via LLM — graceful degradation if both models fail.
    triage = None
    try:
        triage = await triage_service.triage(ticket.subject, ticket.body)
        await cache_repo.set(ticket.id, triage)
    except Exception as e:
        logger.error(
            "LLM triage failed for new ticket %s — persisting without triage. (%s)",
            ticket.id, e,
        )

    # 5. Commit Postgres.
    await session.commit()

    return _orm_to_response(ticket, triage)


@router.get(
    "",
    response_model=list[TicketResponse],
    summary="List tickets (paginated), with triage attached when available",
)
async def list_tickets(
    limit: int = Query(default=20, ge=1, le=200, description="Max tickets returned (1-200)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    ticket_repo: TicketRepository = Depends(get_ticket_repo),
    cache_repo: TriageCacheRepository = Depends(get_cache_repo),
) -> list[TicketResponse]:
    tickets = await ticket_repo.list_all(limit=limit, offset=offset)

    # Fetch all triages concurrently — N round-trips fired in parallel.
    triages = await asyncio.gather(*(cache_repo.get(t.id) for t in tickets))

    return [_orm_to_response(t, tr) for t, tr in zip(tickets, triages)]


@router.post(
    "/{ticket_id}/triage",
    response_model=TicketResponse,
    summary="(Re-)triage an existing ticket via the LLM pipeline",
    description=(
        "Always invokes the LLM regardless of any cached value. "
        "The fresh triage replaces any existing cache entry."
    ),
)
async def retriage_ticket(
    ticket_id: str,
    ticket_repo: TicketRepository = Depends(get_ticket_repo),
    cache_repo: TriageCacheRepository = Depends(get_cache_repo),
    triage_service: TriageService = Depends(get_triage_service),
) -> TicketResponse:
    ticket = await ticket_repo.get_by_id(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket {ticket_id!r} not found.",
        )

    try:
        triage = await triage_service.triage(ticket.subject, ticket.body)
    except Exception as e:
        logger.error("LLM triage failed for %s: %s", ticket_id, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM triage failed (both primary and fallback exhausted).",
        )

    await cache_repo.set(ticket_id, triage)
    return _orm_to_response(ticket, triage)
