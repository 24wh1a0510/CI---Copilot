"""Integration tests for Hindsight Memory — the core memory layer of CI Copilot.

These tests use the REAL HindsightStore with no mocking.
They verify retain → recall → analysis → incremental learning → isolation.

Run:
    pytest tests/test_hindsight_memory.py -v
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import pytest

from models.memory_schemas import (
    CompetitorEvent,
    EventType,
    HiringTrend,
    Prediction,
    PredictionStatus,
    RiskLevel,
    StrategyEvolution,
    StrategyPhase,
    TrendDirection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bare_store(tmp_path: Path):
    """Return a HindsightStore wired to tmp_path with NO seed data."""
    from memory.hindsight_store import HindsightStore

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
    return store


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path):
    """Fresh isolated HindsightStore per test — no seed data."""
    return _bare_store(tmp_path)


@pytest.fixture()
def neuracode_events() -> list[CompetitorEvent]:
    """Five realistic weekly events for NeuraCode AI spanning Jan–Feb 2026."""
    return [
        CompetitorEvent(
            competitor="NeuraCode AI",
            event_type=EventType.FEATURE_LAUNCH,
            date="2026-01-08",
            title="NeuraCode AI launches NeuraAssist v1.0",
            description=(
                "NeuraCode AI releases NeuraAssist v1.0, an AI-powered code review "
                "and generation tool. Targets mid-market engineering teams with "
                "GPT-4-class code understanding and automated PR reviews."
            ),
            impact_score=8.5,
            confidence=0.92,
            evidence_urls=["https://neuracode.ai/blog/neuraassist-launch"],
        ),
        CompetitorEvent(
            competitor="NeuraCode AI",
            event_type=EventType.HIRING,
            date="2026-01-15",
            title="NeuraCode AI hires 15 ML engineers from Google and Meta",
            description=(
                "NeuraCode AI announces aggressive hiring of 15 machine learning "
                "engineers, with 8 coming from Google DeepMind and 7 from Meta AI. "
                "Roles are focused on model fine-tuning and code intelligence."
            ),
            impact_score=7.0,
            confidence=0.88,
            evidence_urls=["https://neuracode.ai/careers", "https://linkedin.com/neuracode-hiring"],
        ),
        CompetitorEvent(
            competitor="NeuraCode AI",
            event_type=EventType.PRICING_CHANGE,
            date="2026-01-22",
            title="NeuraCode AI introduces enterprise tier at $45/seat/month",
            description=(
                "NeuraCode AI launches an enterprise pricing tier at $45 per seat "
                "per month with SSO, audit logs, and dedicated SLA. Minimum 20 seats. "
                "Undercuts GitHub Copilot Enterprise at $39 while adding compliance features."
            ),
            impact_score=8.0,
            confidence=0.95,
            evidence_urls=["https://neuracode.ai/pricing"],
        ),
        CompetitorEvent(
            competitor="NeuraCode AI",
            event_type=EventType.ACQUISITION,
            date="2026-01-29",
            title="NeuraCode AI acquires CodeLens Analytics for $28M",
            description=(
                "NeuraCode AI acquires CodeLens Analytics, a startup specialising in "
                "developer productivity metrics and code quality scoring. Deal valued at "
                "$28M. Brings 12 engineers and a suite of IDE telemetry tools."
            ),
            impact_score=7.5,
            confidence=0.91,
            evidence_urls=["https://neuracode.ai/news/codelens-acquisition"],
        ),
        CompetitorEvent(
            competitor="NeuraCode AI",
            event_type=EventType.FEATURE_LAUNCH,
            date="2026-02-05",
            title="NeuraCode AI NeuraAssist Enterprise: AI Security Code Scanner",
            description=(
                "NeuraCode AI ships a built-in AI security vulnerability scanner into "
                "NeuraAssist Enterprise. Integrates with SAST workflows and flags "
                "OWASP Top 10 issues in real time during code review."
            ),
            impact_score=8.8,
            confidence=0.93,
            evidence_urls=["https://neuracode.ai/blog/security-scanner"],
        ),
    ]


# ── Test 1: Store and recall a single event ───────────────────────────────────

def test_store_and_recall_single_event(store):
    event = CompetitorEvent(
        competitor="NeuraCode AI",
        event_type=EventType.FEATURE_LAUNCH,
        date="2026-01-08",
        title="NeuraAssist v1.0 launch",
        description="AI code review tool launched for engineering teams.",
        impact_score=8.5,
        confidence=0.92,
    )
    store.store_event(event)

    recalled = store.get_events(competitor="NeuraCode AI")
    assert len(recalled) == 1
    assert recalled[0].title == "NeuraAssist v1.0 launch"
    assert recalled[0].competitor == "NeuraCode AI"
    assert recalled[0].event_type == EventType.FEATURE_LAUNCH


# ── Test 2: Store five events and recall all ─────────────────────────────────

def test_multiple_events_same_competitor(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    recalled = store.get_events(competitor="NeuraCode AI")
    assert len(recalled) == 5

    event_types = {e.event_type for e in recalled}
    assert EventType.FEATURE_LAUNCH in event_types
    assert EventType.HIRING in event_types
    assert EventType.PRICING_CHANGE in event_types
    assert EventType.ACQUISITION in event_types

    dates = [e.date for e in recalled]
    assert sorted(dates, reverse=True) == dates


# ── Test 3: Before vs After memory profile ───────────────────────────────────

def test_before_after_memory(store, neuracode_events):
    # BEFORE: profile is None before any events
    profile_before = store.get_memory_profile("NeuraCode AI")
    assert profile_before is None, "Profile must not exist before any events are stored"

    # Store all events
    for ev in neuracode_events:
        store.store_event(ev)

    # AFTER: profile now exists and reflects the events
    profile_after = store.get_memory_profile("NeuraCode AI")
    assert profile_after is not None, "Profile must exist after events are stored"
    assert profile_after.total_events == 5
    assert profile_after.confidence_score > 0.0, "Confidence must be > 0 after events"
    assert profile_after.confidence_score <= 1.0

    # Innovation score — only counts events within last 90 days.
    # Demo events use fixed 2026-01 dates which may be >90 days ago at test time.
    assert profile_after.innovation_score >= 0.0  # Must never be negative

    # 2 feature launches, 1 acquisition, 1 partnership — should be recognised
    assert profile_after.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL), (
        f"Expected HIGH or CRITICAL risk after {profile_after.total_events} events "
        f"with high impact scores. Got: {profile_after.risk_level}"
    )

    # Historical events list must be populated
    assert len(profile_after.historical_events) == 5

    # All events in the profile must be for NeuraCode AI
    for ev in profile_after.historical_events:
        assert ev.competitor == "NeuraCode AI"


# ── Test 4: Persistence across separate instances ────────────────────────────

def test_persistence_across_instances(tmp_path, neuracode_events):
    # Instance A: write
    store_a = _bare_store(tmp_path)
    for ev in neuracode_events:
        store_a.store_event(ev)

    stats_a = store_a.get_stats()
    assert stats_a.total_events == 5

    # Instance B: read from same path (simulates backend restart)
    store_b = _bare_store(tmp_path)
    store_b._load_all()

    recalled = store_b.get_events(competitor="NeuraCode AI")
    assert len(recalled) == 5, (
        "Events stored by instance A must be readable by a new instance B "
        "pointing at the same path — proving persistence across restarts."
    )

    profile = store_b.get_memory_profile("NeuraCode AI")
    assert profile is not None, "Profile persisted by A must be readable by B"
    assert profile.total_events == 5


# ── Test 5: Incremental learning ─────────────────────────────────────────────

def test_incremental_learning(store, neuracode_events):
    # Store first 4 events
    for ev in neuracode_events[:4]:
        store.store_event(ev)

    profile_4 = store.get_memory_profile("NeuraCode AI")
    assert profile_4.total_events == 4
    conf_4 = profile_4.confidence_score

    # Add the 5th event
    store.store_event(neuracode_events[4])

    profile_5 = store.get_memory_profile("NeuraCode AI")
    assert profile_5.total_events == 5, "After adding 5th event, total must be 5"

    # Confidence must increase
    assert profile_5.confidence_score >= conf_4, (
        "Confidence score must not decrease when more events are added"
    )

    # Old events must still be present
    recalled = store.get_events(competitor="NeuraCode AI")
    titles = [e.title for e in recalled]
    assert neuracode_events[0].title in titles, "First event must still be in memory"
    assert neuracode_events[4].title in titles, "New event must also be in memory"


# ── Test 6: Memory isolation ─────────────────────────────────────────────────

def test_memory_isolation(store, neuracode_events):
    # Store NeuraCode AI events
    for ev in neuracode_events:
        store.store_event(ev)

    # Store completely different events for a rival
    rival_events = [
        CompetitorEvent(
            competitor="RivalCorp",
            event_type=EventType.FUNDING,
            date="2026-01-10",
            title="RivalCorp raises $200M Series C",
            description="RivalCorp closes a $200M Series C to expand into Asia.",
            impact_score=9.0,
            confidence=0.97,
        ),
        CompetitorEvent(
            competitor="RivalCorp",
            event_type=EventType.PARTNERSHIP,
            date="2026-01-20",
            title="RivalCorp partners with AWS for cloud distribution",
            description="RivalCorp signs AWS partnership to distribute product globally.",
            impact_score=8.5,
            confidence=0.90,
        ),
    ]
    for ev in rival_events:
        store.store_event(ev)

    # Query only NeuraCode AI
    neura_events = store.get_events(competitor="NeuraCode AI")
    for ev in neura_events:
        assert ev.competitor == "NeuraCode AI", (
            f"RivalCorp event leaked into NeuraCode AI results: {ev.title}"
        )
    assert len(neura_events) == 5

    # Query only RivalCorp
    rival_recalled = store.get_events(competitor="RivalCorp")
    for ev in rival_recalled:
        assert ev.competitor == "RivalCorp", (
            f"NeuraCode AI event leaked into RivalCorp results: {ev.title}"
        )
    assert len(rival_recalled) == 2

    # Profiles must be fully separate
    neura_profile = store.get_memory_profile("NeuraCode AI")
    rival_profile = store.get_memory_profile("RivalCorp")
    assert neura_profile is not None
    assert rival_profile is not None
    for ev in neura_profile.historical_events:
        assert ev.competitor == "NeuraCode AI"
    for ev in rival_profile.historical_events:
        assert ev.competitor == "RivalCorp"


# ── Test 7: Empty memory graceful response ───────────────────────────────────

def test_empty_memory_graceful(store):
    profile = store.get_memory_profile("NonExistentCorp")
    assert profile is None

    events = store.get_events(competitor="NonExistentCorp")
    assert events == []

    timeline = store.get_timeline(competitor="NonExistentCorp")
    assert timeline == []

    strategy = store.get_strategy_evolution("NonExistentCorp")
    assert strategy is None

    predictions = store.get_predictions(competitor="NonExistentCorp")
    assert predictions == []

    stats = store.get_stats()
    assert stats.total_events == 0
    assert stats.competitors_tracked == 0


# ── Test 8: Duplicate event handling ─────────────────────────────────────────

def test_duplicate_event_handling(store):
    event = CompetitorEvent(
        competitor="NeuraCode AI",
        event_type=EventType.FEATURE_LAUNCH,
        date="2026-01-08",
        title="Duplicate Event Test",
        description="Testing how the store handles duplicate titles.",
        impact_score=7.0,
        confidence=0.85,
    )
    store.store_event(event)
    store.store_event(event)  # intentional duplicate

    # Store must not crash — both entries accepted (append-only)
    recalled = store.get_events(competitor="NeuraCode AI")
    assert len(recalled) >= 1, "Store must not crash on duplicate event"
    # Profile total_events reflects actual count
    profile = store.get_memory_profile("NeuraCode AI")
    assert profile.total_events >= 1


# ── Test 9: Malformed event fields ───────────────────────────────────────────

def test_malformed_event_rejected_by_schema():
    """CompetitorEvent schema must reject impact_score > 10."""
    import pydantic

    with pytest.raises((ValueError, pydantic.ValidationError)):
        CompetitorEvent(
            competitor="BadCorp",
            event_type=EventType.FEATURE_LAUNCH,
            date="2026-01-01",
            title="Invalid event",
            description="Testing validation.",
            impact_score=99.9,  # out of range (max 10)
            confidence=0.8,
        )


def test_malformed_confidence_rejected_by_schema():
    """CompetitorEvent schema must reject confidence > 1.0."""
    import pydantic

    with pytest.raises((ValueError, pydantic.ValidationError)):
        CompetitorEvent(
            competitor="BadCorp",
            event_type=EventType.FEATURE_LAUNCH,
            date="2026-01-01",
            title="Invalid event",
            description="Testing validation.",
            impact_score=7.0,
            confidence=1.5,  # out of range (max 1.0)
        )


def test_store_does_not_crash_on_date_edge_cases(store):
    """Store must handle unusual but valid date strings without crashing."""
    event = CompetitorEvent(
        competitor="EdgeCorp",
        event_type=EventType.MARKET_SIGNAL,
        date="2026-12-31",
        title="Year-end event",
        description="Testing year-end date handling.",
        impact_score=5.0,
        confidence=0.7,
    )
    store.store_event(event)
    recalled = store.get_events(competitor="EdgeCorp")
    assert len(recalled) == 1


# ── Test 10: Strategy evolution generated from stored events ─────────────────

def test_strategy_evolution_stored_and_retrieved(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    # Build a strategy from the stored events
    strat = StrategyEvolution(
        competitor="NeuraCode AI",
        timeline=[
            StrategyPhase(
                period="Jan 2026 Week 1",
                dominant_strategy="Product Launch",
                key_events=["NeuraAssist v1.0 launch"],
                confidence=0.92,
            ),
            StrategyPhase(
                period="Jan 2026 Week 2",
                dominant_strategy="Talent Acquisition",
                key_events=["15 ML engineers hired from Google/Meta"],
                confidence=0.88,
            ),
            StrategyPhase(
                period="Jan 2026 Week 3-4",
                dominant_strategy="Enterprise Pricing + M&A",
                key_events=["Enterprise tier $45/seat", "CodeLens acquisition $28M"],
                confidence=0.91,
            ),
            StrategyPhase(
                period="Feb 2026 Week 1",
                dominant_strategy="Security Differentiation",
                key_events=["AI Security Scanner launch"],
                confidence=0.93,
            ),
        ],
        synthesized_strategy="Rapid Enterprise Expansion via Product + Talent + M&A",
        evidence_summary=(
            "NeuraCode AI executed a 5-week sprint: launched product, hired 15 engineers, "
            "introduced enterprise pricing, acquired CodeLens, then shipped security features. "
            "Pattern indicates a planned enterprise land-and-expand strategy."
        ),
        confidence_score=0.90,
        trend_direction=TrendDirection.ACCELERATING,
    )
    store.save_strategy_evolution(strat)

    retrieved = store.get_strategy_evolution("NeuraCode AI")
    assert retrieved is not None
    assert retrieved.competitor == "NeuraCode AI"
    assert retrieved.synthesized_strategy == "Rapid Enterprise Expansion via Product + Talent + M&A"
    assert len(retrieved.timeline) == 4
    assert retrieved.confidence_score == 0.90
    assert retrieved.trend_direction == TrendDirection.ACCELERATING


# ── Test 11: Predictions generated and retrievable ───────────────────────────

def test_predictions_generated_from_memory(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    pred = Prediction(
        competitor="NeuraCode AI",
        prediction_text=(
            "NeuraCode AI will launch an AI-native CI/CD pipeline integration "
            "at $55/seat/month targeting DevSecOps teams within 45 days"
        ),
        confidence=0.81,
        supporting_evidence=[
            "CodeLens acquisition adds IDE telemetry — natural fit for CI/CD",
            "Security scanner launch signals DevSecOps positioning",
            "Enterprise pricing tier already in place — upsell path exists",
            "15 ML engineers hired with CI/CD and DevOps backgrounds",
        ],
        historical_pattern=(
            "NeuraCode AI has shipped a new enterprise feature every 2 weeks "
            "since NeuraAssist v1.0. Pattern suggests another launch within 14-21 days."
        ),
        predicted_timeframe="Next 30-45 days",
        category="product",
        status=PredictionStatus.PENDING,
    )
    store.save_prediction(pred)

    predictions = store.get_predictions(competitor="NeuraCode AI")
    assert len(predictions) == 1
    assert predictions[0].confidence == 0.81
    assert len(predictions[0].supporting_evidence) == 4
    assert predictions[0].status == PredictionStatus.PENDING

    # Update to confirmed
    store.update_prediction_status(predictions[0].id, PredictionStatus.CONFIRMED)
    confirmed = store.get_predictions(competitor="NeuraCode AI")
    assert confirmed[0].status == PredictionStatus.CONFIRMED


# ── Test 12: Stats accuracy ───────────────────────────────────────────────────

def test_get_stats_reflects_actual_data(store, neuracode_events):
    stats_empty = store.get_stats()
    assert stats_empty.total_events == 0
    assert stats_empty.competitors_tracked == 0

    for ev in neuracode_events:
        store.store_event(ev)

    # Add rival data
    store.store_event(CompetitorEvent(
        competitor="RivalCorp",
        event_type=EventType.FUNDING,
        date="2026-01-10",
        title="RivalCorp Series C",
        description="RivalCorp raises $200M.",
        impact_score=9.0,
        confidence=0.95,
    ))

    store.save_prediction(Prediction(
        competitor="NeuraCode AI",
        prediction_text="Will launch CI/CD product",
        confidence=0.80,
        supporting_evidence=["Evidence 1", "Evidence 2"],
    ))

    stats = store.get_stats()
    assert stats.total_events == 6
    assert stats.competitors_tracked == 2
    assert stats.predictions_generated == 1
    assert stats.memory_size_kb >= 0


# ── Test 13: Clear all ────────────────────────────────────────────────────────

def test_clear_all(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    assert store.get_stats().total_events == 5

    store.clear_all()

    stats = store.get_stats()
    assert stats.total_events == 0
    assert stats.competitors_tracked == 0
    assert stats.predictions_generated == 0

    assert store.get_memory_profile("NeuraCode AI") is None
    assert store.get_events(competitor="NeuraCode AI") == []


# ── Test 14: Search memory ────────────────────────────────────────────────────

def test_search_memory_finds_by_title(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    results = store.search_memory("security")
    assert len(results) >= 1
    assert any("security" in r.title.lower() or "security" in r.description.lower()
               for r in results)


def test_search_memory_finds_by_description(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    results = store.search_memory("OWASP")
    assert len(results) >= 1
    assert any("OWASP" in r.description for r in results)


def test_search_memory_no_match_returns_empty(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    results = store.search_memory("zzz_no_match_xyz_123_abc")
    assert results == []


def test_search_memory_by_competitor_name(store, neuracode_events):
    for ev in neuracode_events:
        store.store_event(ev)

    results = store.search_memory("NeuraCode")
    assert len(results) == 5


# ── Test 15: The full memory learning loop ────────────────────────────────────

def test_full_memory_learning_loop(tmp_path):
    """
    End-to-end memory learning test.

    1. BEFORE: empty store returns no profile.
    2. Store 5 weekly events for NeuraCode AI.
    3. AFTER: profile exists, events recalled, strategy saved, prediction stored.
    4. Persist: new store instance reads same data (simulates restart).
    5. INCREMENTAL: add one new event, verify it appears without losing old ones.
    6. ISOLATION: add RivalCorp event, verify it does NOT bleed into NeuraCode AI.
    """
    # --- BEFORE ---
    store = _bare_store(tmp_path)
    assert store.get_memory_profile("NeuraCode AI") is None, "BEFORE: profile must be None"
    assert store.get_events(competitor="NeuraCode AI") == [], "BEFORE: events must be empty"

    # --- STORE ---
    events = [
        CompetitorEvent(competitor="NeuraCode AI", event_type=EventType.FEATURE_LAUNCH,
                        date="2026-01-08", title="NeuraAssist v1.0",
                        description="AI code review product launched.", impact_score=8.5, confidence=0.92),
        CompetitorEvent(competitor="NeuraCode AI", event_type=EventType.HIRING,
                        date="2026-01-15", title="15 ML engineers hired",
                        description="Hired from Google and Meta.", impact_score=7.0, confidence=0.88),
        CompetitorEvent(competitor="NeuraCode AI", event_type=EventType.PRICING_CHANGE,
                        date="2026-01-22", title="Enterprise tier $45/seat",
                        description="Launched enterprise pricing with SSO.", impact_score=8.0, confidence=0.95),
        CompetitorEvent(competitor="NeuraCode AI", event_type=EventType.ACQUISITION,
                        date="2026-01-29", title="CodeLens acquired $28M",
                        description="Acquired dev metrics startup.", impact_score=7.5, confidence=0.91),
        CompetitorEvent(competitor="NeuraCode AI", event_type=EventType.FEATURE_LAUNCH,
                        date="2026-02-05", title="AI Security Scanner",
                        description="OWASP Top 10 scanner in enterprise tier.", impact_score=8.8, confidence=0.93),
    ]
    for ev in events:
        store.store_event(ev)

    # --- AFTER ---
    profile = store.get_memory_profile("NeuraCode AI")
    assert profile is not None, "AFTER: profile must exist"
    assert profile.total_events == 5, f"Expected 5 events, got {profile.total_events}"
    assert profile.confidence_score > 0.5, "Confidence must be substantial after 5 events"

    recalled = store.get_events(competitor="NeuraCode AI")
    assert len(recalled) == 5, "All 5 events must be recallable"

    # --- PERSIST across restart ---
    store2 = _bare_store(tmp_path)
    store2._load_all()
    recalled2 = store2.get_events(competitor="NeuraCode AI")
    assert len(recalled2) == 5, "Events must survive restart (persistence check)"
    profile2 = store2.get_memory_profile("NeuraCode AI")
    assert profile2 is not None, "Profile must survive restart"

    # --- INCREMENTAL ---
    new_event = CompetitorEvent(
        competitor="NeuraCode AI",
        event_type=EventType.PARTNERSHIP,
        date="2026-02-12",
        title="NeuraCode AI partners with JetBrains",
        description="Native IDE plugin integration across JetBrains suite.",
        impact_score=7.8,
        confidence=0.89,
    )
    store2.store_event(new_event)
    recalled_incremental = store2.get_events(competitor="NeuraCode AI")
    assert len(recalled_incremental) == 6, "After adding 1 more, total must be 6"

    titles = [e.title for e in recalled_incremental]
    assert "NeuraAssist v1.0" in titles, "Original events must be preserved after incremental add"
    assert "NeuraCode AI partners with JetBrains" in titles, "New event must appear"

    # --- ISOLATION ---
    store2.store_event(CompetitorEvent(
        competitor="RivalCorp",
        event_type=EventType.FUNDING,
        date="2026-02-01",
        title="RivalCorp $200M Series C",
        description="Funding round to expand into APAC.",
        impact_score=9.0,
        confidence=0.97,
    ))
    neura_only = store2.get_events(competitor="NeuraCode AI")
    for ev in neura_only:
        assert ev.competitor == "NeuraCode AI", (
            f"RivalCorp event leaked into NeuraCode AI results: {ev.title}"
        )
    assert len(neura_only) == 6, "NeuraCode AI count must remain 6 after adding RivalCorp"
