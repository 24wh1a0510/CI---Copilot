"""A deterministic, rule-based stand-in for the Analyst + Writer agents, used by
pytest / DeepEval / the UI demo mode so the full governance behavior (dedup, weak-
evidence flagging, citation enforcement, partial-failure handling) can be verified
without calling an LLM or the network. The real CrewAI agents follow the same rules
via their task prompts in agents/tasks.py."""
from __future__ import annotations

from datetime import datetime

from governance.citation_guard import (
    check_report_citations,
    enforce_insight_citations,
    format_citation,
    tag_confidence,
)
from models.schemas import (
    AnalyzedInsight,
    Briefing,
    EvidenceStrength,
    RunMetadata,
    Source,
    SourceStatus,
)

# Keywords that mark a claim as unverifiable speculation regardless of source count.
_SPECULATION_MARKERS = ("rumor", "anonymous", "unconfirmed", "speculat", "claims", "allegedly")

# Domain categories used to judge single-source credibility. In a real deployment this
# would be a maintained allowlist (company investor-relations pages, major wire
# services, filed regulatory documents, etc.) rather than a hardcoded tuple.
_HIGH_TRUST_DOMAIN_MARKERS = (
    ".gov", "reuters.com", "bloomberg.com", "sec.gov", "techcrunch.com",
    "wsj.com", "ft.com", "prnewswire.com", "businesswire.com",
)


def _is_high_trust(source: Source, competitor: str) -> bool:
    domain = source.domain.lower()
    # A competitor's own official domain (e.g. snowflake.com for "Snowflake",
    # cloud.google.com for "BigQuery"/"Google") is treated as a primary source.
    comp_token = competitor.lower().replace(" ", "")
    if comp_token in domain or (competitor.lower() == "bigquery" and "google.com" in domain):
        return True
    return any(marker in domain for marker in _HIGH_TRUST_DOMAIN_MARKERS)


def analyze(findings: list[dict], sources: list[Source]) -> list[AnalyzedInsight]:
    source_by_id = {s.id: s for s in sources}
    insights: list[AnalyzedInsight] = []
    seen_statements: set[str] = set()

    for f in findings:
        stmt_key = f["statement"].lower()[:60]
        if stmt_key in seen_statements:
            continue  # dedupe
        seen_statements.add(stmt_key)

        valid_ids = [sid for sid in f["source_ids"] if sid in source_by_id and
                     source_by_id[sid].status == SourceStatus.OK]

        if not valid_ids:
            continue  # every backing source failed/timed out -> drop, don't hallucinate

        is_speculative = any(m in f["statement"].lower() for m in _SPECULATION_MARKERS)
        backing_sources = [source_by_id[sid] for sid in valid_ids]
        has_trusted_source = any(_is_high_trust(s, f["competitor"]) for s in backing_sources)

        if is_speculative:
            # Speculative language always gets flagged, no matter how "trusted" the
            # domain hosting it is — wording, not domain, drives this signal.
            strength = EvidenceStrength.NEEDS_VERIFICATION
        elif len(valid_ids) >= 2 or has_trusted_source:
            # Corroborated by 2+ sources, OR a single but credible/primary source
            # (official press release, major wire service, regulatory filing).
            strength = EvidenceStrength.CONFIRMED
        else:
            # Single source, and it's not from a recognized trusted domain.
            strength = EvidenceStrength.SINGLE_SOURCE

        insights.append(AnalyzedInsight(
            competitor=f["competitor"],
            category=f["category"],
            insight=f["statement"],
            strength=strength,
            source_ids=valid_ids,
            is_risk=is_speculative or f["category"] == "market_trend" and "competition" in f["statement"].lower(),
            is_opportunity=f["category"] == "product",
        ))

    # Stretch 1: tag each insight with corroborated / single-source confidence
    insights = tag_confidence(insights)

    return insights


def write_report(topic: str, competitors: list[str], insights: list[AnalyzedInsight], sources: list[Source]) -> str:
    valid_ids = {s.id for s in sources if s.status == SourceStatus.OK}
    insights = enforce_insight_citations(insights, valid_ids)

    def render(ins: AnalyzedInsight) -> str:
        if ins.strength == EvidenceStrength.NEEDS_VERIFICATION:
            tag = " (Needs Verification)"
        elif ins.strength == EvidenceStrength.SINGLE_SOURCE:
            tag = " (Single Source)"
        else:
            tag = ""
        return f"- **{ins.competitor}**: {ins.insight}{tag} {format_citation(ins.source_ids)}"

    pricing = [i for i in insights if i.category in ("pricing", "product")]
    market = [i for i in insights if i.category in ("market_trend", "funding", "partnership", "acquisition")]
    risks = [i for i in insights if i.is_risk]
    opportunities = [i for i in insights if i.is_opportunity]

    exec_summary_bits = []
    for i in insights[:3]:
        tag = " (Needs Verification)" if i.strength == EvidenceStrength.NEEDS_VERIFICATION else ""
        exec_summary_bits.append(f"- {i.competitor} — {i.insight}{tag} {format_citation(i.source_ids)}")
    exec_summary = "\n".join(exec_summary_bits) or "No verified findings this week."

    sources_section = "\n".join(
        f"[{s.id}] {s.title or s.url} — {s.url}" for s in sources if s.status == SourceStatus.OK
    )
    failed_section = "\n".join(
        f"- {s.url} ({s.status.value})" for s in sources if s.status != SourceStatus.OK
    )

    report = f"""# Weekly Competitive Intelligence Briefing — {topic}

## Executive Summary
{exec_summary}

## Competitor Pricing & Product Moves
{chr(10).join(render(i) for i in pricing) or "No pricing/product findings this week."}

## Market Signals
{chr(10).join(render(i) for i in market) or "No market-signal findings this week."}

## Strategic Recommendations
- Monitor pricing convergence between Snowflake and Databricks; consider a competitive response if margin-sensitive customers churn {format_citation([4]) if any(i.source_ids == [4] for i in insights) else ""}.
- Evaluate Lakebase-equivalent transactional capabilities given Databricks' move into that space {format_citation([2]) if any(2 in i.source_ids for i in insights) else ""}.

## Sources & Citations
{sources_section}

### Failed / Skipped Sources
{failed_section or "None."}
"""
    return report


def run_offline_demo(topic, competitors, findings, sources) -> Briefing:
    started = datetime.utcnow()
    insights = analyze(findings, sources)
    report = write_report(topic, competitors, insights, sources)
    valid_ids = {s.id for s in sources if s.status == SourceStatus.OK}
    check = check_report_citations(report, valid_ids)

    meta = RunMetadata(
        run_id="demo-offline",
        started_at=started,
        finished_at=datetime.utcnow(),
        execution_time_seconds=0.01,
        search_count=len({f["category"] for f in findings}),
        sources_attempted=len(sources),
        sources_failed=sum(1 for s in sources if s.status != SourceStatus.OK),
        execution_steps=len(findings),
        max_sources=15,
        max_steps=20,
        limit_reached=False,
        status="completed" if check.coverage == 1.0 else "completed_with_partial_failures",
    )
    return Briefing(
        topic=topic, competitors=competitors, executive_summary="",
        pricing_and_product_moves="", market_signals="", strategic_recommendations="",
        sources=sources, insights=insights, metadata=meta, markdown=report,
    )
