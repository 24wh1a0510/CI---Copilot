"""Pydantic schemas for the Memory-First Competitive Intelligence Copilot.

These models capture everything the Hindsight Memory Agent stores and retrieves:
competitor events, evolving profiles, strategy timelines, and predictions.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enumerations ─────────────────────────────────────────────────────────────

class EventType(str, Enum):
    FEATURE_LAUNCH = "feature_launch"
    PRICING_CHANGE = "pricing_change"
    HIRING = "hiring"
    ACQUISITION = "acquisition"
    FUNDING = "funding"
    PARTNERSHIP = "partnership"
    MARKET_SIGNAL = "market_signal"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HiringTrend(str, Enum):
    SURGING = "surging"
    GROWING = "growing"
    STABLE = "stable"
    DECLINING = "declining"


class TrendDirection(str, Enum):
    ACCELERATING = "accelerating"
    STABLE = "stable"
    PIVOTING = "pivoting"
    DECLINING = "declining"


class PredictionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"


# ── Core Memory Models ────────────────────────────────────────────────────────

class CompetitorEvent(BaseModel):
    """One atomic event stored in persistent Hindsight memory."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    competitor: str
    event_type: EventType
    date: str  # ISO date string YYYY-MM-DD
    title: str
    description: str
    source_ids: list[int] = Field(default_factory=list)
    impact_score: float = Field(default=5.0, ge=0.0, le=10.0)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_urls: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CompetitorMemoryProfile(BaseModel):
    """Continuously evolving intelligence profile for one competitor."""
    competitor: str
    market_focus: str = ""
    innovation_score: float = Field(default=5.0, ge=0.0, le=10.0)
    pricing_strategy: str = "Unknown"
    hiring_trend: HiringTrend = HiringTrend.STABLE
    risk_level: RiskLevel = RiskLevel.MEDIUM
    opportunities: list[str] = Field(default_factory=list)
    threats: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    historical_events: list[CompetitorEvent] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    total_events: int = 0


class StrategyPhase(BaseModel):
    """One discrete phase in a competitor's strategic evolution."""
    period: str  # e.g. "Jan 2026", "Q1 2026"
    dominant_strategy: str
    key_events: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class StrategyEvolution(BaseModel):
    """The synthesized multi-phase strategic narrative for one competitor."""
    competitor: str
    timeline: list[StrategyPhase] = Field(default_factory=list)
    synthesized_strategy: str = ""
    evidence_summary: str = ""
    confidence_score: float = Field(default=0.6, ge=0.0, le=1.0)
    trend_direction: TrendDirection = TrendDirection.STABLE
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class Prediction(BaseModel):
    """A memory-grounded prediction about a competitor's next move."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    competitor: str
    prediction_text: str
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    historical_pattern: str = ""
    predicted_timeframe: str = "Next 30-60 days"
    category: str = "product"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: PredictionStatus = PredictionStatus.PENDING


# ── Aggregate / Summary Models ────────────────────────────────────────────────

class MemoryStats(BaseModel):
    total_events: int = 0
    competitors_tracked: int = 0
    predictions_generated: int = 0
    strategic_alerts: int = 0
    memory_size_kb: float = 0.0


# ── API Request / Response Models ─────────────────────────────────────────────

class BriefingRequest(BaseModel):
    topic: str
    competitors: Optional[list[str]] = None
    date_range_days: int = Field(default=30, ge=1, le=365)
    include_predictions: bool = True


class RunStatus(BaseModel):
    run_id: str
    status: str = "queued"  # queued | running | completed | failed
    progress: int = Field(default=0, ge=0, le=100)
    current_agent: str = ""
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    briefing_id: Optional[str] = None
    error: Optional[str] = None
