"""Web search tool.

We use Tavily rather than a provider-native (Anthropic/OpenAI/Google)
built-in search tool for one reason: subagents can each be configured with
a *different* model (see `subagents.py`), and provider-native search tools
only work with that same provider's model. A plain callable tool works
identically across every subagent regardless of which model backs it.

If you know every subagent will stay on one provider, swap this for that
provider's built-in tool dict (cheaper, no extra API key) — see the
"Provider search" tab in the Deep Agents quickstart docs for the current
tool-type string, since providers rev these periodically.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Literal

from afrivest_ai.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from tavily import TavilyClient

        if not settings.tavily_api_key:
            raise RuntimeError(
                "TAVILY_API_KEY is not set. Set it in your environment before "
                "invoking the agent."
            )
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


def internet_search(
    query: str,
    max_results: int = settings.search_max_results,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
) -> dict:
    """Search the web for current information.

    Use this for anything that needs up-to-date facts: regulations, company
    names, funding rounds, exchange rates, news. Prefer specific queries
    (e.g. "Bank of Ghana fintech sandbox 2026" over "Ghana fintech rules").

    Args:
        query: The search query.
        max_results: Max number of results to return (keep this small;
            large result sets bloat context — the agent should issue more,
            narrower searches instead of one broad one).
        topic: `"finance"` biases results toward financial/market sources,
            `"news"` toward recent news, `"general"` is the default.
        include_raw_content: Set True only when you need the full page text
            (e.g. to quote a regulation precisely). This is expensive on
            context — prefer False and follow up with a narrower search.

    Returns:
        A dict with a `results` list of `{title, url, content, score,
        published_date}` and an optional `answer` summary.
    """
    client = _get_client()
    started_at = perf_counter()
    logger.debug(
        "Web search started topic=%s max_results=%d query_chars=%d",
        topic,
        max_results,
        len(query),
    )
    try:
        result = client.search(
            query=query,
            max_results=max_results,
            topic=topic,
            include_raw_content=include_raw_content,
        )
    except Exception:
        logger.exception("Web search failed topic=%s query_chars=%d", topic, len(query))
        raise

    logger.info(
        "Web search completed topic=%s result_count=%d duration_seconds=%.2f",
        topic,
        len(result.get("results", [])),
        perf_counter() - started_at,
    )
    return result
