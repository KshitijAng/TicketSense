"""Health-check endpoint.

GET /health → {"status": "ok"}

Used by liveness probes (Docker / Kubernetes / load balancers) to confirm
the app process is responsive. No DB or Redis touched intentionally —
this endpoint must succeed even when downstream services are degraded.
"""

from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
