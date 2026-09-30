# AfriVest AI — Deep Agent Research Engine

The AI core for **AfriVest Intelligence**: a LangChain [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)
orchestrator that turns `(country, sector, investment goal)` into a
structured, evidence-cited `InvestmentDossier` — regulatory findings,
competitive landscape, financial risk, currency risk, and a go / conditional-go /
no-go recommendation.

The package exposes async-friendly Python functions
(`run_market_entry_research` / `arun_market_entry_research`) that take a
`MarketEntryRequest` and return a validated `InvestmentDossier`. A FastAPI
application is also included in `afrivest_ai.api.main`, with streaming and
report-retrieval endpoints for the web client.

## Architecture

```
                        ┌─────────────────────────┐
                        │   Orchestrator agent      │
  MarketEntryRequest ─▶ │  (create_deep_agent)      │─▶ InvestmentDossier
                        │  writes /dossiers/*.json  │
                        └─────────────┬─────────────┘
                                      │ task() tool, parallel delegation
              ┌───────────┬──────────┼──────────┬───────────┐
              ▼           ▼          ▼          ▼
        legal-regulatory  market-  financial-  currency-fx-
           -analyst    competition  risk-       analyst
                        -analyst    analyst
        (each subagent has its own response_format= Pydantic schema —
         it returns validated JSON, not prose, to the orchestrator)
```

- **Orchestrator** (`agent.py`): the top-level deep agent. Delegates to
  four specialist subagents via the built-in `task` tool, synthesizes their
  findings, and emits a structured `InvestmentDossier`.
- **Subagents** (`subagents.py`): `legal-regulatory-analyst`,
  `market-competition-analyst`, `financial-risk-analyst`,
  `currency-fx-analyst`. Each is bound to its own Pydantic schema via
  `response_format=ToolStrategy(...)`, so deepagents JSON-serializes their
  `structured_response` straight into the orchestrator's tool result —
  no re-parsing prose.
- **Tools** (`tools/`): Tavily web search (provider-agnostic, works no
  matter which model backs a given subagent) and a currency-rate snapshot
  tool (Frankfurter API).
- **Backend / persistence** (`backend.py`): a `CompositeBackend` — the
  agent's scratch work stays in ephemeral `StateBackend` (thread-scoped),
  finished dossiers under `/dossiers/` persist to a durable `StoreBackend`,
  namespaced per `org_id` so tenants can't read each other's reports.
- **Runner** (`runner.py`): the public entry point. Handles thread/report
  IDs, invokes the agent with the configured `recursion_limit`, and falls
  back to reading the persisted dossier file if `structured_response`
  comes back empty (see "Known reliability note" below).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # fill in ANTHROPIC_API_KEY and TAVILY_API_KEY at minimum
```

```bash
export $(grep -v '^#' .env | xargs)   # or use direnv / your process manager
python examples/run_example.py
```

## Configuration

Everything is env-driven — see `.env.example` and `config.py`. The two
settings that matter most for "letting the agent run longer":

| Setting | What it bounds |
|---|---|
| `AFRIVEST_ORCHESTRATOR_MAX_TOKENS` / `AFRIVEST_SUBAGENT_MAX_TOKENS` | Max tokens **per LLM completion**. A dossier synthesis turn or a dense regulatory summary can be long — raise this if you see truncated JSON. |
| `AFRIVEST_RECURSION_LIMIT` | Max **LangGraph steps** (tool calls + LLM turns) in one `invoke`/`stream` call. A 4-subagent run with a few search rounds each easily needs 150–300 steps; too low and LangGraph raises `GraphRecursionError` mid-run. |

Swap models per-role without touching code:

```bash
AFRIVEST_ORCHESTRATOR_MODEL=anthropic:claude-sonnet-4-6
AFRIVEST_SUBAGENT_MODEL=openai:gpt-5.5   # e.g. cheaper model for the 4 parallel subagents
```

## Running the FastAPI API and viewing logs

Start the development API from `ai-api/` with:

```bash
./run_server.sh
```

Application logs are written to the terminal. They include report IDs,
research phases, subagent/tool names, durations, and failure tracebacks;
prompts, search query text, and raw research results are not logged. Set
`AFRIVEST_DEBUG=true` in `.env` to enable more detailed AfriVest debug logs.
The API exposes `GET /health`, `POST /reports/stream`, `GET /reports/{id}`,
and `POST /reports/async`.

## Known reliability note

Top-level `response_format` combined with a large tool surface is a
known-flaky combination in the current `deepagents`/`langchain` stack
(`structured_response` intermittently comes back `None` — see
[deepagents#330](https://github.com/langchain-ai/deepagents/issues/330)).
The orchestrator's prompt also writes the dossier to
`/dossiers/{report_id}.json` as a durable backup; `runner.py` reads it back
if `structured_response` is missing, so callers always get a validated
`InvestmentDossier` or a clear exception — never a silent partial result.
`RunResult.recovered_from_backup` tells you which path was taken, which is
worth logging/alerting on if it starts happening often (it'd point at a
model or prompt regression worth investigating).

## Known data-coverage gap

`tools/fx.py` uses Frankfurter (ECB reference rates), which does **not**
cover most African currencies except ZAR — GHS, NGN, KES, etc. will hit
its `error` path. This is handled honestly: the tool returns an explicit
error the currency subagent is instructed to fall back on `internet_search`
for, rather than silently returning a wrong or stale number. For production,
swap the implementation behind `get_exchange_rate_snapshot`'s signature for
a data source with real African-currency coverage (a paid FX vendor or
individual central-bank APIs).

## Testing without burning API credits

`create_deep_agent()` and everything in `agent.py`/`subagents.py`/
`backend.py` only *wires up* objects — no network calls happen until you
actually `.invoke()`/`.ainvoke()`. That means `build_agent()` is a fast,
free way to catch config/wiring errors (bad schema, bad backend routing,
missing required kwarg) before spending a single token:

```bash
ANTHROPIC_API_KEY=sk-test-dummy TAVILY_API_KEY=test python -c \
  "from afrivest_ai import build_agent; build_agent(); print('OK')"
```

## Project layout

```
src/afrivest_ai/
├── schemas.py          # Pydantic contracts — MarketEntryRequest, per-track findings, InvestmentDossier
├── config.py             # env-driven Settings
├── prompts.py             # orchestrator + subagent system prompts
├── tools/
│   ├── search.py          # Tavily internet_search
│   └── fx.py               # currency-rate snapshot
├── runtime_context.py      # ResearchContext (org/report scoping)
├── backend.py                # CompositeBackend + checkpointer/store factory
├── subagents.py               # 4 declarative SubAgent specs
├── agent.py                    # create_deep_agent() assembly
├── extraction.py                # fallback dossier recovery
├── runner.py                     # public entry point
└── streaming.py                   # SSE-ready progress events
```
