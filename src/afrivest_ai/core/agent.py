"""Orchestrator deep agent assembly.

This module builds the compiled LangGraph agent once per process. Building
it is cheap (no network calls — `init_chat_model` and `create_deep_agent`
just wire up objects), but a Postgres-backed checkpointer/store opens a
pooled connection, so treat `AgentBundle` as a singleton: build it once at
process/app startup (e.g. FastAPI `lifespan`), not per-request.
"""

from __future__ import annotations

from dataclasses import dataclass

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from afrivest_ai.core.backend import build_backend, build_checkpointer_and_store
from afrivest_ai.config import settings
from afrivest_ai.core.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from afrivest_ai.models.runtime_context import ResearchContext
from afrivest_ai.models.schemas import InvestmentDossier
from afrivest_ai.core.subagents import build_subagents
from afrivest_ai.core.tools import internet_search


@dataclass
class AgentBundle:
    agent: CompiledStateGraph
    checkpointer: BaseCheckpointSaver | None
    store: BaseStore | None


def build_agent() -> AgentBundle:
    """Construct the orchestrator agent and its persistence backends."""
    settings.validate()

    checkpointer, store = build_checkpointer_and_store()
    backend = build_backend(store=store)

    orchestrator_model = init_chat_model(
        settings.orchestrator_model, max_tokens=settings.orchestrator_max_tokens
    )

    middleware = []
    if settings.enable_task_planning:
        # Gives the orchestrator a `write_todos` tool. Not required for
        # correctness, but lets a frontend show live "researching legal...
        # researching competitors..." progress by reading agent state.
        middleware.append(TodoListMiddleware())

    agent = create_deep_agent(
        model=orchestrator_model,
        tools=[internet_search],
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        middleware=middleware,
        subagents=build_subagents(),
        backend=backend,
        response_format=ToolStrategy(InvestmentDossier, handle_errors=True),
        context_schema=ResearchContext,
        checkpointer=checkpointer,
        store=store,
        debug=settings.debug,
        name="afrivest-orchestrator",
    )

    return AgentBundle(agent=agent, checkpointer=checkpointer, store=store)
