"""Top-level orchestration for the Memory-First CI Copilot.

Runs the 7-agent pipeline, stores events in Hindsight, parses strategy and
prediction outputs, and returns an enriched Briefing with memory context.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from crewai import Crew, Process

from agents.definitions import build_agents
from agents.tasks import build_tasks
from config.settings import settings
from governance.citation_guard import check_report_citations, enforce_insight_citations
from logging_.audit_logger import AuditLogger
from memory.hindsight_store import HindsightStore
from models.memory_schemas import (
    CompetitorEvent,
    EventType,
    Prediction,
    PredictionStatus,
    RunStatus,
    StrategyEvolution,
    StrategyPhase,
    TrendDirection,
)
from models.schemas import Briefing, RunMetadata, Source, SourceStatus
from tools.search_tool import SearchBudget

RESULTS_DIR = Path("data/briefing_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def run_briefing(
    topic: str,
    competitors: list[str] | None = None,
    max_sources: int | None = None,
    max_steps: int | None = None,
    on_progress: Any | None = None,  # Optional callback(agent_name, message)
) -> Briefing:
    """Execute the full Memory-First CI Copilot pipeline."""
    competitors = competitors or []
    auto_discovered = len(competitors) == 0
    run_id = uuid.uuid4().hex[:12]
    audit = AuditLogger(run_id)
    budget = SearchBudget(max_sources=max_sources, max_steps=max_steps)
    store = HindsightStore(base_path=settings.hindsight_memory_path)

    started_at = datetime.utcnow()
    t0 = time.monotonic()

    def _progress(agent: str, msg: str) -> None:
        audit.decision(agent, msg)
        if on_progress:
            on_progress(agent, msg)

    if auto_discovered:
        _progress("Supervisor", f"Run {run_id}: topic='{topic}' — auto-discovering competitors")
    else:
        _progress("Supervisor", f"Run {run_id}: topic='{topic}' competitors={competitors}")

    _progress("Memory Agent", f"Hindsight store ready. Current memory: {store.get_stats().total_events} events")

    status = "completed"
    report_markdown = ""
    sources: list[Source] = []

    try:
        agents = build_agents(budget, audit, store)
        tasks = build_tasks(agents, topic, competitors)

        search_tool = agents["researcher"].tools[0]

        crew_agents = [
            agents["researcher"],
            agents["memory"],
            agents["analyst"],
            agents["strategy"],
            agents["prediction"],
            agents["writer"],
        ]
        if auto_discovered:
            crew_agents.insert(0, agents["discovery"])

        crew = Crew(
            agents=crew_agents,
            tasks=tasks,
            process=Process.sequential,
            manager_agent=None,
            verbose=True,
        )

        _progress("Supervisor", "Crew assembled — beginning sequential pipeline execution")
        result = crew.kickoff()
        report_markdown = str(result)

        # Auto-discovered competitor resolution
        if auto_discovered:
            discovery_output = str(tasks[0].output) if tasks and tasks[0].output else ""
            discovered = _extract_competitors_from_discovery(discovery_output)
            if discovered:
                competitors = discovered
                _progress("Supervisor", f"Discovery Agent identified: {competitors}")
            else:
                audit.failure("Supervisor", "Discovery Agent returned no parsable competitor names.")

        sources = list(getattr(search_tool, "collected_sources", []))

        if budget.limit_hit:
            status = "stopped_at_limit"
            audit.limit_reached("Supervisor", "search/step budget")

        # ── Parse and persist memory artifacts ───────────────────────────────
        _persist_memory_artifacts(tasks, store, audit, competitors, run_id)

    except Exception as e:
        status = "failed"
        audit.failure("Supervisor", f"Crew execution failed: {e}")
        report_markdown = (
            f"# Briefing Generation Failed\n\n"
            f"The run encountered an unrecoverable error: {e}\n\n"
            "Partial audit trail is available. Hindsight memory data from previous runs is preserved."
        )

    from governance.citation_guard import extract_citation_ids
    referenced_ids = set(extract_citation_ids(report_markdown))
    citation_check = check_report_citations(report_markdown, referenced_ids)

    if citation_check.coverage < 1.0:
        audit.decision(
            "Supervisor",
            f"Citation coverage {citation_check.coverage:.0%}; "
            f"{len(citation_check.uncited_claims)} uncited claim(s) flagged.",
        )
        if status == "completed":
            status = "completed_with_partial_failures"

    finished_at = datetime.utcnow()
    metadata = RunMetadata(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        execution_time_seconds=round(time.monotonic() - t0, 2),
        search_count=budget.steps_taken,
        sources_attempted=budget.sources_collected,
        sources_failed=sum(1 for e in audit.events if e["event_type"] == "failure"),
        execution_steps=len(audit.events),
        max_sources=budget.max_sources,
        max_steps=budget.max_steps,
        limit_reached=budget.limit_hit,
        status=status,
    )

    _progress("Supervisor", f"Run finished: status={status} | memory_events={store.get_stats().total_events}")

    full_markdown = _append_metadata_section(report_markdown, metadata, citation_check, store)

    briefing = Briefing(
        topic=topic,
        competitors=competitors,
        executive_summary=_extract_section(report_markdown, "Executive Summary"),
        pricing_and_product_moves=_extract_section(report_markdown, "Competitor Moves"),
        market_signals=_extract_section(report_markdown, "Market Signals"),
        strategic_recommendations=_extract_section(report_markdown, "Strategic Recommendations"),
        sources=sources,
        insights=[],
        metadata=metadata,
        markdown=full_markdown,
    )

    # Persist briefing result to disk for API retrieval
    _save_briefing_result(briefing, run_id)

    # Persist to trend memory (legacy compatibility)
    if status in ("completed", "completed_with_partial_failures", "stopped_at_limit"):
        try:
            from tools.trend_memory import save_briefing as _save_trending
            _save_trending(topic, competitors, briefing)
            audit.decision("Supervisor", "Trend memory: briefing saved to history.")
        except Exception as _tm_err:
            audit.decision("Supervisor", f"Trend memory save skipped: {_tm_err}")

    return briefing


def _persist_memory_artifacts(
    tasks: list,
    store: HindsightStore,
    audit: AuditLogger,
    competitors: list[str],
    run_id: str,
) -> None:
    """Parse agent task outputs and persist strategies + predictions to Hindsight."""
    # Find strategy task output
    for task in tasks:
        if task.agent and hasattr(task.agent, "role"):
            role = task.agent.role or ""
            output_text = str(task.output) if task.output else ""

            if "Strategy Evolution" in role and output_text:
                strategies = _parse_strategy_output(output_text, competitors)
                for strat in strategies:
                    store.save_strategy_evolution(strat)
                    audit.decision("Strategy Evolution Agent", f"Saved strategy for {strat.competitor}")

            if "Prediction" in role and output_text:
                preds = _parse_prediction_output(output_text, competitors)
                for pred in preds:
                    store.save_prediction(pred)
                    audit.decision("Prediction Agent", f"Saved prediction for {pred.competitor}: {pred.prediction_text[:60]}...")


def _parse_strategy_output(text: str, competitors: list[str]) -> list[StrategyEvolution]:
    """Extract StrategyEvolution objects from the Strategy Evolution Agent output."""
    strategies = []
    for competitor in competitors:
        # Find section for this competitor
        pattern = rf"## Strategy Evolution:?\s*{re.escape(competitor)}(.*?)(?=## Strategy Evolution:|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            continue

        section = match.group(1)

        # Extract overall strategy
        synth_match = re.search(r"\*\*Overall Strategy\*\*:?\s*(.+)", section)
        synthesized = synth_match.group(1).strip() if synth_match else "Unknown strategy"

        # Extract trend direction
        trend_match = re.search(r"\*\*Trend Direction\*\*:?\s*(\w+)", section, re.IGNORECASE)
        trend_str = trend_match.group(1).lower() if trend_match else "stable"
        trend = TrendDirection.STABLE
        for td in TrendDirection:
            if td.value == trend_str:
                trend = td
                break

        # Extract confidence
        conf_match = re.search(r"\*\*Confidence\*\*:?\s*(\d+)%", section)
        confidence = float(conf_match.group(1)) / 100 if conf_match else 0.7

        # Extract evidence summary
        ev_match = re.search(r"\*\*Evidence Summary\*\*:?\s*(.+?)(?=\n\*\*|\n#|$)", section, re.DOTALL)
        evidence = ev_match.group(1).strip() if ev_match else ""

        # Extract timeline phases
        phases = []
        phase_pattern = r"- \[(.+?)\]:\s*(.+?)\s*\(confidence:\s*(\d+)%\)"
        for pm in re.finditer(phase_pattern, section, re.IGNORECASE):
            phases.append(StrategyPhase(
                period=pm.group(1).strip(),
                dominant_strategy=pm.group(2).strip(),
                confidence=float(pm.group(3)) / 100,
            ))

        if synthesized:
            strategies.append(StrategyEvolution(
                competitor=competitor,
                timeline=phases,
                synthesized_strategy=synthesized,
                evidence_summary=evidence,
                confidence_score=confidence,
                trend_direction=trend,
            ))

    return strategies


def _parse_prediction_output(text: str, competitors: list[str]) -> list[Prediction]:
    """Extract Prediction objects from the Prediction Agent output."""
    predictions = []
    for competitor in competitors:
        pattern = rf"## Predictions:?\s*{re.escape(competitor)}(.*?)(?=## Predictions:|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            continue

        section = match.group(1)

        # Find all prediction blocks
        pred_sections = re.split(r"### Prediction \d+", section)
        for ps in pred_sections[1:]:  # skip first empty split
            pred_match = re.search(r"\*\*Prediction\*\*:?\s*(.+?)(?=\n\*\*|\Z)", ps, re.DOTALL)
            conf_match = re.search(r"\*\*Confidence\*\*:?\s*(\d+)%", ps)
            tf_match = re.search(r"\*\*Timeframe\*\*:?\s*(.+?)(?=\n|\Z)", ps)
            cat_match = re.search(r"\*\*Category\*\*:?\s*(\w+)", ps)
            pattern_match = re.search(r"\*\*Historical Pattern\*\*:?\s*(.+?)(?=\n\*\*|\Z)", ps, re.DOTALL)

            # Evidence bullets
            evidence_lines = re.findall(r"- (.+?)(?=\n|$)", ps)
            # Filter out lines that look like headings or meta
            evidence = [
                ln.strip() for ln in evidence_lines
                if ln.strip() and not ln.startswith("**") and len(ln) > 20
            ]

            if pred_match:
                predictions.append(Prediction(
                    competitor=competitor,
                    prediction_text=pred_match.group(1).strip(),
                    confidence=float(conf_match.group(1)) / 100 if conf_match else 0.6,
                    predicted_timeframe=tf_match.group(1).strip() if tf_match else "Next 30-60 days",
                    category=cat_match.group(1).strip() if cat_match else "product",
                    supporting_evidence=evidence[:5],
                    historical_pattern=pattern_match.group(1).strip() if pattern_match else "",
                    status=PredictionStatus.PENDING,
                ))

    return predictions


def _save_briefing_result(briefing: Briefing, run_id: str) -> None:
    """Persist a briefing result to disk for API retrieval."""
    try:
        path = RESULTS_DIR / f"{run_id}.json"
        data = briefing.model_dump(mode="json")
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _extract_competitors_from_discovery(discovery_markdown: str) -> list[str]:
    lines = discovery_markdown.split("\n")
    capture = False
    names: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Competitors"):
            capture = True
            continue
        if capture and stripped.startswith("##"):
            break
        if not capture or not stripped:
            continue
        m = re.match(r"^\d+[.)]\s*(.+)$", stripped)
        if not m:
            continue
        name = m.group(1)
        name = re.sub(r"\[[\d,\s]+\]\s*$", "", name).strip(" -–:")
        if name:
            names.append(name)
    return names


def _extract_section(markdown: str, heading: str) -> str:
    lines = markdown.split("\n")
    out, capture = [], False
    for line in lines:
        if line.strip().startswith("##") and heading in line:
            capture = True
            continue
        if capture and line.strip().startswith("##"):
            break
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def _append_metadata_section(
    markdown: str,
    meta: RunMetadata,
    citation_check: Any,
    store: HindsightStore,
) -> str:
    stats = store.get_stats()
    metadata_block = f"""

## Run Metadata

| Field | Value |
|---|---|
| Run ID | `{meta.run_id}` |
| Started | {meta.started_at.isoformat()} |
| Finished | {meta.finished_at.isoformat() if meta.finished_at else '-'} |
| Execution time | {meta.execution_time_seconds}s |
| Search count | {meta.search_count} |
| Sources attempted | {meta.sources_attempted} |
| Sources failed | {meta.sources_failed} |
| Execution steps (audit events) | {meta.execution_steps} |
| Limits | {meta.max_sources} sources / {meta.max_steps} steps |
| Limit reached | {meta.limit_reached} |
| Citation coverage | {citation_check.coverage:.0%} |
| **Hindsight Memory Events** | **{stats.total_events}** |
| **Competitors Tracked in Memory** | **{stats.competitors_tracked}** |
| **Predictions in Memory** | **{stats.predictions_generated}** |
| Status | **{meta.status}** |
"""
    return markdown + metadata_block
