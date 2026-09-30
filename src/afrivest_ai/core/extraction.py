"""Fallback dossier recovery.

`response_format` on the orchestrator is the primary path to a validated
`InvestmentDossier` (see agent.py). It is usually reliable, but structured
extraction on a *top-level* agent that also has many tools available is a
known-flaky combination in the current deepagents/langchain stack — see
https://github.com/langchain-ai/deepagents/issues/330. The orchestrator's
system prompt also instructs it to write the dossier to
`/dossiers/{report_id}.json` as a durable backup, specifically so this
module can recover it if `structured_response` comes back `None`.

This also doubles as the read path for "give me the dossier for a report
I already ran", independent of the original thread — useful once the
FastAPI layer needs a plain `GET /reports/{report_id}`.
"""

from __future__ import annotations

import json

from deepagents.backends import StoreBackend
from deepagents.backends.utils import file_data_to_string
from langgraph.store.base import BaseStore
from pydantic import ValidationError

from afrivest_ai.models.schemas import InvestmentDossier


class DossierNotFoundError(Exception):
    pass


class DossierParseError(Exception):
    def __init__(self, report_id: str, raw: str, cause: Exception):
        super().__init__(f"Persisted dossier for report_id={report_id!r} failed to parse: {cause}")
        self.report_id = report_id
        self.raw = raw
        self.cause = cause


def read_persisted_dossier(
    store: BaseStore, report_id: str, org_id: str = "default"
) -> InvestmentDossier:
    """Read `/dossiers/{report_id}.json` back out of the store directly.

    Mirrors the same namespace convention `backend.py` configures for the
    agent's `StoreBackend` route (`(org_id, "dossiers")`), and the same
    leading-slash key convention `CompositeBackend` produces after
    stripping the `/dossiers/` route prefix.
    """
    backend = StoreBackend(namespace=lambda _rt: (org_id, "dossiers"), store=store)
    result = backend.read(f"/{report_id}.json")

    if result.error or result.file_data is None:
        raise DossierNotFoundError(
            f"No persisted dossier found for report_id={report_id!r}, org_id={org_id!r}: "
            f"{result.error}"
        )

    raw = file_data_to_string(result.file_data)
    try:
        return InvestmentDossier.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DossierParseError(report_id, raw, exc) from exc
