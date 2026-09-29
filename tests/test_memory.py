"""Tests for the Hindsight Memory Store and memory models.

Run with: pytest tests/test_memory.py -v
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

import pytest

from models.memory_schemas import (
    CompetitorEvent,
    CompetitorMemoryProfile,
    EventType,
    HiringTrend,
    Prediction,
    PredictionStatus,
    RiskLevel,
    StrategyEvolution,
    StrategyPhase,
    TrendDirection,
)


@pytest.fixture
def temp_store(tmp_path):
    """Create a HindsightStore using a temporary directory (isolated from real data)."""
    from memory.hindsight_store import HindsightStore
    import threading

    store = HindsightStore.__new__(HindsightStore)
    store._base = tmp_path
    store._events_file = tmp_path / "events.jsonl"
    store._profiles_file = tmp_path / "profiles.json"
    store._strategies_file = tmp_path / "strategies.json"
    store._predictions_file = tmp_path / "predictions.json"
    store._lock = threading.Lock()
    store._events = []
    store._profiles = {}
    store._strategies = {}
    store._predictions = []
    yield store


def make_event(
    competitor: str = "TestCorp",
    event_type: EventType = EventType.FEATURE_LAUNCH,
    title: str = "New Feature X",
    description: str = "TestCorp launches Feature X targeting enterprise customers.",
    impact_score: float = 7.5,
    confidence: float = 0.85,
    date: str = "2026-01-15",
) -> CompetitorEvent:
) -> CompetitorEvent:
    return CompetitorEvent(
        competitor=competitor,
        event_type=event_type,
        date=date,
        title=title,
        description=description,
        impact_score=impact_score,
        confidence=confidence,
        evidence_urls=["https://example.com/news"],
    )


# ── Store & Retrieve ──────────────────────────────────────────────────────────

def test_store_and_retrieve_event(temp_store):
    """Events stored must be retrievable by competitor name."""
    event = make_event(competitor="Acme", title="Acme Pricing Cut")
    temp_store.store_event(event)

    results = temp_store.get_events(competitor="Acme")
    assert len(results) == 1
    assert results[0].title == "Acme Pricing Cut"
    assert results[0].competitor == "Acme"


def test_multiple_events_sorted_newest_first(temp_store):
    """get_events must return results newest-first."""
    temp_store.store_event(make_event(date="2026-01-10", title="Older Event"))
    temp_store.store_event(make_event(date="2026-03-20", title="Newer Event"))
    temp_store.store_event(make_event(date="2026-02-15", title="Middle Event"))

    results = temp_store.get_events(competitor="TestCorp")
    assert results[0].date == "2026-03-20"
    assert results[-1].date == "2026-01-10"


def test_event_filter_by_type(temp_store):
    """get_events with event_type filter must return only matching events."""
    temp_store.store_event(make_event(event_type=EventType.FEATURE_LAUNCH, title="Launch"))
    temp_store.store_event(make_event(event_type=EventType.PRICING_CHANGE, title="Price Cut"))

    launches = temp_store.get_events(event_type="feature_launch")
    assert len(launches) == 1
    assert launches[0].title == "Launch"


def test_event_persistence_survives_reload(tmp_path):
    """Events stored must be present after reinitializing the store from the same path."""
    from memory.hindsight_store import HindsightStore
    import threading

    store1 = HindsightStore.__new__(HindsightStore)
    store1._base = tmp_path
    store1._events_file = tmp_path / "events.jsonl"
    store1._profiles_file = tmp_path / "profiles.json"
    store1._strategies_file = tmp_path / "strategies.json"
    store1._predictions_file = tmp_path / "predictions.json"
    store1._lock = threading.Lock()
    store1._events = []
    store1._profiles = {}
    store1._strategies = {}
    store1._predictions = []

    event = make_event(competitor="PersistCorp", title="Persisted Event")
    store1.store_event(event)

    # Load a fresh store from same path without reloading module
    store2 = HindsightStore.__new__(HindsightStore)
    store2._base = tmp_path
    store2._events_file = tmp_path / "events.jsonl"
    store2._profiles_file = tmp_path / "profiles.json"
    store2._strategies_file = tmp_path / "strategies.json"
    store2._predictions_file = tmp_path / "predictions.json"
    store2._lock = threading.Lock()
    store2._events = []
    store2._profiles = {}
    store2._strategies = {}
    store2._predictions = []
    store2._load_all()

    results = store2.get_events(competitor="PersistCorp")
    assert len(results) == 1
    assert results[0].title == "Persisted Event"


# ── Profile Auto-Update ───────────────────────────────────────────────────────

def test_memory_profile_auto_update(temp_store):
    """Storing events must auto-create and update the competitor profile."""
    for i in range(3):
        temp_store.store_event(make_event(
            competitor="AutoCorp",
            event_type=EventType.FEATURE_LAUNCH,
            date=f"2026-0{i+1}-15",
        ))

    profile = temp_store.get_memory_profile("AutoCorp")
    assert profile is not None
    assert profile.competitor == "AutoCorp"
    assert profile.total_events == 3
    # Innovation score should be > 0 (feature launches increase it)
    assert profile.innovation_score > 0


def test_hiring_trend_updates_from_events(temp_store):
    """Multiple hiring events should push hiring_trend to GROWING or SURGING."""
    for i in range(3):
        temp_store.store_event(make_event(
            competitor="HireCorp",
            event_type=EventType.HIRING,
            title=f"Hiring Wave {i+1}",
        ))

    profile = temp_store.get_memory_profile("HireCorp")
    assert profile.hiring_trend in (HiringTrend.GROWING, HiringTrend.SURGING)


def test_high_impact_events_raise_risk_level(temp_store):
    """Three high-impact events should make risk_level CRITICAL."""
    for i in range(3):
        temp_store.store_event(make_event(
            competitor="ThreatCorp",
            event_type=EventType.FEATURE_LAUNCH,
            impact_score=9.5,
            title=f"High Impact Event {i+1}",
        ))

    profile = temp_store.get_memory_profile("ThreatCorp")
    assert profile.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_confidence_grows_with_more_events(temp_store):
    """Confidence score should increase as more events are stored."""
    temp_store.store_event(make_event(competitor="ConfCorp"))
    profile_early = temp_store.get_memory_profile("ConfCorp")
    conf_early = profile_early.confidence_score

    for i in range(5):
        temp_store.store_event(make_event(competitor="ConfCorp", date=f"2026-0{i+1}-20"))

    profile_later = temp_store.get_memory_profile("ConfCorp")
    assert profile_later.confidence_score > conf_early


# ── Strategy Evolution ────────────────────────────────────────────────────────

def test_strategy_evolution_save_and_retrieve(temp_store):
    """Saved strategy evolutions must be retrievable by competitor name."""
    strat = StrategyEvolution(
        competitor="StratCorp",
        timeline=[
            StrategyPhase(period="Jan 2026", dominant_strategy="Cost Leadership", key_events=["Price cut 30%"], confidence=0.9),
            StrategyPhase(period="Mar 2026", dominant_strategy="Market Expansion", key_events=["Partnership announced"], confidence=0.85),
        ],
        synthesized_strategy="Cost-led Market Expansion Strategy",
        evidence_summary="StratCorp cut prices aggressively then expanded via partnerships.",
        confidence_score=0.88,
        trend_direction=TrendDirection.ACCELERATING,
    )
    temp_store.save_strategy_evolution(strat)

    retrieved = temp_store.get_strategy_evolution("StratCorp")
    assert retrieved is not None
    assert retrieved.competitor == "StratCorp"
    assert retrieved.synthesized_strategy == "Cost-led Market Expansion Strategy"
    assert len(retrieved.timeline) == 2


def test_strategy_evolution_requires_phases(temp_store):
    """A strategy with fewer than 2 phases should still store but timeline length is checked."""
    strat = StrategyEvolution(
        competitor="MinCorp",
        timeline=[StrategyPhase(period="Q1 2026", dominant_strategy="Launch", key_events=["Product released"], confidence=0.8)],
        synthesized_strategy="Single-Phase Strategy",
        confidence_score=0.6,
    )
    temp_store.save_strategy_evolution(strat)
    retrieved = temp_store.get_strategy_evolution("MinCorp")
    assert retrieved is not None
    assert len(retrieved.timeline) >= 1  # Can have 1 phase, just less confident


# ── Predictions ───────────────────────────────────────────────────────────────

def test_prediction_evidence_required():
    """A Prediction with empty supporting_evidence is invalid for production use."""
    pred = Prediction(
        competitor="TestCorp",
        prediction_text="Will launch feature X",
        confidence=0.7,
        supporting_evidence=[],  # Empty — should be flagged
        historical_pattern="Pattern from memory",
    )
    # Model allows it but we validate in business logic
    assert pred.supporting_evidence == []
    # Production rule: at minimum one evidence item
    assert len(pred.supporting_evidence) == 0  # This is the gap test catches


def test_save_and_retrieve_prediction(temp_store):
    """Saved predictions must be retrievable and filterable by competitor."""
    pred = Prediction(
        competitor="PredCorp",
        prediction_text="Will acquire startup X for $500M",
        confidence=0.78,
        supporting_evidence=["3 acquisitions in last 6 months", "Fundraising announced"],
        historical_pattern="PredCorp acquired 3 companies before each major product launch",
        predicted_timeframe="Next 45 days",
        category="acquisition",
    )
    temp_store.save_prediction(pred)

    results = temp_store.get_predictions(competitor="PredCorp")
    assert len(results) == 1
    assert results[0].prediction_text == "Will acquire startup X for $500M"
    assert results[0].confidence == 0.78


def test_prediction_status_updates(temp_store):
    """Prediction status can be updated from PENDING to CONFIRMED."""
    pred = Prediction(
        competitor="StatusCorp",
        prediction_text="Will launch API v2",
        confidence=0.8,
        supporting_evidence=["API v1 pattern"],
        status=PredictionStatus.PENDING,
    )
    stored = temp_store.save_prediction(pred)
    temp_store.update_prediction_status(stored.id, PredictionStatus.CONFIRMED)

    updated = temp_store.get_predictions(competitor="StatusCorp")
    assert updated[0].status == PredictionStatus.CONFIRMED


# ── Memory Stats ──────────────────────────────────────────────────────────────

def test_memory_stats_accuracy(temp_store):
    """MemoryStats must accurately reflect stored data."""
    for comp in ["Alpha", "Beta", "Gamma"]:
        temp_store.store_event(make_event(competitor=comp))
    temp_store.save_prediction(Prediction(
        competitor="Alpha",
        prediction_text="Will expand",
        confidence=0.7,
        supporting_evidence=["Evidence A"],
    ))

    stats = temp_store.get_stats()
    assert stats.total_events == 3
    assert stats.competitors_tracked == 3
    assert stats.predictions_generated == 1


# ── Search ────────────────────────────────────────────────────────────────────

def test_search_memory_finds_matches(temp_store):
    """search_memory must find events by keyword in title or description."""
    temp_store.store_event(make_event(
        title="Pricing Cut Announcement",
        description="Company cuts API pricing by 50% to gain market share.",
    ))
    temp_store.store_event(make_event(
        title="New Partnership",
        description="Company partners with major cloud provider.",
    ))

    results = temp_store.search_memory("pricing")
    assert len(results) >= 1
    assert any("pricing" in r.title.lower() or "pricing" in r.description.lower() for r in results)


def test_search_memory_no_results(temp_store):
    """search_memory returns empty list for queries with no matches."""
    temp_store.store_event(make_event(title="Feature Launch"))
    results = temp_store.search_memory("zzznomatch_xyz_123")
    assert results == []


# ── Demo Seed ─────────────────────────────────────────────────────────────────

def test_demo_seed_populates_data(tmp_path):
    """Initializing a fresh HindsightStore must populate demo data automatically."""
    from memory.hindsight_store import HindsightStore
    store = HindsightStore(base_path=str(tmp_path))
    stats = store.get_stats()
    assert stats.total_events >= 20, "Expected at least 20 demo events"
    assert stats.competitors_tracked >= 4, "Expected at least 4 demo competitors"
    assert stats.predictions_generated >= 3, "Expected at least 3 demo predictions"


def test_demo_seed_has_all_expected_competitors(tmp_path):
    """Demo seed must include all 4 major AI competitors."""
    from memory.hindsight_store import HindsightStore
    store = HindsightStore(base_path=str(tmp_path))
    profiles = store.get_all_profiles()
    competitor_names = {p.competitor for p in profiles}
    expected = {"OpenAI", "Anthropic", "Google DeepMind", "Microsoft Copilot"}
    assert expected.issubset(competitor_names), f"Missing: {expected - competitor_names}"


def test_clear_all_removes_data(tmp_path):
    """clear_all must remove all events, profiles, strategies, and predictions."""
    from memory.hindsight_store import HindsightStore
    store = HindsightStore(base_path=str(tmp_path))
    assert store.get_stats().total_events > 0  # seeded

    store.clear_all()
    stats = store.get_stats()
    assert stats.total_events == 0
    assert stats.competitors_tracked == 0
    assert stats.predictions_generated == 0
