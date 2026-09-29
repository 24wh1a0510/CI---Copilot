"""Enforces the core governance rule: every claim in the final briefing must resolve
to a citation number that exists in the Sources list. Anything that doesn't is either
stripped or downgraded to 'Needs Verification' before publication."""
from __future__ import annotations

import re
from dataclasses import dataclass

from models.schemas import AnalyzedInsight, EvidenceStrength, Source

CITATION_PATTERN = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")
# Matches raw source-list / failed-source-list entries, e.g. "[1] Title — url" or
# "https://example.com (timeout)" — these are reference entries, not claims.
CITATION_LIST_ENTRY = re.compile(r"^(\[\d+\]\s|https?://|\(\w+\)$)")


@dataclass
class CitationCheckResult:
    total_claims: int
    cited_claims: int
    uncited_claims: list[str]
    coverage: float  # 0..1


def extract_citation_ids(text: str) -> list[int]:
    ids: list[int] = []
    for m in CITATION_PATTERN.finditer(text):
        for part in m.group(1).split(","):
            ids.append(int(part.strip()))
    return ids


def check_report_citations(report_text: str, valid_source_ids: set[int]) -> CitationCheckResult:
    """Split report into sentences/bullets and verify each factual line carries a
    citation that resolves to a real source id."""
    lines = [ln.strip("-• \t") for ln in report_text.split("\n") if ln.strip()]
    # Skip headings, table rows, and the raw Sources/Failed-Sources listings — those are
    # reference lists (already the citation targets), not factual claims requiring a
    # citation themselves.
    factual_lines = [
        ln for ln in lines
        if len(ln) > 20 and not ln.startswith("#") and not ln.startswith("|")
        and not CITATION_LIST_ENTRY.match(ln)
    ]

    cited = 0
    uncited: list[str] = []
    for line in factual_lines:
        ids = extract_citation_ids(line)
        if ids and all(i in valid_source_ids for i in ids):
            cited += 1
        elif "Needs Verification" in line:
            # explicitly flagged as unverified is acceptable governance behavior
            cited += 1
        else:
            uncited.append(line)

    total = len(factual_lines) or 1
    return CitationCheckResult(
        total_claims=total,
        cited_claims=cited,
        uncited_claims=uncited,
        coverage=cited / total,
    )


def enforce_insight_citations(insights: list[AnalyzedInsight], valid_source_ids: set[int]) -> list[AnalyzedInsight]:
    """Never hallucinate facts: drop or downgrade any insight whose source_ids aren't real."""
    safe: list[AnalyzedInsight] = []
    for insight in insights:
        real_ids = [sid for sid in insight.source_ids if sid in valid_source_ids]
        if not real_ids:
            # No valid evidence at all -> do not publish as fact.
            continue
        if len(real_ids) < len(insight.source_ids) or insight.strength == EvidenceStrength.SINGLE_SOURCE:
            insight = insight.model_copy(update={
                "source_ids": real_ids,
                "strength": EvidenceStrength.NEEDS_VERIFICATION if len(real_ids) == 1 else insight.strength,
            })
        safe.append(insight)
    return safe


def tag_confidence(insights: list[AnalyzedInsight]) -> list[AnalyzedInsight]:
    """Stretch 1: Confidence Scoring.

    Tag each insight as 'corroborated' (2+ source_ids) or 'single-source' (1 source_id).
    Returns the same list with confidence_tag set on each insight.
    """
    tagged: list[AnalyzedInsight] = []
    for insight in insights:
        if len(insight.source_ids) >= 2:
            tag = "corroborated"
        else:
            tag = "single-source"
        tagged.append(insight.model_copy(update={"confidence_tag": tag}))
    return tagged


def format_citation(source_ids: list[int]) -> str:
    return f"[{', '.join(str(i) for i in sorted(set(source_ids)))}]"
