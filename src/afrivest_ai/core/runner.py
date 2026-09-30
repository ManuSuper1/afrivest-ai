"""High-level API for running a market-entry research job.

This is the module the future FastAPI layer should import — one function
call in, one validated `InvestmentDossier` out (or a well-typed exception).
Everything about deep agents, subagents, and backends stays behind this
boundary.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from deepagents.backends import StoreBackend
from afrivest_ai.core.agent import AgentBundle, build_agent
from afrivest_ai.config import settings
from afrivest_ai.core.extraction import DossierNotFoundError, DossierParseError, read_persisted_dossier
from afrivest_ai.models.runtime_context import ResearchContext
from afrivest_ai.models.schemas import InvestmentDossier, MarketEntryRequest

logger = logging.getLogger("afrivest_ai.core.runner")

_bundle: AgentBundle | None = None


def get_agent_bundle() -> AgentBundle:
    """Process-wide singleton. Build once; reuse across requests.

    In a FastAPI app, call `build_agent()` once in the `lifespan` startup
    hook instead of relying on this module-level singleton, so you control
    exactly when the (possibly pooled-connection) backends are created and
    torn down. This lazy singleton exists so the example script and quick
    local testing don't need that ceremony.
    """
    global _bundle
    if _bundle is None:
        _bundle = build_agent()
    return _bundle


def _build_prompt(request: MarketEntryRequest, report_id: str) -> str:
    lines = [
        f"report_id: {report_id}",
        f"Country: {request.country}",
        f"Sector: {request.sector}",
        f"Investor type: {request.investor_type.value}",
        f"Investment goal: {request.investment_goal}",
    ]
    if request.budget_usd is not None:
        lines.append(f"Approximate budget (USD): {request.budget_usd:,.0f}")
    if request.time_horizon_months is not None:
        lines.append(f"Time horizon: {request.time_horizon_months} months")
    if request.notes:
        lines.append(f"Additional notes: {request.notes}")
    lines.append(
        "\nProduce a complete InvestmentDossier for this request, following your "
        "instructions: delegate to the four subagents, synthesize the findings, "
        f"and write the final dossier to /dossiers/{report_id}.json."
    )
    return "\n".join(lines)


@dataclass
class RunResult:
    dossier: InvestmentDossier
    report_id: str
    thread_id: str
    recovered_from_backup: bool
    """True if `structured_response` was missing and the dossier was
    recovered from the persisted `/dossiers/{report_id}.json` file instead."""


def run_market_entry_research(
    request: MarketEntryRequest,
    *,
    report_id: str | None = None,
    org_id: str = "default",
    user_id: str | None = None,
    thread_id: str | None = None,
) -> RunResult:
    """Run a full market-entry research job synchronously and return the dossier.

    For a FastAPI endpoint, prefer `arun_market_entry_research` (below) so
    the event loop isn't blocked for the (likely tens-of-seconds-to-minutes)
    duration of the run.
    """
    bundle = get_agent_bundle()
    report_id = report_id or str(uuid.uuid4())
    thread_id = thread_id or report_id
    context = ResearchContext(report_id=report_id, org_id=org_id, user_id=user_id)

    result = bundle.agent.invoke(
        {"messages": [{"role": "user", "content": _build_prompt(request, report_id)}]},
        config={
            "recursion_limit": settings.recursion_limit,
            "configurable": {"thread_id": thread_id},
        },
        context=context,
    )

    return _resolve_result(result, bundle, report_id, thread_id, org_id)


async def arun_market_entry_research(
    request: MarketEntryRequest,
    *,
    report_id: str | None = None,
    org_id: str = "default",
    user_id: str | None = None,
    thread_id: str | None = None,
    bundle: AgentBundle | None = None,
) -> RunResult:
    """Async counterpart of `run_market_entry_research`. Use this from FastAPI."""
    bundle = bundle or get_agent_bundle()
    report_id = report_id or str(uuid.uuid4())
    thread_id = thread_id or report_id
    context = ResearchContext(report_id=report_id, org_id=org_id, user_id=user_id)

    result = await bundle.agent.ainvoke(
        {"messages": [{"role": "user", "content": _build_prompt(request, report_id)}]},
        config={
            "recursion_limit": settings.recursion_limit,
            "configurable": {"thread_id": thread_id},
        },
        context=context,
    )

    return _resolve_result(result, bundle, report_id, thread_id, org_id)


def _resolve_result(
    result: dict, bundle: AgentBundle, report_id: str, thread_id: str, org_id: str
) -> RunResult:
    structured = result.get("structured_response")
    if structured is not None:
        dossier = _finalize_dossier(structured, bundle, report_id, org_id)
        return RunResult(
            dossier=dossier,
            report_id=report_id,
            thread_id=thread_id,
            recovered_from_backup=False,
        )

    logger.warning(
        "structured_response missing for report_id=%s; recovering from "
        "/dossiers/%s.json instead.",
        report_id,
        report_id,
    )
    if bundle.store is None:
        raise RuntimeError(
            f"structured_response missing for report_id={report_id!r} and no "
            "store is configured to recover it from. Check AFRIVEST_PERSISTENCE."
        )

    try:
        persisted_dossier = read_persisted_dossier(bundle.store, report_id, org_id=org_id)
    except (DossierNotFoundError, DossierParseError) as exc:
        raise RuntimeError(
            f"Agent run for report_id={report_id!r} finished without a usable "
            f"dossier (structured_response missing and file backup unreadable): {exc}"
        ) from exc

    dossier = _finalize_dossier(persisted_dossier, bundle, report_id, org_id)
    return RunResult(
        dossier=dossier, report_id=report_id, thread_id=thread_id, recovered_from_backup=True
    )


def _finalize_dossier(
    dossier: InvestmentDossier | dict,
    bundle: AgentBundle,
    report_id: str,
    org_id: str,
) -> InvestmentDossier:
    """Apply server-owned report metadata and persist the canonical dossier."""
    finalized = InvestmentDossier.model_validate(dossier).model_copy(
        update={
            "report_id": report_id,
            "generated_at": datetime.now(timezone.utc),
        }
    )
    if bundle.store is not None:
        backend = StoreBackend(
            namespace=lambda _runtime: (org_id, "dossiers"),
            store=bundle.store,
        )
        write_result = backend.write(
            f"/{report_id}.json",
            finalized.model_dump_json(),
        )
        if write_result.error:
            raise RuntimeError(
                f"Could not persist finalized dossier for report_id={report_id!r}: "
                f"{write_result.error}"
            )
    return finalized
