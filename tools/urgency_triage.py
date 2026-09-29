"""Urgency Triage — post-Writer pass that flags high-impact items separately.

Completely independent of the SearchBudget and crew run cap.  Call
`triage_briefing(markdown)` on the final report text and it returns a list of
TriageItem objects that the UI can render as a top-of-page alert panel.

High-impact criteria (all require a citation [n] to avoid flagging boilerplate):
  HIGH  — pricing keyword AND quantified change (%, $, "cut", "raised")
  HIGH  — leadership / personnel change keyword
  HIGH  — explicit urgency words: "immediately", "urgent", "critical", "breaking"
  HIGH  — M&A / IPO signal: acquisition, merger, buyout, IPO
  MEDIUM — funding round (Series A/B/C, raised $X)
  MEDIUM — product launch keyword with a citation

Lines without a citation [n] are NEVER flagged — they are either boilerplate
summaries or uncited claims that governance already handles separately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Must appear WITH a citation to fire — avoids flagging boilerplate summaries
_CITATION_RE = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")

# Pricing: must include a numeric change signal (%, $, cut, raised, reduced, increase)
_PRICING_KW = re.compile(
    r"\b(pric(e|ing|ed)|discount|subscription|tier|billing)\w*\b",
    re.IGNORECASE,
)
_QUANTIFIED_CHANGE = re.compile(
    r"(\d+\s*%"
    r"|(?:raised?|cut|reduced?|increased?|dropped?|slashed?)\s+(?:by\s+)?\$?\d"
    r"|\$\s*\d[\d,.]*\s*(?:million|billion|M|B)\b)",
    re.IGNORECASE,
)

# Leadership / personnel — requires an action word, not just a title mention
# "CEO resigned" fires. "confirmed by CEO" does not.
_LEADERSHIP_KW = re.compile(
    r"\b(ceo|cto|cfo|coo|founder|co-founder)\b.{0,40}\b(resign\w*|step(?:ping)?\s+down"
    r"|fired|laid\s+off|depart\w*|quit\w*|leav\w*|replac\w*|successor)"
    r"|"
    r"\b(resign\w*|step(?:ping)?\s+down|fired|laid\s+off|depart\w*)\b.{0,40}"
    r"\b(ceo|cto|cfo|coo|founder)\b"
    r"|"
    r"\b(appoint\w*|hire[ds]?|named\s+(?:new\s+)?(?:ceo|cto|cfo|coo))\b",
    re.IGNORECASE,
)

# Explicit urgency — tightly scoped to avoid false positives on "ensuring", "encapsulates"
_URGENCY_KW = re.compile(
    r"\b(immediately|urgent(?:ly)?|critical(?:ly)?|breaking(?:\s+news)?"
    r"|emergency|imminent(?:ly)?|escalat\w*|red\s+alert)\b",
    re.IGNORECASE,
)

# M&A / IPO — high severity
_MA_KW = re.compile(
    r"\b(acqui(?:red?|ring|sition)|merger|buyout|takeover|ipo|going\s+public)\b",
    re.IGNORECASE,
)

# Funding round — medium severity
_FUNDING_KW = re.compile(
    r"(series\s+[a-f]"
    r"|seed\s+round"
    r"|funding\s+round"
    r"|raised?\s+(?:\$\s*)?\d[\d,.]*\s*(?:million|billion|M|B)?"
    r"|venture\s+capital"
    r"|vc\s+funding)",
    re.IGNORECASE,
)

# Product launch — medium severity (only with citation)
_LAUNCH_KW = re.compile(
    r"\b(launch(?:ed|ing)?|unveiled?|announc(?:ed|ing)?\s+\w+\s+product"
    r"|released?|debut(?:ed)?|general(?:ly)?\s+available)\b",
    re.IGNORECASE,
)

# Lines to skip entirely
_SKIP_RE = re.compile(
    r"^(#{1,6}\s|"           # any heading
    r"\|"                     # table row
    r"|-{3,}"                 # horizontal rule
    r"|\*{3,}"                # bold-only lines
    r"|Run\s+Metadata"
    r"|Sources\s*&?\s*Citations?"
    r"|Failed\s*/\s*Skipped"
    r"|\[\d+\]\s+https?://)"  # citation list entries
)


@dataclass
class TriageItem:
    text: str
    reason: str
    severity: str = "high"        # "high" | "medium"
    section: str = ""
    source_ids: list[int] = field(default_factory=list)


def _citation_ids(text: str) -> list[int]:
    ids: list[int] = []
    for m in _CITATION_RE.finditer(text):
        for part in m.group(1).split(","):
            try:
                ids.append(int(part.strip()))
            except ValueError:
                pass
    return ids


def _score_line(line: str) -> TriageItem | None:
    clean = line.strip("-•* \t")

    # Minimum length guard
    if len(clean) < 30:
        return None

    # Skip structural lines
    if _SKIP_RE.match(clean):
        return None

    # REQUIRED: line must carry at least one citation [n]
    # Without it we cannot verify the claim — governance handles that separately
    ids = _citation_ids(clean)
    if not ids:
        return None

    reasons: list[str] = []
    severity = "medium"

    # HIGH: explicit urgency language
    if _URGENCY_KW.search(clean):
        reasons.append("explicit urgency signal")
        severity = "high"

    # HIGH: M&A / IPO
    if _MA_KW.search(clean):
        reasons.append("M&A / IPO signal")
        severity = "high"

    # HIGH: leadership change
    if _LEADERSHIP_KW.search(clean):
        reasons.append("leadership / personnel change")
        severity = "high"

    # HIGH: pricing with quantified change
    if _PRICING_KW.search(clean) and _QUANTIFIED_CHANGE.search(clean):
        reasons.append("pricing change with quantified impact")
        severity = "high"

    # MEDIUM: funding round
    if _FUNDING_KW.search(clean):
        if severity != "high":
            severity = "medium"
        reasons.append("funding / investment signal")

    # MEDIUM: product launch
    if _LAUNCH_KW.search(clean) and severity == "medium":
        reasons.append("product launch signal")

    if not reasons:
        return None

    return TriageItem(
        text=clean,
        reason="; ".join(reasons),
        severity=severity,
        source_ids=ids,
    )


def triage_briefing(markdown: str) -> list[TriageItem]:
    """Parse markdown report and return high-impact TriageItems, deduplicated."""
    items: list[TriageItem] = []
    seen: set[str] = set()
    current_section = ""

    # Sections to skip entirely — these are structural, not factual claims
    _SKIP_SECTIONS = {"sources & citations", "run metadata", "failed / skipped sources"}

    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()

        if stripped.startswith("## "):
            current_section = stripped.lstrip("# ").strip()
            continue

        if stripped.startswith("#") or not stripped:
            continue

        # Skip non-factual sections
        if current_section.lower() in _SKIP_SECTIONS:
            continue

        item = _score_line(stripped)
        if item is None:
            continue

        dedup_key = item.text[:80].lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        item.section = current_section
        items.append(item)

    # HIGH first, stable order within each tier
    items.sort(key=lambda i: (0 if i.severity == "high" else 1))
    return items
