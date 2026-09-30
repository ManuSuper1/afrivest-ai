"""Run-scoped, immutable context for a single agent invocation.

This is *not* application state — it's metadata about who is asking and
which report this run belongs to, used to namespace persisted storage
(see `backend.py`). When the FastAPI layer lands, this is where
`org_id`/`user_id` from the auth layer should flow in, so that
`StoreBackend` scopes each org's dossiers separately.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchContext:
    report_id: str
    org_id: str = "default"
    user_id: str | None = None
