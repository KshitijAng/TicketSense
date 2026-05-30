"""Overview endpoints.

GET   /overview           → returns the cached aggregate (1 Redis GET)
POST  /overview/refresh   → recomputes from sources and re-caches

The cached aggregate has a 24h TTL. If neither path has run, GET returns 404.

app/routers/overview.py uses:
- app/dependencies.py            → DI factories
- dtos/response.py               → OverviewResponse shape
- services/overview_service.py   → get/refresh implementation
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_overview_service
from dtos.response import OverviewResponse
from services.overview_service import OverviewService


router = APIRouter(prefix="/overview", tags=["overview"])


@router.get(
    "",
    response_model=OverviewResponse,
    summary="Read the pre-computed dashboard overview",
    description=(
        "Returns the cached aggregate (total tickets + counts per priority / category / sentiment). "
        "Constant-time read — single Redis GET. Returns 404 if no aggregate has been "
        "computed yet (run `POST /overview/refresh` first)."
    ),
)
async def get_overview(
    service: OverviewService = Depends(get_overview_service),
) -> OverviewResponse:
    overview = await service.get_overview()
    if overview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No cached overview yet. POST /overview/refresh to compute one.",
        )
    return overview


@router.post(
    "/refresh",
    response_model=OverviewResponse,
    summary="Recompute the overview from Postgres + Redis triages",
    description=(
        "Reads ticket count from Postgres, reads every cached triage from Redis "
        "(via MGET), tallies the aggregate, writes it back under the canonical "
        "Redis key. Returns the freshly-computed overview."
    ),
)
async def refresh_overview(
    service: OverviewService = Depends(get_overview_service),
) -> OverviewResponse:
    return await service.refresh_overview()
