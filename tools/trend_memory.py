"""Trend Memory — persists briefing history to a local JSON file and produces
a line-level diff between the current run and the previous run for the same
topic + competitors combination.

Storage: data/briefing_history.json  (one JSON array of run records)
"""
from __future__ import annotations

import difflib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.schemas import Briefing

_HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "briefing_history.json"


def _load_history() -> list[dict]:
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(history: list[dict]) -> None:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")


def _normalize_key(topic: str, competitors: list[str]) -> str:
    """Canonical key for matching runs."""
    return f"{topic.lower().strip()}|{','.join(sorted(c.lower().strip() for c in competitors))}"


def save_briefing(topic: str, competitors: list[str], briefing: "Briefing") -> None:
    """Append a summary of the current briefing to the history file."""
    history = _load_history()

    # Build a compact insights summary
    insights_summary = [
        {
            "competitor": ins.competitor,
            "category": ins.category,
            "insight": ins.insight[:200],
            "confidence_tag": getattr(ins, "confidence_tag", "unknown"),
        }
        for ins in (briefing.insights or [])
    ]

    record = {
        "run_id": briefing.metadata.run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "topic": topic,
        "competitors": competitors,
        "_key": _normalize_key(topic, competitors),
        "markdown": briefing.markdown,
        "insights_summary": insights_summary,
    }
    history.append(record)
    # Keep only the last 50 records to avoid unbounded growth
    history = history[-50:]
    _save_history(history)


def load_last_briefing(topic: str, competitors: list[str]) -> dict | None:
    """Return the most recent history record matching topic + competitors, or None."""
    history = _load_history()
    key = _normalize_key(topic, competitors)
    # Walk backwards — most recent first
    for record in reversed(history):
        if record.get("_key") == key:
            return record
    return None


def diff_insights(current_markdown: str, previous_markdown: str) -> str:
    """Return a Markdown string summarising added/removed bullet points.

    Uses difflib.unified_diff on bullet lines (lines starting with - or *).
    """
    def extract_bullets(md: str) -> list[str]:
        lines = []
        for line in md.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                lines.append(stripped)
        return lines

    prev_bullets = extract_bullets(previous_markdown)
    curr_bullets = extract_bullets(current_markdown)

    diff = list(
        difflib.unified_diff(
            prev_bullets,
            curr_bullets,
            fromfile="previous_run",
            tofile="current_run",
            lineterm="",
        )
    )

    if not diff:
        return "_No changes detected compared to the previous run._"

    added = [ln[1:].strip() for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:].strip() for ln in diff if ln.startswith("-") and not ln.startswith("---")]

    parts: list[str] = []
    if added:
        parts.append("**New / Updated findings:**")
        parts.extend(f"+ {a}" for a in added)
    if removed:
        parts.append("\n**Removed / No longer mentioned:**")
        parts.extend(f"- {r}" for r in removed)

    return "\n".join(parts) if parts else "_No bullet-level changes detected._"
