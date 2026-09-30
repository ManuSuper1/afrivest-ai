"""End-to-end example: run one market-entry research job and print the dossier.

Usage:
    export ANTHROPIC_API_KEY=...
    export TAVILY_API_KEY=...
    python examples/run_example.py
"""

from __future__ import annotations

import asyncio
import json

from afrivest_ai import InvestmentDossier, MarketEntryRequest, arun_market_entry_research
from afrivest_ai.models.schemas import InvestorType


async def main() -> None:
    request = MarketEntryRequest(
        country="Ghana",
        sector="fintech",
        investment_goal=(
            "Launch a mobile-first remittance and bill-payment app targeting the "
            "Ghanaian diaspora in the UK and US, sending money home."
        ),
        investor_type=InvestorType.DIASPORA,
        budget_usd=150_000,
        time_horizon_months=9,
    )

    result = await arun_market_entry_research(request)
    dossier: InvestmentDossier = result.dossier

    print(f"\nreport_id: {result.report_id}")
    print(f"recovered_from_backup: {result.recovered_from_backup}")
    print("\n" + "=" * 70)
    print(dossier.model_dump_json(indent=2))
    print("=" * 70)
    print(f"\nRecommendation: {dossier.recommendation.value.upper()} "
          f"(confidence {dossier.confidence:.0%})")
    print(f"\n{dossier.executive_summary}")


if __name__ == "__main__":
    asyncio.run(main())
