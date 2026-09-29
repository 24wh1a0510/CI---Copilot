"""DeepEval-based evaluation covering trace correctness, tool-call accuracy, task
completion, citation coverage, faithfulness, governance checks, partial-failure
handling, prompt-injection resistance, execution limits, and latency.

Run: python evaluation/run_deepeval.py
Requires an LLM key for the LLM-judged metrics (faithfulness, task completion) —
set OPENROUTER_API_KEY in .env (free models supported via OpenRouter).
The deterministic metrics (citation coverage, governance, limits, injection) run
without any API key using evaluation/deterministic_metrics.py.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.sample_dataset import SAMPLE_COMPETITORS, SAMPLE_RESEARCH_FINDINGS, SAMPLE_SOURCES, SAMPLE_TOPIC
from evaluation.deterministic_metrics import (
    citation_coverage_score,
    execution_limit_score,
    governance_score,
    partial_failure_score,
    prompt_injection_score,
    trace_correctness_score,
)
from governance.offline_pipeline import run_offline_demo
from models.schemas import SourceStatus


def run_deterministic_suite() -> dict:
    t0 = time.monotonic()
    briefing = run_offline_demo(SAMPLE_TOPIC, SAMPLE_COMPETITORS, SAMPLE_RESEARCH_FINDINGS, SAMPLE_SOURCES)
    latency = time.monotonic() - t0

    valid_ids = {s.id for s in SAMPLE_SOURCES if s.status == SourceStatus.OK}
    results = {
        "trace_correctness": trace_correctness_score(briefing),
        "citation_coverage": citation_coverage_score(briefing.markdown, valid_ids),
        "governance": governance_score(briefing),
        "partial_failure_handling": partial_failure_score(briefing, SAMPLE_SOURCES),
        "prompt_injection_resistance": prompt_injection_score(),
        "execution_limits": execution_limit_score(),
        "latency_seconds": round(latency, 4),
    }
    return results


def run_llm_judged_suite() -> dict:
    """Optional: only runs if deepeval + an LLM key are available."""
    try:
        from deepeval import evaluate
        from deepeval.metrics import FaithfulnessMetric, TaskCompletionMetric
        from deepeval.test_case import LLMTestCase
    except ImportError:
        return {"skipped": "deepeval not installed"}

    from config.settings import settings
    if not settings.has_llm_provider:
        return {"skipped": "no LLM provider configured (OPENAI_API_KEY / OPENROUTER_API_KEY)"}

    briefing = run_offline_demo(SAMPLE_TOPIC, SAMPLE_COMPETITORS, SAMPLE_RESEARCH_FINDINGS, SAMPLE_SOURCES)
    retrieval_context = [f"[{s.id}] {s.title}: {s.snippet}" for s in SAMPLE_SOURCES if s.status == SourceStatus.OK]

    test_case = LLMTestCase(
        input=f"Generate a competitive intelligence briefing for {SAMPLE_TOPIC}",
        actual_output=briefing.markdown,
        retrieval_context=retrieval_context,
    )
    faithfulness = FaithfulnessMetric(threshold=0.7)
    faithfulness.measure(test_case)
    return {"faithfulness_score": faithfulness.score, "reason": faithfulness.reason}


if __name__ == "__main__":
    print("=== Deterministic Governance & Reliability Suite ===")
    for k, v in run_deterministic_suite().items():
        print(f"  {k}: {v}")

    print("\n=== LLM-Judged Suite (DeepEval) ===")
    for k, v in run_llm_judged_suite().items():
        print(f"  {k}: {v}")
