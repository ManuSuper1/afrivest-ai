"""Runtime configuration for the AfriVest Intelligence deep agent.

Deliberately dependency-light (stdlib `dataclasses` + `os.environ`) rather
than pulling in `pydantic-settings` for what is currently ~10 scalar
settings. Swap for `pydantic-settings` if this grows real validation needs
(e.g. multiple environments, secrets manager integration).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- Model selection -------------------------------------------------
    # `provider:model` strings, passed straight to `init_chat_model`.
    orchestrator_model: str = field(
        default_factory=lambda: os.getenv(
            "AFRIVEST_ORCHESTRATOR_MODEL", "anthropic:claude-sonnet-4-6"
        )
    )
    subagent_model: str = field(
        default_factory=lambda: os.getenv(
            "AFRIVEST_SUBAGENT_MODEL", "anthropic:claude-sonnet-4-6"
        )
    )

    # --- Output length / run length ---------------------------------------
    # These are the two knobs that matter for "letting the agent run
    # longer": `max_tokens` bounds a single completion, `recursion_limit`
    # bounds the total number of graph steps (tool calls + LLM turns) in
    # one `invoke`/`stream` call. A multi-subagent research run with
    # several search rounds per subagent needs a generous recursion limit
    # or LangGraph will raise `GraphRecursionError` mid-run.
    orchestrator_max_tokens: int = field(
        default_factory=lambda: _env_int("AFRIVEST_ORCHESTRATOR_MAX_TOKENS", 8192)
    )
    subagent_max_tokens: int = field(
        default_factory=lambda: _env_int("AFRIVEST_SUBAGENT_MAX_TOKENS", 6144)
    )
    recursion_limit: int = field(
        default_factory=lambda: _env_int("AFRIVEST_RECURSION_LIMIT", 300)
    )

    # --- Search ------------------------------------------------------------
    tavily_api_key: str | None = field(default_factory=lambda: os.getenv("TAVILY_API_KEY"))
    search_max_results: int = field(
        default_factory=lambda: _env_int("AFRIVEST_SEARCH_MAX_RESULTS", 6)
    )

    # --- FX tool -------------------------------------------------------
    fx_api_base_url: str = field(
        default_factory=lambda: os.getenv(
            "AFRIVEST_FX_API_BASE_URL", "https://api.frankfurter.app"
        )
    )

    # --- Persistence ---------------------------------------------------
    # "memory" is fine for local dev; swap to a Postgres checkpointer/store
    # (langgraph-checkpoint-postgres) for production so dossiers survive
    # process restarts. See backend.py.
    persistence_backend: str = field(
        default_factory=lambda: os.getenv("AFRIVEST_PERSISTENCE", "memory")
    )
    postgres_uri: str | None = field(default_factory=lambda: os.getenv("AFRIVEST_POSTGRES_URI"))

    # --- Misc ------------------------------------------------------------
    enable_task_planning: bool = field(
        default_factory=lambda: _env_bool("AFRIVEST_ENABLE_TASK_PLANNING", True)
    )
    debug: bool = field(default_factory=lambda: _env_bool("AFRIVEST_DEBUG", False))

    def validate(self) -> None:
        """Fail fast with a clear message instead of a deep stack trace mid-run."""
        errors: list[str] = []

        provider = self.orchestrator_model.split(":", 1)[0]
        key_env_by_provider = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google_genai": "GOOGLE_API_KEY",
        }
        required_key = key_env_by_provider.get(provider)
        if required_key and not os.getenv(required_key):
            errors.append(
                f"Model provider '{provider}' selected but {required_key} is not set."
            )

        if not self.tavily_api_key:
            errors.append(
                "TAVILY_API_KEY is not set. The internet_search tool will fail at "
                "call time. Set it, or swap tools/search.py for a provider-native "
                "search tool (see README)."
            )

        if self.persistence_backend == "postgres" and not self.postgres_uri:
            errors.append("AFRIVEST_PERSISTENCE=postgres but AFRIVEST_POSTGRES_URI is not set.")

        if errors:
            raise RuntimeError(
                "Invalid AfriVest AI configuration:\n- " + "\n- ".join(errors)
            )


settings = Settings()
