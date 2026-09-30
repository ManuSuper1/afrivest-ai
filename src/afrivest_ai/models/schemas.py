"""Structured data contracts for AfriVest Intelligence.

Every subagent is bound to one of these schemas via `response_format=`,
so the deep agent harness forces the model to emit valid, typed JSON for
each research track (regulatory, competitive, financial, currency) instead
of free-text prose. The orchestrator then composes those four typed
findings into a single `InvestmentDossier`, which is the artifact the
FastAPI layer will eventually serve to the frontend.

Keep these schemas the single source of truth: the frontend's TypeScript
types and the FastAPI response models should both be generated /
hand-mirrored from this file to avoid drift.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Shared primitives
# --------------------------------------------------------------------------


class Citation(BaseModel):
    """A single evidence source backing a claim in the dossier."""

    title: str = Field(description="Title of the source page or document.")
    url: str = Field(description="Direct URL to the source.")
    publisher: str | None = Field(
        default=None, description="Publisher or site name, e.g. 'Bank of Ghana'."
    )
    published_date: str | None = Field(
        default=None, description="Publication date as stated by the source, if known."
    )
    note: str | None = Field(
        default=None, description="One-line note on what this source supports."
    )


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"


class InvestorType(str, Enum):
    DIASPORA = "diaspora"
    FOREIGN_INVESTOR = "foreign_investor"
    LOCAL_FOUNDER = "local_founder"
    OTHER = "other"


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------


class MarketEntryRequest(BaseModel):
    """The user-facing input that kicks off a market-entry research run."""

    country: str = Field(description="Target African country, e.g. 'Ghana'.")
    sector: str = Field(description="Target sector, e.g. 'fintech', 'agritech'.")
    investment_goal: str = Field(
        description="Free-text statement of what the user wants to achieve, "
        "e.g. 'Launch a B2C remittance app targeting the diaspora corridor.'"
    )
    investor_type: InvestorType = InvestorType.OTHER
    budget_usd: float | None = Field(
        default=None, description="Approximate available capital in USD, if known."
    )
    time_horizon_months: int | None = Field(
        default=None, description="Planned time horizon for market entry, in months."
    )
    notes: str | None = Field(default=None, description="Any extra context from the user.")

    @field_validator("country", "sector")
    @classmethod
    def _strip_and_require(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


# --------------------------------------------------------------------------
# Per-track findings (one schema per subagent)
# --------------------------------------------------------------------------


class RegulatoryFindings(BaseModel):
    """Output schema for the legal / regulatory subagent."""

    licensing_requirements: list[str] = Field(
        description="Licenses, permits, or registrations required to operate legally."
    )
    key_regulators: list[str] = Field(
        description="Government bodies or regulators the entity must engage with."
    )
    foreign_ownership_rules: str = Field(
        description="Summary of foreign ownership caps, local-partner requirements, or "
        "restricted-sector rules that apply."
    )
    data_and_sector_specific_compliance: list[str] = Field(
        default_factory=list,
        description="Sector-specific compliance obligations, e.g. data protection, "
        "central bank sandbox rules, AML/KYC requirements.",
    )
    estimated_setup_timeline: str = Field(
        description="Rough estimate of how long registration + licensing takes."
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description="Regulatory risks or blockers that could stop or delay market entry.",
    )
    overall_regulatory_risk: RiskLevel
    sources: list[Citation] = Field(default_factory=list)


class CompetitorProfile(BaseModel):
    name: str
    description: str
    estimated_stage: str | None = Field(
        default=None, description="e.g. 'seed', 'Series A', 'bootstrapped', 'incumbent'."
    )
    differentiator: str | None = Field(
        default=None, description="What this competitor is known for / their edge."
    )


class CompetitiveLandscape(BaseModel):
    """Output schema for the market / competitor-benchmarking subagent."""

    market_size_estimate: str = Field(
        description="Best-available estimate of market size / growth trajectory, with caveats."
    )
    competitors: list[CompetitorProfile] = Field(default_factory=list)
    market_gaps: list[str] = Field(
        default_factory=list, description="Underserved segments or unmet needs identified."
    )
    barriers_to_entry: list[str] = Field(default_factory=list)
    distribution_channels: list[str] = Field(
        default_factory=list,
        description="How players in this market typically acquire customers.",
    )
    sources: list[Citation] = Field(default_factory=list)


class FinancialRiskAssessment(BaseModel):
    """Output schema for the financial-risk subagent."""

    typical_setup_cost_usd_range: str = Field(
        description="Rough range of capital needed to set up and reach initial traction."
    )
    tax_regime_summary: str
    funding_landscape: str = Field(
        description="Availability of local VC/angel/grant/DFI funding for this sector."
    )
    repatriation_of_profits: str = Field(
        description="Rules and friction around repatriating profits or dividends abroad."
    )
    key_financial_risks: list[str] = Field(default_factory=list)
    overall_financial_risk: RiskLevel
    sources: list[Citation] = Field(default_factory=list)


class CurrencyRiskAssessment(BaseModel):
    """Output schema for the currency / FX-risk subagent."""

    local_currency_code: str = Field(description="ISO 4217 code, e.g. 'GHS'.")
    fx_rate_usd_to_local: float | None = Field(
        default=None, description="Latest observed USD -> local currency rate, if fetched."
    )
    twelve_month_volatility_note: str = Field(
        description="Qualitative/quantitative summary of recent currency volatility."
    )
    convertibility_and_capital_controls: str = Field(
        description="Any restrictions on currency conversion or capital movement."
    )
    hedging_recommendations: list[str] = Field(default_factory=list)
    overall_currency_risk: RiskLevel
    sources: list[Citation] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Final composed deliverable
# --------------------------------------------------------------------------


class GoNoGoRecommendation(str, Enum):
    GO = "go"
    CONDITIONAL_GO = "conditional_go"
    NO_GO = "no_go"


class InvestmentDossier(BaseModel):
    """The final, structured market-entry brief the orchestrator produces.

    This is what gets persisted to the virtual filesystem and is the shape
    the FastAPI layer should return to the frontend.
    """

    report_id: str
    country: str
    sector: str
    executive_summary: str = Field(
        description="3-6 sentence plain-language summary of the opportunity and verdict."
    )
    regulatory: RegulatoryFindings
    competitive_landscape: CompetitiveLandscape
    financial_risk: FinancialRiskAssessment
    currency_risk: CurrencyRiskAssessment
    recommendation: GoNoGoRecommendation
    confidence: float = Field(ge=0.0, le=1.0, description="Model's confidence in the verdict.")
    key_risks: list[str] = Field(
        description="Cross-cutting top risks, deduplicated and ranked by severity."
    )
    recommended_next_steps: list[str] = Field(
        description="Concrete next actions for the user, ordered by priority."
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"use_enum_values": False}
