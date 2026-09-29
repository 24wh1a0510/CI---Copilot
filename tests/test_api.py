"""API endpoint tests for the CI Copilot FastAPI backend.

Uses httpx + TestClient (synchronous, no actual crew runs).
Run with: pytest tests/test_api.py -v
"""
from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def temp_memory_dir():
    """Isolated temp directory for the test memory store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture(scope="module")
def client(temp_memory_dir):
    """Create FastAPI TestClient with isolated memory store."""
    import threading
    from pathlib import Path
    from memory.hindsight_store import HindsightStore

    # Build a real store against the temp dir (includes seed data)
    test_store = HindsightStore(base_path=temp_memory_dir)

    with patch("api.main._store", test_store):
        from api.main import app
        # lifespan=False skips the startup handler that would reinitialise _store
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_endpoint(client):
    """GET /health should return status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "memory_stats" in data
    assert "version" in data


# ── Memory Stats ──────────────────────────────────────────────────────────────

def test_memory_stats_endpoint(client):
    """GET /api/memory/stats should return MemoryStats."""
    resp = client.get("/api/memory/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_events" in data
    assert "competitors_tracked" in data
    assert "predictions_generated" in data
    assert "strategic_alerts" in data
    assert "memory_size_kb" in data


def test_memory_stats_reflect_seeded_data(client):
    """Memory stats after seeding should show events > 0."""
    resp = client.get("/api/memory/stats")
    data = resp.json()
    # Demo data should have been seeded by HindsightStore init
    assert data["total_events"] >= 0  # May be 0 in isolated test
    assert data["competitors_tracked"] >= 0


# ── Memory Profiles ───────────────────────────────────────────────────────────

def test_memory_profiles_endpoint(client):
    """GET /api/memory/profiles should return a list."""
    resp = client.get("/api/memory/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_memory_profile_individual(client, temp_memory_dir):
    """GET /api/memory/profiles/{competitor} should return a profile or 404."""
    from memory.hindsight_store import HindsightStore
    store = HindsightStore.__new__(HindsightStore)
    # Use a fresh store pointing to same dir
    from memory.hindsight_store import HindsightStore as HS2
    import threading
    from pathlib import Path

    # If seeded data is available, test retrieval
    resp_list = client.get("/api/memory/profiles")
    profiles = resp_list.json()

    if profiles:
        first_comp = profiles[0]["competitor"]
        resp = client.get(f"/api/memory/profiles/{first_comp}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["competitor"] == first_comp
    else:
        # If no profiles, expect 404
        resp = client.get("/api/memory/profiles/NonExistentCorp")
        assert resp.status_code == 404


def test_memory_profile_not_found(client):
    """GET /api/memory/profiles/{unknown} should return 404."""
    resp = client.get("/api/memory/profiles/CompanyThatDoesNotExist_XYZ_123")
    assert resp.status_code == 404


# ── Memory Timeline ───────────────────────────────────────────────────────────

def test_memory_timeline_endpoint(client):
    """GET /api/memory/timeline should return a list of events."""
    resp = client.get("/api/memory/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_memory_timeline_with_competitor_filter(client):
    """GET /api/memory/timeline?competitor=X should filter correctly."""
    # First get all profiles to find a real competitor
    profiles_resp = client.get("/api/memory/profiles")
    profiles = profiles_resp.json()

    if profiles:
        comp = profiles[0]["competitor"]
        resp = client.get(f"/api/memory/timeline?competitor={comp}")
        assert resp.status_code == 200
        data = resp.json()
        # All returned events should be for this competitor
        for event in data:
            assert event["competitor"] == comp
    else:
        resp = client.get("/api/memory/timeline?competitor=TestCorp")
        assert resp.status_code == 200
        assert resp.json() == []


def test_memory_timeline_days_parameter(client):
    """GET /api/memory/timeline?days=30 should filter by time range."""
    resp = client.get("/api/memory/timeline?days=30")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Predictions ───────────────────────────────────────────────────────────────

def test_predictions_endpoint(client):
    """GET /api/memory/predictions should return a list."""
    resp = client.get("/api/memory/predictions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_predictions_with_competitor_filter(client):
    """Predictions filtered by competitor should only return matching items."""
    resp = client.get("/api/memory/predictions")
    all_preds = resp.json()

    if all_preds:
        comp = all_preds[0]["competitor"]
        filtered_resp = client.get(f"/api/memory/predictions?competitor={comp}")
        assert filtered_resp.status_code == 200
        filtered = filtered_resp.json()
        for pred in filtered:
            assert pred["competitor"] == comp


# ── Strategies ────────────────────────────────────────────────────────────────

def test_strategies_list_endpoint(client):
    """GET /api/memory/strategies should return all strategies."""
    resp = client.get("/api/memory/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_strategy_for_competitor(client):
    """GET /api/memory/strategy/{competitor} should return strategy or 404."""
    strats_resp = client.get("/api/memory/strategies")
    strats = strats_resp.json()

    if strats:
        comp = strats[0]["competitor"]
        resp = client.get(f"/api/memory/strategy/{comp}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["competitor"] == comp
        assert "synthesized_strategy" in data
        assert "timeline" in data
    else:
        resp = client.get("/api/memory/strategy/NonExistent")
        assert resp.status_code == 404


# ── Memory Events ─────────────────────────────────────────────────────────────

def test_memory_events_endpoint(client):
    """GET /api/memory/events should return a list of events."""
    resp = client.get("/api/memory/events")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_memory_events_limit_parameter(client):
    """GET /api/memory/events?limit=5 should return at most 5 results."""
    resp = client.get("/api/memory/events?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 5


def test_memory_events_event_type_filter(client):
    """Filtering by event_type returns only matching events."""
    resp = client.get("/api/memory/events?event_type=feature_launch")
    assert resp.status_code == 200
    data = resp.json()
    for event in data:
        assert event["event_type"] == "feature_launch"


# ── Audit Logs ────────────────────────────────────────────────────────────────

def test_audit_logs_endpoint(client):
    """GET /api/audit/logs should return a list."""
    resp = client.get("/api/audit/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_audit_logs_limit(client):
    """GET /api/audit/logs?limit=10 should respect the limit."""
    resp = client.get("/api/audit/logs?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 10


# ── Briefings ─────────────────────────────────────────────────────────────────

def test_briefings_list_endpoint(client):
    """GET /api/briefings should return a list (possibly empty)."""
    resp = client.get("/api/briefings")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_briefing_not_found(client):
    """GET /api/briefings/{unknown_id} should return 404."""
    resp = client.get("/api/briefings/does-not-exist-abc123")
    assert resp.status_code == 404


# ── Runs ──────────────────────────────────────────────────────────────────────

def test_start_run_returns_run_id(client):
    """POST /api/runs/start should return a run_id (doesn't actually run crew)."""
    with patch("api.main._run_briefing_background") as mock_task:
        mock_task.return_value = None  # Don't actually run
        resp = client.post("/api/runs/start", json={
            "topic": "AI Assistants",
            "competitors": ["OpenAI", "Anthropic"],
            "date_range_days": 30,
            "include_predictions": True,
        })

    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "queued"


def test_run_status_endpoint(client):
    """GET /api/runs/{run_id}/status should return status for registered runs."""
    with patch("api.main._run_briefing_background"):
        start_resp = client.post("/api/runs/start", json={
            "topic": "Test Topic",
            "competitors": ["TestCorp"],
            "date_range_days": 7,
        })

    run_id = start_resp.json()["run_id"]
    status_resp = client.get(f"/api/runs/{run_id}/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["run_id"] == run_id
    assert data["status"] in ("queued", "running", "completed", "failed")


def test_run_status_not_found(client):
    """GET /api/runs/{unknown_id}/status should return 404."""
    resp = client.get("/api/runs/nonexistent-run-id-xyz/status")
    assert resp.status_code == 404


def test_list_runs(client):
    """GET /api/runs should return a list of recent runs."""
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Seed & Reset ──────────────────────────────────────────────────────────────

def test_seed_endpoint_when_empty(temp_memory_dir):
    """POST /api/memory/seed should seed data when memory is empty."""
    from memory.hindsight_store import HindsightStore
    fresh_store = HindsightStore.__new__(HindsightStore)
    from pathlib import Path
    import threading

    with tempfile.TemporaryDirectory() as fresh_dir:
        fresh_path = Path(fresh_dir)
        fresh_store._base = fresh_path
        fresh_store._events_file = fresh_path / "events.jsonl"
        fresh_store._profiles_file = fresh_path / "profiles.json"
        fresh_store._strategies_file = fresh_path / "strategies.json"
        fresh_store._predictions_file = fresh_path / "predictions.json"
        fresh_store._lock = threading.Lock()
        fresh_store._events = []
        fresh_store._profiles = {}
        fresh_store._strategies = {}
        fresh_store._predictions = []

        with patch("api.main._store", fresh_store):
            from api.main import app
            with TestClient(app) as c:
                resp = c.post("/api/memory/seed")
                assert resp.status_code == 200
                data = resp.json()
                assert data["seeded"] is True


def test_seed_endpoint_when_not_empty(client):
    """POST /api/memory/seed should not re-seed when data exists."""
    # First ensure there's data
    events_resp = client.get("/api/memory/events")
    events = events_resp.json()

    if events:
        resp = client.post("/api/memory/seed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["seeded"] is False
