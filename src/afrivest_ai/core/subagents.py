"""Subagent definitions.

Each subagent gets `response_format=ToolStrategy(<Schema>, handle_errors=True)`.
Per the deepagents harness, when a subagent has `response_format` set, its
`structured_response` is JSON-serialized and returned as the `task` tool's
`ToolMessage` content to the orchestrator — replacing the default
"last assistant message" extraction. In practice this means the
orchestrator receives clean, schema-validated JSON per research track
instead of prose it has to re-parse. `handle_errors=True` lets the
subagent retry internally if its first structured-output attempt fails
schema validation, instead of surfacing a raw validation error as the
task result.
"""

from __future__ import annotations

from langchain.agents.structured_output import ToolStrategy
from langchain.chat_models import init_chat_model

from afrivest_ai.config import settings
from afrivest_ai.core.prompts import (
    CURRENCY_SUBAGENT_PROMPT,
    FINANCIAL_SUBAGENT_PROMPT,
    LEGAL_SUBAGENT_PROMPT,
    MARKET_SUBAGENT_PROMPT,
)
from afrivest_ai.models.schemas import (
    CompetitiveLandscape,
    CurrencyRiskAssessment,
    FinancialRiskAssessment,
    RegulatoryFindings,
)
from afrivest_ai.core.tools import get_exchange_rate_snapshot, internet_search


def _subagent_model():
    """Fresh model instance per call site so each subagent doesn't share
    mutable client state; cheap since `init_chat_model` construction is
    lightweight (no network call)."""
    return init_chat_model(settings.subagent_model, max_tokens=settings.subagent_max_tokens)


def build_subagents() -> list[dict]:
    """Build the four declarative subagent specs.

    Built lazily via a function (rather than a module-level constant) so
    `settings` is read at call time, not import time — this matters if a
    caller mutates env vars / reloads settings before building the agent
    (e.g. in tests).
    """
    legal_subagent = {
        "name": "legal-regulatory-analyst",
        "description": (
            "Researches licensing, foreign-ownership rules, and regulatory "
            "compliance requirements for entering a specific African market "
            "and sector. Call this first — other tracks sometimes depend on "
            "knowing whether the sector is regulated or restricted."
        ),
        "system_prompt": LEGAL_SUBAGENT_PROMPT,
        "tools": [internet_search],
        "model": _subagent_model(),
        "response_format": ToolStrategy(RegulatoryFindings, handle_errors=True),
    }

    market_subagent = {
        "name": "market-competition-analyst",
        "description": (
            "Researches market size, named competitors, market gaps, and "
            "barriers to entry for a specific African market and sector."
        ),
        "system_prompt": MARKET_SUBAGENT_PROMPT,
        "tools": [internet_search],
        "model": _subagent_model(),
        "response_format": ToolStrategy(CompetitiveLandscape, handle_errors=True),
    }

    financial_subagent = {
        "name": "financial-risk-analyst",
        "description": (
            "Researches setup costs, tax regime, funding landscape, and "
            "profit-repatriation rules for a specific African market and sector."
        ),
        "system_prompt": FINANCIAL_SUBAGENT_PROMPT,
        "tools": [internet_search],
        "model": _subagent_model(),
        "response_format": ToolStrategy(FinancialRiskAssessment, handle_errors=True),
    }

    currency_subagent = {
        "name": "currency-fx-analyst",
        "description": (
            "Researches exchange-rate trends, volatility, capital controls, "
            "and hedging options for a specific African country's currency."
        ),
        "system_prompt": CURRENCY_SUBAGENT_PROMPT,
        "tools": [internet_search, get_exchange_rate_snapshot],
        "model": _subagent_model(),
        "response_format": ToolStrategy(CurrencyRiskAssessment, handle_errors=True),
    }

    return [legal_subagent, market_subagent, financial_subagent, currency_subagent]
