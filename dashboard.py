"""Streamlit dashboard for TicketSense.

Reads the pre-computed overview from Redis (one round-trip) and renders KPIs
+ three breakdown charts + a small ticket sample. A Refresh button triggers
recompute on demand.

Run via:
    venv/bin/streamlit run dashboard.py

dashboard.py uses:
- db/session.py                              → Postgres SessionLocal
- db/redis_client.py                         → shared async Redis client
- repositories/ticket_repository.py          → fetch sample tickets
- repositories/triage_cache_repository.py    → fetch individual triages
- services/overview_service.py               → pre-computed aggregate read/refresh
- dtos/response.py                           → OverviewResponse shape
- dtos/llm.py                                → TriageOutput for the ticket sample table
"""

import asyncio
import random
from typing import Coroutine, TypeVar

import pandas as pd
import streamlit as st

from db.redis_client import redis_client
from db.session import SessionLocal
from dtos.response import OverviewResponse
from repositories.ticket_repository import TicketRepository
from repositories.triage_cache_repository import TriageCacheRepository
from services.overview_service import OverviewService


# Page config — must be the first Streamlit call

st.set_page_config(
    page_title="TicketSense",
    page_icon="🎟️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# Larger caption helper — Streamlit's built-in st.caption renders quite small.
# This wraps st.markdown with explicit styling so all helper text is legible.

def big_caption(text: str) -> None:
    st.markdown(
        f'<p style="font-size: 1.05rem; color: rgba(150, 150, 150, 1); '
        f'line-height: 1.55; margin-top: -8px; margin-bottom: 1rem;">{text}</p>',
        unsafe_allow_html=True,
    )


# Persistent event loop — shared across all async calls in the script.
#
# Why not asyncio.run()? It creates a fresh loop each call and closes it after.
# Our module-level redis_client and SQLAlchemy engine cache connections that
# are bound to the loop they were created in — using a different loop next
# call triggers "Event loop is closed" during teardown.
#
# @st.cache_resource memoizes the loop across Streamlit reruns so the same
# loop (and its bound connections) lives for the entire dashboard session.

T = TypeVar("T")


@st.cache_resource
def _event_loop() -> asyncio.AbstractEventLoop:
    return asyncio.new_event_loop()


def run_async(coro: Coroutine[None, None, T]) -> T:
    """Execute an async coroutine on the script's persistent event loop."""
    return _event_loop().run_until_complete(coro)


# Display orderings — natural sequence for each constrained set so the bar
# charts don't render alphabetically (which is meaningless for "priority")

PRIORITY_ORDER = ["low", "medium", "high", "critical"]
SENTIMENT_ORDER = ["positive", "neutral", "negative", "angry"]
CATEGORY_ORDER = ["billing", "technical", "feature_request", "complaint", "general"]


# Async helpers — Streamlit runs sync, so we wrap each async call in asyncio.run

def load_overview() -> OverviewResponse | None:
    """Single Redis GET for the cached aggregate."""
    async def _go():
        async with SessionLocal() as session:
            svc = OverviewService(
                TicketRepository(session),
                TriageCacheRepository(redis_client),
                redis_client,
            )
            return await svc.get_overview()
    return run_async(_go())


def recompute_overview() -> OverviewResponse:
    """Recompute and overwrite the cached aggregate."""
    async def _go():
        async with SessionLocal() as session:
            svc = OverviewService(
                TicketRepository(session),
                TriageCacheRepository(redis_client),
                redis_client,
            )
            return await svc.refresh_overview()
    return run_async(_go())


def load_sample_tickets(n: int = 10) -> list[dict]:
    """Pull a small random sample of tickets joined with their triage labels.

    Returns plain dicts for direct rendering in st.dataframe.
    """
    async def _go():
        async with SessionLocal() as session:
            tickets = await TicketRepository(session).list_all(limit=10_000)
        # Pick n random tickets so the sample looks different each refresh
        sample = random.sample(tickets, min(n, len(tickets)))
        cache_repo = TriageCacheRepository(redis_client)

        rows = []
        for t in sample:
            triage = await cache_repo.get(t.id)
            rows.append({
                "id": t.id,
                "subject": t.subject[:60] + ("…" if len(t.subject) > 60 else ""),
                "from_name": t.from_name,
                "priority": triage.priority if triage else "—",
                "category": triage.category if triage else "—",
                "sentiment": triage.sentiment if triage else "—",
                "summary": (triage.summary[:80] + "…") if triage and len(triage.summary) > 80 else (triage.summary if triage else "—"),
            })
        return rows
    return run_async(_go())


# Header

st.title("TicketSense")
big_caption(
    "LLM-powered support-ticket triage — classifies incoming emails by priority, "
    "category, and sentiment. Aggregates pre-computed in Redis; dashboard reads "
    "one key per page load."
)

# Refresh button — recomputes the overview key in Redis when clicked
with st.sidebar:
    st.header("Controls")
    if st.button("Refresh overview", type="primary", use_container_width=True):
        with st.spinner("Recomputing aggregates from Redis…"):
            recompute_overview()
        st.success("Overview recomputed.")
        st.rerun()


# Load overview

overview = load_overview()

if overview is None:
    st.warning(
        "No overview cached yet. Either run `scripts/triage_all` to populate "
        "Redis, or click **Refresh overview** in the sidebar."
    )
    st.stop()


# KPI row — four metric cards

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total tickets", overview.total_tickets)
col2.metric("Critical", overview.by_priority.get("critical", 0))
col3.metric("Angry", overview.by_sentiment.get("angry", 0))
col4.metric("Technical", overview.by_category.get("technical", 0))


# Three breakdown charts side-by-side

def ordered_df(counts: dict, order: list[str], col_label: str) -> pd.DataFrame:
    """Coerce a counts dict into a DataFrame ordered by domain convention,
    not alphabetically. Missing categories show as 0."""
    data = [{col_label: k, "count": counts.get(k, 0)} for k in order]
    return pd.DataFrame(data).set_index(col_label)


st.subheader("Breakdowns")
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("**By priority**")
    st.bar_chart(ordered_df(overview.by_priority, PRIORITY_ORDER, "priority"))

with c2:
    st.markdown("**By category**")
    st.bar_chart(ordered_df(overview.by_category, CATEGORY_ORDER, "category"))

with c3:
    st.markdown("**By sentiment**")
    st.bar_chart(ordered_df(overview.by_sentiment, SENTIMENT_ORDER, "sentiment"))


# Random sample of triaged tickets

st.subheader("Random sample of triaged tickets")
big_caption("Refresh the page to draw a new random sample.")

sample = load_sample_tickets(10)
st.dataframe(
    sample,
    use_container_width=True,
    hide_index=True,
    column_config={
        "id": st.column_config.TextColumn("ID", width="small"),
        "subject": st.column_config.TextColumn("Subject"),
        "from_name": st.column_config.TextColumn("From", width="small"),
        "priority": st.column_config.TextColumn("Priority", width="small"),
        "category": st.column_config.TextColumn("Category", width="small"),
        "sentiment": st.column_config.TextColumn("Sentiment", width="small"),
        "summary": st.column_config.TextColumn("Summary"),
    },
)


big_caption(f"Backend: Postgres ({overview.total_tickets} tickets) + Redis (pre-computed overview key)")
