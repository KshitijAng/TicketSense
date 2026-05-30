"""
LLM-side DTOs. These are the structured shapes the LLM is FORCED to produce
when called via `with_structured_output()` — invalid outputs are rejected before they reach us.

Descriptions in this file become part of the prompt the LLM sees per field. Write them like instructions.
"""

from typing import Literal
from pydantic import BaseModel, Field


class TriageOutput(BaseModel):  # What Groq returns for a triage call — constrained by this schema
    priority: Literal["low", "medium", "high", "critical"] = Field(   # Literal[...] = LLM must pick exactly one of these strings.
        ...,
        description=(
            "How urgent is this ticket? "
            "critical = production outage, security incident, or churn threat from a paying customer. "
            "high = blocked workflow, time-sensitive issue, formal escalation. "
            "medium = non-urgent issue affecting daily work. "
            "low = general question, onboarding help, or feature request."
        ),
    )
    category: Literal["billing", "technical", "feature_request", "complaint", "general"] = Field(
        ...,
        description=(
            "What kind of ticket is this? "
            "billing = payments, invoices, plan changes, refunds. "
            "technical = errors, bugs, login issues, API failures, integration problems. "
            "feature_request = asking for new functionality or improvements. "
            "complaint = frustration, dissatisfaction, churn risk. "
            "general = questions, onboarding, how-to, anything else."
        ),
    )
    sentiment: Literal["positive", "neutral", "negative", "angry"] = Field(
        ...,
        description=(
            "How is the customer feeling? "
            "positive = grateful, excited, happy. "
            "neutral = professional, businesslike, calm. "
            "negative = frustrated, disappointed. "
            "angry = furious, threatening, escalating to executives or legal."
        ),
    )
    summary: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="One sentence (max 500 chars) summarizing what the customer is asking or reporting. Do not paraphrase — capture the core issue or request.",
    )
    tags: list[str] = Field(
        ...,
        description="2 to 5 short kebab-case tags capturing key signals (e.g., 'login-issue', 'auth-error', 'urgent', 'churn-risk', 'refund-request'). Tags should help filter and search later.",
    )
