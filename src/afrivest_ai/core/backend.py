"""Virtual filesystem backend and persistence wiring.

Two different kinds of "persistence" are in play here and it's worth being
precise about which is which:

- **Checkpointer**: persists the LangGraph *conversation/run state*
  (messages, todos, in-flight tool calls) so a thread can be resumed or
  inspected. Scoped by `thread_id`.
- **Store**: persists arbitrary key/value data *across threads*. We route
  the `/dossiers/` path of the agent's virtual filesystem here so a
  finished dossier survives after its research thread ends, and can be
  read back by report_id from a different thread (e.g. a later chat, or
  a plain REST GET once the FastAPI layer exists).

Everything else the agent writes (scratch notes, intermediate subagent
output) stays in the default `StateBackend`, i.e. it's thread-scoped and
disappears once the thread is no longer checkpointed. That's intentional —
you don't want every subagent's raw search dump kept forever.
"""

from __future__ import annotations

from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from afrivest_ai.config import settings


def _dossier_namespace(runtime) -> tuple[str, ...]:
    """Scope persisted dossiers by org, so orgs can't read each other's reports.

    `runtime.context` is the `ResearchContext` passed to `agent.invoke(context=...)`.
    Falls back to a shared "default" namespace if no context was supplied
    (e.g. ad hoc local testing).
    """
    ctx = runtime.context
    org_id = getattr(ctx, "org_id", None) or "default"
    return (org_id, "dossiers")


def build_backend(store: BaseStore | None) -> CompositeBackend:
    """Build the composite virtual filesystem for the main agent.

    `/dossiers/` -> durable, cross-thread `StoreBackend`.
    everything else -> ephemeral, thread-scoped `StateBackend`.
    """
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/dossiers/": StoreBackend(namespace=_dossier_namespace, store=store),
        },
    )


def build_checkpointer_and_store() -> tuple[BaseCheckpointSaver | None, BaseStore | None]:
    """Return `(checkpointer, store)` for the configured persistence backend.

    "memory" is process-local and only for local development — state is
    lost on restart and never shared across workers. For anything running
    behind the FastAPI layer with more than one worker process, switch
    `AFRIVEST_PERSISTENCE=postgres` and set `AFRIVEST_POSTGRES_URI`; this
    requires `pip install langgraph-checkpoint-postgres` (not a default
    dependency here, since not every deployment needs it).
    """
    if settings.persistence_backend == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from langgraph.store.postgres import PostgresStore
        except ImportError as exc:  # pragma: no cover - guidance path
            raise ImportError(
                "AFRIVEST_PERSISTENCE=postgres requires "
                "`pip install langgraph-checkpoint-postgres`."
            ) from exc

        # Both context managers open a pooled connection; callers are
        # expected to keep the returned objects alive for process lifetime
        # (e.g. instantiate once at FastAPI startup, not per-request).
        checkpointer_cm = PostgresSaver.from_conn_string(settings.postgres_uri)
        store_cm = PostgresStore.from_conn_string(settings.postgres_uri)
        checkpointer = checkpointer_cm.__enter__()
        store = store_cm.__enter__()
        checkpointer.setup()
        store.setup()
        return checkpointer, store

    # Default: in-memory, single-process. Fine for local dev and for the
    # example script in examples/run_example.py.
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.store.memory import InMemoryStore

    return MemorySaver(), InMemoryStore()
