# Testing Guide — CI Briefing Crew

How to run every test suite and verify the Hindsight Memory layer works end-to-end.

---

## Prerequisites

```bash
cd D:\GenAI\ci-briefing-crew

# activate your venv (adjust path if needed)
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

pip install -r requirements.txt
```

No API keys are required for the memory tests or the standalone demo.

---

## Test Files

| File | What it tests | Needs keys? |
|---|---|---|
| `tests/test_memory.py` | HindsightStore unit tests (isolated tmp store) | No |
| `tests/test_hindsight_memory.py` | Integration tests — real store, no mocks | No |
| `tests/test_api.py` | FastAPI endpoints via TestClient | No |
| `tests/test_scenarios.py` | End-to-end scenario tests | No |
| `tests/test_login_playwright.py` | Playwright UI login flow | No (needs browser) |
| `scripts/demo_memory.py` | Standalone BEFORE/AFTER CLI demo | No |

---

## Quick Start — Run Everything

```bash
# from project root
pytest tests/ -v
```

---

## Run Individual Suites

### Memory unit tests
```bash
pytest tests/test_memory.py -v
```

### Hindsight Memory integration tests
```bash
pytest tests/test_hindsight_memory.py -v
```

### API endpoint tests
```bash
pytest tests/test_api.py -v
```

### All tests except Playwright (no browser install needed)
```bash
pytest tests/ -v --ignore=tests/test_login_playwright.py
```

### Playwright UI tests (requires browser install)
```bash
playwright install chromium
pytest tests/test_login_playwright.py -v
```

### Run a single test by name
```bash
pytest tests/test_memory.py::test_store_and_retrieve_event -v
pytest tests/test_hindsight_memory.py::test_full_retain_recall_cycle -v
```

### Run tests matching a keyword
```bash
pytest tests/ -v -k "memory"
pytest tests/ -v -k "prediction"
pytest tests/ -v -k "profile"
```

---

## Standalone BEFORE / AFTER Demo

This script requires **no backend, no LLM, no network** — it runs purely against
the in-memory HindsightStore and prints a full BEFORE/AFTER walkthrough.

```bash
python scripts/demo_memory.py
```

### What it demonstrates

```
BEFORE MEMORY
  Query "NeuraCode AI" → No profile, no events
  Response: "No data available for NeuraCode AI. Cannot determine strategy."

STORING 5 EVENTS IN HINDSIGHT MEMORY
  [2026-01-08] feature_launch : NeuraAssist v1.0 — AI Code Review Tool launched
  [2026-01-15] hiring         : 15 ML engineers hired from Google DeepMind and Meta AI
  [2026-01-22] pricing_change : Enterprise tier introduced at $45/seat/month
  [2026-01-29] acquisition    : CodeLens Analytics acquired for $28M
  [2026-02-05] feature_launch : AI Security Code Scanner — OWASP Top 10 in real time

AFTER MEMORY
  Query "NeuraCode AI" → Profile exists, 5 events, confidence 87%
  Response:
    Based on 5 stored memory events (confidence: 87%):
    • [2026-01-08] Launched NeuraAssist v1.0 — AI code review tool
    • [2026-01-15] Hired 15 ML engineers from Google/Meta
    • [2026-01-22] Introduced enterprise pricing at $45/seat
    • [2026-01-29] Acquired CodeLens Analytics for $28M
    • [2026-02-05] Shipped AI Security Scanner
    Pattern: Rapid Enterprise Expansion via Product + Talent + M&A.
    Risk Level: HIGH | Innovation: 8.5/10

INCREMENTAL LEARNING
  Add [2026-02-12] partnership: JetBrains native IDE integration
  → total_events = 6, old events preserved ✓

PERSISTENCE (SIMULATED RESTART)
  Reinitialise store from same path → all 5 events still present ✓

MEMORY ISOLATION
  Store 2 events for RivalCorp
  → NeuraCode AI query returns 6 events, zero RivalCorp leakage ✓
  → RivalCorp query returns 2 events, zero NeuraCode AI leakage ✓

STATS
  total_events = 8  |  competitors_tracked = 2

SEARCH
  search_memory("security") → 1 result ✓
  search_memory("zzz_no_match") → [] ✓

CLEAR
  clear_all() → total_events = 0, competitors_tracked = 0 ✓
```

Expected final output:
```
ALL 22/22 TESTS PASSED

BEFORE vs AFTER summary:
  BEFORE: No profile, no events — generic fallback response
  AFTER:  5 events stored → profile with confidence, risk level,
          innovation score, and full event history accessible
  INCREMENTAL: Added 1 event → total became 6, old events preserved
  ISOLATION: RivalCorp data never appeared in NeuraCode AI recall
  PERSISTENCE: Data survived simulated process restart
```

---

## pytest Options Reference

| Flag | Purpose |
|---|---|
| `-v` | Verbose — show each test name and PASS/FAIL |
| `-s` | Show print/stdout output from tests |
| `-x` | Stop on first failure |
| `--tb=short` | Compact traceback on failure |
| `--tb=long` | Full traceback (default) |
| `-k "keyword"` | Run only tests whose name matches keyword |
| `--co` | Collect only — list tests without running |
| `-q` | Quiet mode — summary only |

### Useful combinations

```bash
# Stop at first failure, show stdout
pytest tests/test_memory.py -v -x -s

# Dry-run: list all tests without executing
pytest tests/ --co -q

# Only memory-related tests, compact tracebacks
pytest tests/ -v -k "memory" --tb=short

# Full suite, quiet summary
pytest tests/ -q
```

---

## Coverage Report (optional)

```bash
pip install pytest-cov
pytest tests/ --cov=memory --cov=models --cov=api --cov-report=term-missing
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'memory'`**
Run pytest from the project root, not from inside `tests/`:
```bash
cd D:\GenAI\ci-briefing-crew
pytest tests/ -v
```

**`ImportError` on `api.main`**
The API tests patch `api.main._store`. If FastAPI app startup fails, check that
`api/main.py` imports are satisfied (`pip install -r requirements.txt`).

**Playwright tests fail with "browser not found"**
```bash
playwright install chromium
```

**Memory tests leave data behind**
All memory tests use `tmp_path` (pytest built-in) or `tempfile.TemporaryDirectory`,
so real data in `data/memory/` is never touched.
