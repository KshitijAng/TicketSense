"""LLM-powered triage service.

Calls Groq with TriageOutput as the constrained schema (structured output).
Implements two layers of resilience:

  Layer 1: retry with exponential backoff on 429 (rate limit) errors.
  Layer 2: model-level fallback — if the primary model exhausts retries or
           fails for any reason, the call is repeated against a smaller,
           faster fallback model with its own rate-limit pool.

services/triage_service.py uses:
- dtos/llm.py            → TriageOutput (the constrained LLM output schema)
- db/session.py          → settings.groq_api_key
"""

import asyncio
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

from db.session import settings
from dtos.llm import TriageOutput


logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────────────

PRIMARY_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
FALLBACK_MODEL = "llama-3.1-8b-instant"

# Backoff schedule for 429 (rate-limit) retries. 
# Applied INDEPENDENTLY to whichever model is currently being tried.
RETRY_DELAYS_SECONDS = [1, 2, 4]


SYSTEM_PROMPT = (
    "You are an expert support ticket triager. "
    "Analyze the email below and produce structured triage labels — priority, "
    "category, sentiment, a one-sentence summary, and 2–5 short kebab-case tags. "
    "Pick exactly one value from each constrained field; do not invent new values."
)


# ────────────────────────────────────────────────────────────────────────────
# Service
# ────────────────────────────────────────────────────────────────────────────

class TriageService:
    """Async service that turns (subject, body) into a validated TriageOutput.

    Wraps two Groq models behind one method — caller doesn't see which model
    actually produced the result.
    """

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.groq_api_key

        # Each ChatGroq + with_structured_output pair forces the model to return
        # JSON matching TriageOutput's schema.
        self._primary = ChatGroq(model=PRIMARY_MODEL, api_key=key, temperature=0).with_structured_output(TriageOutput)
        self._fallback = ChatGroq(model=FALLBACK_MODEL, api_key=key, temperature=0).with_structured_output(TriageOutput)

    async def triage(self, subject: str, body: str) -> TriageOutput:
        """Triage one ticket. Tries primary model with retries, then fallback."""
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=self._format_ticket(subject, body)),
        ]

        # --- Layer 1+2: try primary with retries; fall back if exhausted ---
        try:
            return await self._call_with_retry(self._primary, messages, model_name=PRIMARY_MODEL)
        except Exception as primary_err:
            logger.warning(
                "Primary model %s failed (%s). Falling back to %s.",
                PRIMARY_MODEL, type(primary_err).__name__, FALLBACK_MODEL,
            )

        # --- Fallback model path ---
        try:
            return await self._call_with_retry(self._fallback, messages, model_name=FALLBACK_MODEL)
        except Exception as fallback_err:
            logger.error(
                "Fallback model %s also failed (%s). Both models exhausted.",
                FALLBACK_MODEL, type(fallback_err).__name__,
            )
            raise   # Let the caller decide what to do (mark for later retry, skip, etc.)

    @staticmethod
    def _format_ticket(subject: str, body: str) -> str:
        """Build the user-message payload from the raw ticket fields."""
        return f"Subject: {subject}\n\nBody:\n{body}"

    @staticmethod
    async def _call_with_retry(
        chain: Any,                # LangChain runnable wrapping ChatGroq + structured output
        messages: list,
        model_name: str,           # Just for logging
    ) -> TriageOutput:
        """Invoke `chain` with exponential backoff on rate-limit errors."""
        for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
            try:
                result = await chain.ainvoke(messages)
                # If result is already a TriageOutput, return it as-is. 
                # Otherwise, parse it through Pydantic to turn it into one.
                return result if isinstance(result, TriageOutput) else TriageOutput.model_validate(result)
            except Exception as e:
                err_text = str(e).lower()
                is_rate_limited = "429" in err_text or "rate" in err_text or "too many" in err_text

                if is_rate_limited and attempt < len(RETRY_DELAYS_SECONDS):
                    delay = RETRY_DELAYS_SECONDS[attempt]
                    logger.warning(
                        "%s rate-limited (attempt %d). Sleeping %ds.",
                        model_name, attempt + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                # Either not a rate-limit error or out of retries — propagate up
                # so the outer try in triage() can decide to fall back.
                raise
        # Should be unreachable, but satisfies the type checker
        raise RuntimeError(f"{model_name} retry loop exited without result")
