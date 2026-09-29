"""Pydantic schemas exchanged between agents. Every artifact in the pipeline is typed
and validated so the Writer Agent can never silently accept malformed data."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class SourceStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class Source(BaseModel):
    id: int
    url: str
    title: str = ""
    domain: str = ""
    query: str = ""
    status: SourceStatus = SourceStatus.OK
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    snippet: str = ""
    # Stretch 3: Source Trust Weighting
    trust_tier: str = "medium"   # "high" | "medium" | "low"
    trust_reason: str = ""


class ResearchFinding(BaseModel):
    """One atomic fact pulled from a source, prior to analysis."""
    competitor: str
    category: str  # pricing | product | partnership | acquisition | funding | market_trend
    statement: str
    source_ids: list[int]


class EvidenceStrength(str, Enum):
    CONFIRMED = "confirmed"          # 2+ independent sources agree
    SINGLE_SOURCE = "single_source"  # 1 source only
    NEEDS_VERIFICATION = "needs_verification"  # weak / contradictory / speculative


class AnalyzedInsight(BaseModel):
    competitor: str
    category: str
    insight: str
    strength: EvidenceStrength
    source_ids: list[int]
    is_risk: bool = False
    is_opportunity: bool = False
    # Stretch 1: Confidence Scoring
    confidence_tag: str = "unknown"  # "corroborated" | "single-source" | "unknown"


class RunMetadata(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    execution_time_seconds: float | None = None
    search_count: int = 0
    sources_attempted: int = 0
    sources_failed: int = 0
    execution_steps: int = 0
    max_sources: int = 0
    max_steps: int = 0
    limit_reached: bool = False
    status: str = "running"  # running | completed | completed_with_partial_failures | stopped_at_limit | failed


class Briefing(BaseModel):
    topic: str
    competitors: list[str]
    executive_summary: str
    pricing_and_product_moves: str
    market_signals: str
    strategic_recommendations: str
    sources: list[Source]
    insights: list[AnalyzedInsight]
    metadata: RunMetadata
    markdown: str = ""
