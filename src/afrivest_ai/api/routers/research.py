import asyncio
import json
import logging
import uuid
from time import perf_counter
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, BackgroundTasks, Header, HTTPException
from sse_starlette.sse import EventSourceResponse

from afrivest_ai.api.dependencies import get_agent_bundle
from afrivest_ai.core.agent import AgentBundle
from afrivest_ai.core.runner import arun_market_entry_research, _build_prompt
from afrivest_ai.core.streaming import stream_market_entry_research
from afrivest_ai.models.schemas import MarketEntryRequest, InvestmentDossier

router = APIRouter(prefix="/reports", tags=["Research"])
logger = logging.getLogger(__name__)


@router.post("/stream")
async def create_report_stream(
    request: MarketEntryRequest,
    org_id: str = Header("default", alias="X-Org-ID"),
    bundle: AgentBundle = Depends(get_agent_bundle),
):
    """
    Kicks off a deep-agent market entry research job and streams the progress 
    using Server-Sent Events (SSE) for a premium real-time UX.
    """
    report_id = str(uuid.uuid4())
    thread_id = report_id

    prompt = _build_prompt(request, report_id)
    started_at = perf_counter()
    logger.info(
        "Research stream accepted report_id=%s country=%s sector=%s",
        report_id,
        request.country,
        request.sector,
    )

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            async for chunk in stream_market_entry_research(
                bundle, prompt, report_id=report_id, thread_id=thread_id, org_id=org_id
            ):
                if chunk.get("type") == "done":
                    logger.info(
                        "Research stream finished report_id=%s dossier_included=%s "
                        "duration_seconds=%.2f",
                        report_id,
                        bool(chunk.get("dossier")),
                        perf_counter() - started_at,
                    )
                elif chunk.get("type") == "error":
                    logger.error(
                        "Research stream reported an error report_id=%s",
                        report_id,
                    )
                yield {"event": "update", "data": json.dumps(chunk)}
                await asyncio.sleep(0.01)
        except Exception:
            logger.exception(
                "Research stream failed report_id=%s duration_seconds=%.2f",
                report_id,
                perf_counter() - started_at,
            )
            yield {
                "event": "update",
                "data": json.dumps(
                    {
                        "type": "error",
                        "message": (
                            "Research failed. Check the API terminal logs using this "
                            "report ID for details, then try again."
                        ),
                    }
                ),
            }

    return EventSourceResponse(event_generator())

@router.get("/{report_id}", response_model=InvestmentDossier)
async def get_report(
    report_id: str,
    org_id: str = Header("default", alias="X-Org-ID"),
    bundle: AgentBundle = Depends(get_agent_bundle),
):
    from afrivest_ai.core.extraction import (
        DossierNotFoundError,
        DossierParseError,
        read_persisted_dossier,
    )

    if not bundle.store:
        logger.error(
            "Report lookup failed report_id=%s: persistence is not configured",
            report_id,
        )
        raise HTTPException(status_code=500, detail="Persistence store not configured.")
    try:
        dossier = read_persisted_dossier(bundle.store, report_id, org_id=org_id)
        logger.info("Report retrieved report_id=%s", report_id)
        return dossier
    except DossierNotFoundError:
        logger.info("Report not found report_id=%s", report_id)
        raise HTTPException(status_code=404, detail="Report not found.")
    except DossierParseError as e:
        logger.exception("Persisted report could not be parsed report_id=%s", report_id)
        raise HTTPException(status_code=500, detail=f"Failed to parse report: {e}")


@router.post("/async", response_model=dict)
async def create_report_async(
    request: MarketEntryRequest,
    background_tasks: BackgroundTasks,
    org_id: str = Header("default", alias="X-Org-ID"),
    bundle: AgentBundle = Depends(get_agent_bundle),
):
    """
    Fire-and-forget endpoint. Returns a report_id immediately.
    The agent runs in the background. Client can poll GET /reports/{id} later.
    """
    report_id = str(uuid.uuid4())
    logger.info(
        "Async research accepted report_id=%s country=%s sector=%s",
        report_id,
        request.country,
        request.sector,
    )

    async def run_task():
        started_at = perf_counter()
        try:
            result = await arun_market_entry_research(
                request, report_id=report_id, org_id=org_id, bundle=bundle
            )
            logger.info(
                "Async research completed report_id=%s recovered_from_backup=%s "
                "duration_seconds=%.2f",
                report_id,
                result.recovered_from_backup,
                perf_counter() - started_at,
            )
        except Exception:
            logger.exception(
                "Async research failed report_id=%s duration_seconds=%.2f",
                report_id,
                perf_counter() - started_at,
            )

    background_tasks.add_task(run_task)
    return {"status": "accepted", "report_id": report_id, "message": "Research started."}
