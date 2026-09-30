"""Streaming helper.

Wraps `agent.astream(..., stream_mode=["updates", "messages"])` into a
flat sequence of small, JSON-serializable event dicts, so the future
FastAPI layer can forward each one as an SSE `data:` line (or a WebSocket
message) with zero LangGraph-specific knowledge. This is intentionally a
thin translation layer, not a queueing/backpressure system — that belongs
in the FastAPI layer once it exists.

Event shapes yielded:
    {"type": "todo_update", "todos": [...]}
    {"type": "tool_call", "tool": str, "args": dict}
    {"type": "tool_result", "tool": str, "content": str}
    {"type": "subagent_start", "subagent": str}
    {"type": "message_delta", "text": str}
    {"type": "done", "dossier": dict}
    {"type": "error", "message": str}
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from afrivest_ai.core.agent import AgentBundle
from afrivest_ai.config import settings
from afrivest_ai.models.runtime_context import ResearchContext

logger = logging.getLogger(__name__)


async def stream_market_entry_research(
    bundle: AgentBundle,
    prompt: str,
    *,
    report_id: str,
    thread_id: str,
    org_id: str = "default",
    user_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    context = ResearchContext(report_id=report_id, org_id=org_id, user_id=user_id)

    started_at = perf_counter()
    logger.info("Agent stream started report_id=%s thread_id=%s", report_id, thread_id)
    last_todos: list[dict] | None = None
    final_state: dict | None = None
    subagents_by_call_id: dict[str, str] = {}

    try:
        async for stream_mode, chunk in bundle.agent.astream(
            {"messages": [{"role": "user", "content": prompt}]},
            config={
                "recursion_limit": settings.recursion_limit,
                "configurable": {"thread_id": thread_id},
            },
            context=context,
            stream_mode=["updates", "messages"],
        ):
            if stream_mode == "updates":
                for node_name, node_update in chunk.items():
                    if not isinstance(node_update, dict):
                        continue
                    final_state = node_update
                    logger.debug(
                        "Agent node updated report_id=%s node=%s",
                        report_id,
                        node_name,
                    )

                    todos = node_update.get("todos")
                    if todos is not None and todos != last_todos:
                        last_todos = todos
                        logger.info(
                            "Research plan updated report_id=%s task_count=%d",
                            report_id,
                            len(todos),
                        )
                        yield {"type": "todo_update", "todos": todos}

                    for message in node_update.get("messages", []) or []:
                        tool_calls = getattr(message, "tool_calls", None)
                        if tool_calls:
                            for call in tool_calls:
                                name = call.get("name", "")
                                args = call.get("args", {})
                                if name == "task":
                                    subagent = args.get("subagent_type", "unknown")
                                    call_id = call.get("id")
                                    if call_id:
                                        subagents_by_call_id[call_id] = subagent
                                    logger.info(
                                        "Subagent started report_id=%s subagent=%s",
                                        report_id,
                                        subagent,
                                    )
                                    yield {
                                        "type": "subagent_start",
                                        "subagent": subagent,
                                    }
                                elif name == "InvestmentDossier":
                                    logger.info(
                                        "Dossier synthesis started report_id=%s",
                                        report_id,
                                    )
                                    yield {"type": "synthesis_start"}
                                else:
                                    logger.info(
                                        "Agent tool started report_id=%s tool=%s",
                                        report_id,
                                        name,
                                    )
                                    yield {
                                        "type": "tool_call",
                                        "tool": name,
                                        "args": args,
                                    }

                        message_type = getattr(message, "type", None)
                        if message_type == "tool":
                            tool_name = getattr(message, "name", "unknown")
                            tool_call_id = getattr(message, "tool_call_id", None)
                            if tool_name == "task" and tool_call_id:
                                subagent = subagents_by_call_id.pop(tool_call_id, None)
                                if subagent:
                                    logger.info(
                                        "Subagent completed report_id=%s subagent=%s",
                                        report_id,
                                        subagent,
                                    )
                                    yield {
                                        "type": "subagent_complete",
                                        "subagent": subagent,
                                    }
                            content = getattr(message, "content", "")
                            logger.debug(
                                "Agent tool completed report_id=%s tool=%s "
                                "result_chars=%d",
                                report_id,
                                tool_name,
                                len(content) if isinstance(content, str) else 0,
                            )
                            yield {
                                "type": "tool_result",
                                "tool": tool_name,
                                "content": _truncate(content),
                            }

            elif stream_mode == "messages":
                message_chunk, _metadata = chunk
                content = getattr(message_chunk, "content", None)
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and "text" in block
                    )
                if text:
                    yield {"type": "message_delta", "text": text}
    except Exception:
        logger.exception(
            "Agent stream failed report_id=%s duration_seconds=%.2f",
            report_id,
            perf_counter() - started_at,
        )
        yield {
            "type": "error",
            "message": (
                "Research failed. Check the API terminal logs using this report ID "
                "for details, then try again."
            ),
        }
        return

    from afrivest_ai.core.runner import _resolve_result
    try:
        if final_state is not None:
            result = _resolve_result(final_state, bundle, report_id, thread_id, org_id)
            logger.info(
                "Agent stream completed report_id=%s recovered_from_backup=%s "
                "duration_seconds=%.2f",
                report_id,
                result.recovered_from_backup,
                perf_counter() - started_at,
            )
            yield {"type": "done", "dossier": result.dossier.model_dump(mode="json")}
            return
    except Exception:
        logger.exception("Could not resolve final dossier report_id=%s", report_id)

    logger.error(
        "Agent stream ended without a dossier report_id=%s duration_seconds=%.2f",
        report_id,
        perf_counter() - started_at,
    )
    yield {
        "type": "error",
        "message": (
            "Research ended without a complete report. Check the API terminal logs "
            "using this report ID for details, then try again."
        ),
    }


def _truncate(content: Any, limit: int = 500) -> str:
    text = content if isinstance(content, str) else str(content)
    return text if len(text) <= limit else text[:limit] + "…"
