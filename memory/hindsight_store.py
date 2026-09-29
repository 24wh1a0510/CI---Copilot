"""HindsightStore — Persistent memory engine for the CI Copilot.

Every competitor event is stored permanently in append-only JSONL format.
Profiles, strategies, and predictions are maintained in JSON files.
Thread-safe. Auto-seeds realistic demo data on first run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from models.memory_schemas import (
    CompetitorEvent,
    CompetitorMemoryProfile,
    EventType,
    HiringTrend,
    MemoryStats,
    Prediction,
    PredictionStatus,
    RiskLevel,
    StrategyEvolution,
    StrategyPhase,
    TrendDirection,
)

logger = logging.getLogger(__name__)


class HindsightStore:
    """Persistent, thread-safe store for all competitor intelligence memory."""

    def __init__(self, base_path: str = "data/memory"):
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        self._events_file = self._base / "events.jsonl"
        self._profiles_file = self._base / "profiles.json"
        self._strategies_file = self._base / "strategies.json"
        self._predictions_file = self._base / "predictions.json"
        self._lock = threading.Lock()

        # In-memory caches (rebuilt from disk on init)
        self._events: list[CompetitorEvent] = []
        self._profiles: dict[str, CompetitorMemoryProfile] = {}
        self._strategies: dict[str, StrategyEvolution] = {}
        self._predictions: list[Prediction] = []

        self._load_all()

        # Seed demo data if completely empty
        if not self._events:
            self._seed_demo_data()

    # ── Load / Persist ────────────────────────────────────────────────────────

    def _load_all(self) -> None:
        """Load all persisted data into memory caches."""
        # Events (JSONL)
        if self._events_file.exists():
            with open(self._events_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._events.append(CompetitorEvent.model_validate_json(line))
                        except Exception:
                            pass

        # Profiles (JSON dict)
        if self._profiles_file.exists():
            try:
                with open(self._profiles_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        self._profiles[k] = CompetitorMemoryProfile.model_validate(v)
            except Exception:
                pass

        # Strategies (JSON dict)
        if self._strategies_file.exists():
            try:
                with open(self._strategies_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        self._strategies[k] = StrategyEvolution.model_validate(v)
            except Exception:
                pass

        # Predictions (JSON list)
        if self._predictions_file.exists():
            try:
                with open(self._predictions_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    self._predictions = [Prediction.model_validate(p) for p in raw]
            except Exception:
                pass

    def _persist_events(self) -> None:
        """Append the last event to the JSONL file (append-only)."""
        if self._events:
            with open(self._events_file, "a", encoding="utf-8") as f:
                f.write(self._events[-1].model_dump_json() + "\n")

    def _persist_profiles(self) -> None:
        with open(self._profiles_file, "w", encoding="utf-8") as f:
            data = {k: v.model_dump(mode="json") for k, v in self._profiles.items()}
            json.dump(data, f, indent=2, default=str)

    def _persist_strategies(self) -> None:
        with open(self._strategies_file, "w", encoding="utf-8") as f:
            data = {k: v.model_dump(mode="json") for k, v in self._strategies.items()}
            json.dump(data, f, indent=2, default=str)

    def _persist_predictions(self) -> None:
        with open(self._predictions_file, "w", encoding="utf-8") as f:
            data = [p.model_dump(mode="json") for p in self._predictions]
            json.dump(data, f, indent=2, default=str)

    # ── Events API ────────────────────────────────────────────────────────────

    def store_event(self, event: CompetitorEvent) -> CompetitorEvent:
        """Persist a new competitor event and update the relevant profile."""
        with self._lock:
            self._events.append(event)
            self._persist_events()
            self._update_profile_from_event(event)
        return event

    def get_events(
        self,
        competitor: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
        days: Optional[int] = None,
    ) -> list[CompetitorEvent]:
        with self._lock:
            results = list(self._events)

        if competitor:
            results = [e for e in results if e.competitor.lower() == competitor.lower()]
        if event_type:
            results = [e for e in results if e.event_type.value == event_type]
        if days:
            # BUG FIX #2: use proper date parsing instead of string comparison
            # which is fragile for non-zero-padded or non-ISO dates.
            cutoff = (datetime.utcnow() - timedelta(days=days)).date()
            filtered = []
            for e in results:
                try:
                    event_date = datetime.strptime(e.date, "%Y-%m-%d").date()
                    if event_date >= cutoff:
                        filtered.append(e)
                except ValueError:
                    # If date is malformed, include event (don't silently drop it)
                    filtered.append(e)
            results = filtered

        # Newest first
        results.sort(key=lambda e: e.date, reverse=True)
        return results[:limit]

    def get_timeline(self, competitor: Optional[str] = None, days: int = 180) -> list[CompetitorEvent]:
        """Chronological timeline for Memory Timeline page."""
        events = self.get_events(competitor=competitor, days=days, limit=500)
        events.sort(key=lambda e: e.date)
        return events

    def search_memory(self, query: str) -> list[CompetitorEvent]:
        """Simple keyword search across events."""
        q = query.lower()
        with self._lock:
            results = [
                e for e in self._events
                if q in e.title.lower()
                or q in e.description.lower()
                or q in e.competitor.lower()
            ]
        return sorted(results, key=lambda e: e.date, reverse=True)[:50]

    # ── Profile API ───────────────────────────────────────────────────────────

    def get_memory_profile(self, competitor: str) -> Optional[CompetitorMemoryProfile]:
        with self._lock:
            return self._profiles.get(competitor)

    def update_memory_profile(self, profile: CompetitorMemoryProfile) -> None:
        with self._lock:
            profile.last_updated = datetime.utcnow()
            self._profiles[profile.competitor] = profile
            self._persist_profiles()

    def get_all_profiles(self) -> list[CompetitorMemoryProfile]:
        with self._lock:
            return list(self._profiles.values())

    def _update_profile_from_event(self, event: CompetitorEvent) -> None:
        """Auto-update the competitor profile based on a new event."""
        prof = self._profiles.get(event.competitor) or CompetitorMemoryProfile(competitor=event.competitor)

        # Add event to profile history (keep last 50)
        prof.historical_events.append(event)
        prof.historical_events = sorted(prof.historical_events, key=lambda e: e.date, reverse=True)[:50]
        prof.total_events = len([e for e in self._events if e.competitor == event.competitor])

        # BUG FIX #3: innovation_score claimed to use 90-day recency but had NO date filter.
        # Now filters to actual 90-day window using proper date parsing.
        ninety_days_ago = (datetime.utcnow() - timedelta(days=90)).date()
        recent = []
        for e in self._events:
            if e.competitor != event.competitor:
                continue
            if e.event_type not in (EventType.FEATURE_LAUNCH, EventType.ACQUISITION, EventType.PARTNERSHIP):
                continue
            try:
                event_date = datetime.strptime(e.date, "%Y-%m-%d").date()
                if event_date >= ninety_days_ago:
                    recent.append(e)
            except ValueError:
                # Include malformed dates to be conservative
                recent.append(e)
        prof.innovation_score = min(10.0, len(recent) * 1.2)

        # Update hiring trend from hiring events
        hiring_events = [e for e in self._events if e.competitor == event.competitor and e.event_type == EventType.HIRING]
        if len(hiring_events) >= 4:
            prof.hiring_trend = HiringTrend.SURGING
        elif len(hiring_events) >= 2:
            prof.hiring_trend = HiringTrend.GROWING
        else:
            prof.hiring_trend = HiringTrend.STABLE

        # Risk level from impact scores
        high_impact = [e for e in self._events if e.competitor == event.competitor and e.impact_score >= 8.0]
        if len(high_impact) >= 3:
            prof.risk_level = RiskLevel.CRITICAL
        elif len(high_impact) >= 1:
            prof.risk_level = RiskLevel.HIGH
        elif prof.total_events >= 5:
            prof.risk_level = RiskLevel.MEDIUM

        # Confidence from event count
        prof.confidence_score = min(0.98, 0.3 + (prof.total_events * 0.07))

        prof.last_updated = datetime.utcnow()
        self._profiles[event.competitor] = prof
        self._persist_profiles()

    # ── Strategy API ──────────────────────────────────────────────────────────

    def get_strategy_evolution(self, competitor: str) -> Optional[StrategyEvolution]:
        with self._lock:
            return self._strategies.get(competitor)

    def save_strategy_evolution(self, evolution: StrategyEvolution) -> None:
        with self._lock:
            evolution.last_updated = datetime.utcnow()
            self._strategies[evolution.competitor] = evolution
            self._persist_strategies()

    def get_all_strategies(self) -> list[StrategyEvolution]:
        with self._lock:
            return list(self._strategies.values())

    # ── Predictions API ───────────────────────────────────────────────────────

    def get_predictions(self, competitor: Optional[str] = None) -> list[Prediction]:
        with self._lock:
            preds = list(self._predictions)
        if competitor:
            preds = [p for p in preds if p.competitor.lower() == competitor.lower()]
        return sorted(preds, key=lambda p: p.created_at, reverse=True)

    def save_prediction(self, pred: Prediction) -> Prediction:
        with self._lock:
            self._predictions.append(pred)
            self._persist_predictions()
        return pred

    def update_prediction_status(self, pred_id: str, status: PredictionStatus) -> bool:
        """Update prediction status. Returns True if found, False if pred_id unknown.

        BUG FIX #4: Original silently ignored unknown pred_id and returned None.
        Now returns a bool so callers can detect failures.
        """
        with self._lock:
            for p in self._predictions:
                if p.id == pred_id:
                    p.status = status
                    self._persist_predictions()
                    return True
        logger.warning("update_prediction_status: pred_id=%r not found", pred_id)
        return False

    # ── Stats API ─────────────────────────────────────────────────────────────

    def get_stats(self) -> MemoryStats:
        with self._lock:
            total_events = len(self._events)
            competitors_tracked = len(self._profiles)
            predictions_generated = len(self._predictions)
            # Strategic alerts = critical + high risk competitors
            alerts = sum(
                1 for p in self._profiles.values()
                if p.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)
            )
            # Estimate memory size from file sizes
            size_kb = 0.0
            for fp in [self._events_file, self._profiles_file, self._strategies_file, self._predictions_file]:
                if fp.exists():
                    size_kb += fp.stat().st_size / 1024

        return MemoryStats(
            total_events=total_events,
            competitors_tracked=competitors_tracked,
            predictions_generated=predictions_generated,
            strategic_alerts=alerts,
            memory_size_kb=round(size_kb, 1),
        )

    # ── Export API ────────────────────────────────────────────────────────────

    def export_profile_markdown(self, competitor: str) -> str:
        """Export a competitor profile as Markdown text."""
        prof = self.get_memory_profile(competitor)
        if not prof:
            return f"# {competitor}\n\nNo memory data available yet.\n"

        lines = [
            f"# {competitor} — Intelligence Profile",
            f"\n**Last Updated:** {prof.last_updated.strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Confidence Score:** {prof.confidence_score:.0%}",
            f"**Innovation Score:** {prof.innovation_score:.1f}/10",
            f"**Risk Level:** {prof.risk_level.value.upper()}",
            f"**Hiring Trend:** {prof.hiring_trend.value}",
            f"**Pricing Strategy:** {prof.pricing_strategy}",
            f"**Market Focus:** {prof.market_focus}",
            "\n## Opportunities",
        ]
        for o in prof.opportunities:
            lines.append(f"- {o}")
        lines.append("\n## Threats")
        for t in prof.threats:
            lines.append(f"- {t}")
        lines.append(f"\n## Event History ({prof.total_events} events)")
        for ev in prof.historical_events[:10]:
            lines.append(f"\n### [{ev.date}] {ev.title}")
            lines.append(f"**Type:** {ev.event_type.value} | **Impact:** {ev.impact_score:.0f}/10 | **Confidence:** {ev.confidence:.0%}")
            lines.append(ev.description)

        return "\n".join(lines)

    def clear_all(self) -> None:
        """Wipe all memory (dev/testing use only)."""
        with self._lock:
            self._events = []
            self._profiles = {}
            self._strategies = {}
            self._predictions = []
            for fp in [self._events_file, self._profiles_file, self._strategies_file, self._predictions_file]:
                if fp.exists():
                    fp.unlink()

    # ── Demo Seed Data ────────────────────────────────────────────────────────

    def _seed_demo_data(self) -> None:
        """Seed 6 months of realistic AI competitor events for demo purposes.

        BUG FIX #1: Original wrote directly to JSONL and called
        _update_profile_from_event bypassing store_event(), causing any
        hooks on store_event to be skipped.  Now uses store_event() for all
        event writes so the full persist/profile-update pipeline fires.
        The lock is released before each store_event call to avoid deadlock
        since store_event acquires it internally.
        """

        def d(months_ago: int, day: int = 15) -> str:
            base = datetime.utcnow()
            target = base - timedelta(days=months_ago * 30 + (15 - day))
            return target.date().isoformat()

        events_data = [
            # ── OpenAI ────────────────────────────────────────────────
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(6, 1),
                title="GPT-4o multimodal launch",
                description="OpenAI launches GPT-4o with native audio, vision, and text capabilities in a single model. Significantly lowers latency for voice interactions.",
                impact_score=9.5, confidence=0.97,
                evidence_urls=["https://openai.com/blog/gpt-4o"],
            ),
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.PRICING_CHANGE,
                date=d(5, 10),
                title="GPT-4o input pricing cut 50%",
                description="OpenAI cuts GPT-4o API input pricing from $5 to $2.50 per million tokens, intensifying pressure on competitors.",
                impact_score=8.8, confidence=0.99,
                evidence_urls=["https://openai.com/api/pricing"],
            ),
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.HIRING,
                date=d(5, 20),
                title="Massive enterprise sales hiring wave",
                description="OpenAI posts 80+ enterprise sales roles targeting Fortune 500 companies. Clear signal of enterprise-first go-to-market pivot.",
                impact_score=7.2, confidence=0.88,
                evidence_urls=["https://openai.com/careers"],
            ),
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(4, 5),
                title="ChatGPT Team plan launched",
                description="New ChatGPT Team plan at $25/user/month targets SMBs and teams, with shared workspace and admin controls.",
                impact_score=7.8, confidence=0.95,
                evidence_urls=["https://openai.com/chatgpt/team"],
            ),
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.PARTNERSHIP,
                date=d(4, 18),
                title="Microsoft Azure OpenAI expansion",
                description="Microsoft and OpenAI announce expanded Azure OpenAI Service with GPT-4o integration and enterprise SLAs. Deal value estimated $10B+.",
                impact_score=9.0, confidence=0.98,
                evidence_urls=["https://azure.microsoft.com/openai"],
            ),
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(3, 8),
                title="o1 reasoning model released",
                description="OpenAI releases o1 series with chain-of-thought reasoning. Significantly outperforms on coding and math benchmarks.",
                impact_score=9.2, confidence=0.99,
                evidence_urls=["https://openai.com/o1"],
            ),
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.PRICING_CHANGE,
                date=d(2, 5),
                title="Enterprise tier introduced at $60/user/month",
                description="OpenAI launches ChatGPT Enterprise with dedicated compute, SSO, and data privacy controls at $60/user/month minimum 150 seats.",
                impact_score=8.5, confidence=0.97,
                evidence_urls=["https://openai.com/chatgpt/enterprise"],
            ),
            CompetitorEvent(
                competitor="OpenAI",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(1, 12),
                title="GPT-4o mini fine-tuning GA",
                description="Fine-tuning for GPT-4o mini now generally available. Enables customers to create custom models from 10,000+ examples.",
                impact_score=7.5, confidence=0.94,
                evidence_urls=["https://openai.com/fine-tuning"],
            ),

            # ── Anthropic ─────────────────────────────────────────────
            CompetitorEvent(
                competitor="Anthropic",
                event_type=EventType.FUNDING,
                date=d(6, 5),
                title="$4B investment from Amazon AWS",
                description="Amazon invests up to $4B in Anthropic and makes Claude available on AWS Bedrock. Anthropic valued at $18B post-money.",
                impact_score=9.8, confidence=0.99,
                evidence_urls=["https://anthropic.com/news/amazon-investment"],
            ),
            CompetitorEvent(
                competitor="Anthropic",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(5, 22),
                title="Claude 3 Opus released — beats GPT-4",
                description="Anthropic releases Claude 3 family. Opus model surpasses GPT-4 on MMLU, HumanEval, and reasoning benchmarks. Context window extended to 200K tokens.",
                impact_score=9.5, confidence=0.98,
                evidence_urls=["https://anthropic.com/claude-3"],
            ),
            CompetitorEvent(
                competitor="Anthropic",
                event_type=EventType.HIRING,
                date=d(5, 5),
                title="50+ AI safety researcher hires",
                description="Anthropic aggressively recruits from OpenAI and DeepMind for AI safety and alignment roles. Signals differentiation through safety positioning.",
                impact_score=6.5, confidence=0.85,
                evidence_urls=["https://anthropic.com/careers"],
            ),
            CompetitorEvent(
                competitor="Anthropic",
                event_type=EventType.PRICING_CHANGE,
                date=d(4, 12),
                title="Claude 3 Haiku pricing at $0.25/M tokens",
                description="Anthropic launches Claude 3 Haiku at $0.25/M input tokens — aggressively undercutting OpenAI on cost for high-volume enterprise use cases.",
                impact_score=8.0, confidence=0.97,
                evidence_urls=["https://anthropic.com/pricing"],
            ),
            CompetitorEvent(
                competitor="Anthropic",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(3, 20),
                title="Computer use capabilities beta",
                description="Anthropic releases 'computer use' capability allowing Claude to operate desktop interfaces. First mover in agentic computer control.",
                impact_score=9.0, confidence=0.96,
                evidence_urls=["https://anthropic.com/computer-use"],
            ),
            CompetitorEvent(
                competitor="Anthropic",
                event_type=EventType.PARTNERSHIP,
                date=d(2, 18),
                title="Salesforce Einstein integration",
                description="Anthropic and Salesforce partner to embed Claude in Salesforce Einstein platform. Access to 150,000+ enterprise customers.",
                impact_score=8.8, confidence=0.92,
                evidence_urls=["https://salesforce.com/anthropic"],
            ),
            CompetitorEvent(
                competitor="Anthropic",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(1, 8),
                title="Claude claude.ai Artifacts feature",
                description="Claude.ai launches Artifacts — interactive code and document generation within the chat interface. Direct response to OpenAI Canvas.",
                impact_score=7.8, confidence=0.94,
                evidence_urls=["https://claude.ai"],
            ),

            # ── Google DeepMind ────────────────────────────────────────
            CompetitorEvent(
                competitor="Google DeepMind",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(6, 8),
                title="Gemini 1.5 Pro with 1M token context",
                description="Google releases Gemini 1.5 Pro with industry-first 1 million token context window. Enables analysis of entire codebases and hours of video.",
                impact_score=9.3, confidence=0.99,
                evidence_urls=["https://deepmind.google/gemini"],
            ),
            CompetitorEvent(
                competitor="Google DeepMind",
                event_type=EventType.ACQUISITION,
                date=d(5, 14),
                title="DeepMind absorbs Google Brain fully",
                description="Alphabet completes merger of Google Brain and DeepMind into single Google DeepMind unit. Estimated 3,000+ combined researchers.",
                impact_score=8.5, confidence=0.99,
                evidence_urls=["https://deepmind.google"],
            ),
            CompetitorEvent(
                competitor="Google DeepMind",
                event_type=EventType.PRICING_CHANGE,
                date=d(4, 25),
                title="Gemini API: free tier 1M tokens/day",
                description="Google introduces generous free tier on Gemini API — 1M tokens per day free. Clear developer-acquisition strategy vs. OpenAI.",
                impact_score=7.5, confidence=0.96,
                evidence_urls=["https://ai.google.dev/pricing"],
            ),
            CompetitorEvent(
                competitor="Google DeepMind",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(3, 15),
                title="NotebookLM Plus with Gemini 1.5",
                description="NotebookLM Plus launched with Gemini 1.5, enabling deep research on uploaded documents. Goes viral with 5M users in 30 days.",
                impact_score=8.0, confidence=0.95,
                evidence_urls=["https://notebooklm.google"],
            ),
            CompetitorEvent(
                competitor="Google DeepMind",
                event_type=EventType.PARTNERSHIP,
                date=d(2, 10),
                title="Samsung Galaxy AI integration",
                description="Google DeepMind integrates Gemini across Samsung Galaxy device lineup. Reaches 300M+ mobile users instantly.",
                impact_score=8.5, confidence=0.97,
                evidence_urls=["https://samsung.com/gemini"],
            ),
            CompetitorEvent(
                competitor="Google DeepMind",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(1, 20),
                title="Gemini 2.0 Flash: 10x faster inference",
                description="Gemini 2.0 Flash delivers 10x faster inference at 30% lower cost. Targets real-time applications and agentic workflows.",
                impact_score=9.0, confidence=0.98,
                evidence_urls=["https://deepmind.google/gemini-2"],
            ),

            # ── Microsoft Copilot ──────────────────────────────────────
            CompetitorEvent(
                competitor="Microsoft Copilot",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(6, 3),
                title="Microsoft 365 Copilot GA launch",
                description="Microsoft 365 Copilot generally available at $30/user/month. Embeds AI into Word, Excel, PowerPoint, Teams, and Outlook.",
                impact_score=9.5, confidence=0.99,
                evidence_urls=["https://microsoft.com/copilot"],
            ),
            CompetitorEvent(
                competitor="Microsoft Copilot",
                event_type=EventType.HIRING,
                date=d(5, 12),
                title="10,000 AI engineering hires announced",
                description="Microsoft announces 10,000 AI-focused engineering hires over 18 months. Largest single AI talent acquisition wave in industry history.",
                impact_score=8.0, confidence=0.95,
                evidence_urls=["https://microsoft.com/careers"],
            ),
            CompetitorEvent(
                competitor="Microsoft Copilot",
                event_type=EventType.PRICING_CHANGE,
                date=d(5, 1),
                title="Copilot Pro at $20/month consumer tier",
                description="Microsoft launches Copilot Pro for consumers at $20/month, giving GPT-4 Turbo access with priority. Competing directly with ChatGPT Plus.",
                impact_score=7.8, confidence=0.98,
                evidence_urls=["https://microsoft.com/copilot-pro"],
            ),
            CompetitorEvent(
                competitor="Microsoft Copilot",
                event_type=EventType.ACQUISITION,
                date=d(4, 8),
                title="Inflection AI talent acqui-hire",
                description="Microsoft acquires key Inflection AI talent including co-founder Mustafa Suleyman to lead consumer AI division.",
                impact_score=8.8, confidence=0.97,
                evidence_urls=["https://microsoft.com/inflection"],
            ),
            CompetitorEvent(
                competitor="Microsoft Copilot",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(3, 10),
                title="Copilot Studio: build AI agents in minutes",
                description="Microsoft launches Copilot Studio enabling enterprise users to build custom AI agents with no-code interface on top of Azure OpenAI.",
                impact_score=8.5, confidence=0.96,
                evidence_urls=["https://microsoft.com/copilot-studio"],
            ),
            CompetitorEvent(
                competitor="Microsoft Copilot",
                event_type=EventType.PARTNERSHIP,
                date=d(2, 5),
                title="SAP S/4HANA Copilot embedded integration",
                description="Microsoft and SAP embed Copilot directly into S/4HANA workflows. Reaches 400M+ SAP enterprise users.",
                impact_score=8.2, confidence=0.93,
                evidence_urls=["https://microsoft.com/sap-copilot"],
            ),
            CompetitorEvent(
                competitor="Microsoft Copilot",
                event_type=EventType.FEATURE_LAUNCH,
                date=d(1, 5),
                title="Copilot Pages: collaborative AI workspace",
                description="Copilot Pages launches as a persistent collaborative canvas powered by GPT-4o. Direct competitor to Notion AI and Google Workspace.",
                impact_score=7.5, confidence=0.94,
                evidence_urls=["https://microsoft.com/copilot-pages"],
            ),
        ]

        # Store all events via store_event() so the full pipeline fires
        for event in events_data:
            self.store_event(event)

        # Enrich profiles with domain knowledge
        enrichments = {
            "OpenAI": {
                "market_focus": "Enterprise AI, API-first LLM, Consumer AI assistants",
                "pricing_strategy": "Tiered API + SaaS (Free → Plus $20 → Team $25 → Enterprise $60/user)",
                "opportunities": [
                    "Capture enterprise deals via Microsoft distribution",
                    "Fine-tuning market is high-margin and defensible",
                    "o1 series creates a moat for reasoning-heavy workloads",
                ],
                "threats": [
                    "Anthropic closing the benchmark gap rapidly",
                    "Open-source models commoditizing base LLM capabilities",
                    "Regulatory scrutiny on market concentration",
                ],
            },
            "Anthropic": {
                "market_focus": "Safety-first AI, Enterprise API, Agentic AI workflows",
                "pricing_strategy": "Competitive underpricing on Haiku tier, premium for Opus",
                "opportunities": [
                    "Safety positioning resonates with risk-averse enterprises",
                    "Computer use creates new agentic automation market",
                    "Amazon distribution could rival Microsoft OpenAI",
                ],
                "threats": [
                    "Heavy dependence on Amazon for cloud distribution",
                    "OpenAI's brand recognition is significantly larger",
                    "Slower product cadence vs. Google and OpenAI",
                ],
            },
            "Google DeepMind": {
                "market_focus": "Long-context AI, Mobile AI, Research infrastructure",
                "pricing_strategy": "Aggressive free tiers for developer acquisition, enterprise paid",
                "opportunities": [
                    "1M token context is unmatched — unique enterprise use cases",
                    "Android/Samsung distribution gives instant mobile scale",
                    "DeepMind research depth creates compounding advantages",
                ],
                "threats": [
                    "Internal execution complexity from Brain/DeepMind merger",
                    "Search revenue cannibalization risk from AI Overviews",
                    "Consumer trust deficit vs. OpenAI brand",
                ],
            },
            "Microsoft Copilot": {
                "market_focus": "Enterprise productivity AI, Office 365, Developer tools",
                "pricing_strategy": "Bundle into M365 at $30/user premium, consumer Pro at $20",
                "opportunities": [
                    "Existing 400M+ M365 seats are natural upsell targets",
                    "Copilot Studio creates platform ecosystem lock-in",
                    "SAP/Salesforce integrations reach entire enterprise software stack",
                ],
                "threats": [
                    "Adoption rate of $30 Copilot lower than projected",
                    "GPT-4 dependency creates existential risk if OpenAI pivots",
                    "GitHub Copilot facing increasing competition from Cursor and others",
                ],
            },
        }

        with self._lock:
            for competitor, data in enrichments.items():
                prof = self._profiles.get(competitor)
                if prof:
                    prof.market_focus = data["market_focus"]
                    prof.pricing_strategy = data["pricing_strategy"]
                    prof.opportunities = data["opportunities"]
                    prof.threats = data["threats"]
                    self._profiles[competitor] = prof
            self._persist_profiles()

        # Seed strategy evolutions
        strategies = [
            StrategyEvolution(
                competitor="OpenAI",
                timeline=[
                    StrategyPhase(period="Mar 2025", dominant_strategy="API Commoditization", key_events=["GPT-4o launch", "50% price cut"], confidence=0.95),
                    StrategyPhase(period="May 2025", dominant_strategy="Enterprise Expansion", key_events=["ChatGPT Team plan", "80+ sales hires"], confidence=0.90),
                    StrategyPhase(period="Jul 2025", dominant_strategy="Reasoning Moat", key_events=["o1 model release", "Microsoft Azure expansion"], confidence=0.92),
                    StrategyPhase(period="Sep 2025", dominant_strategy="Enterprise Lock-in", key_events=["Enterprise tier $60/user", "GPT-4o mini fine-tuning GA"], confidence=0.88),
                ],
                synthesized_strategy="Enterprise AI Domination via Tiered Pricing + Partner Distribution",
                evidence_summary="OpenAI systematically lowered API costs to win developers, then monetized enterprise through SaaS tiers. o1 reasoning model creates high-value moat.",
                confidence_score=0.94,
                trend_direction=TrendDirection.ACCELERATING,
            ),
            StrategyEvolution(
                competitor="Anthropic",
                timeline=[
                    StrategyPhase(period="Mar 2025", dominant_strategy="Safety Positioning + Funding", key_events=["$4B Amazon deal"], confidence=0.99),
                    StrategyPhase(period="May 2025", dominant_strategy="Benchmark Leadership", key_events=["Claude 3 Opus beats GPT-4", "200K context window"], confidence=0.97),
                    StrategyPhase(period="Jul 2025", dominant_strategy="Enterprise Cost Attack", key_events=["Haiku at $0.25/M tokens", "50 safety researcher hires"], confidence=0.93),
                    StrategyPhase(period="Sep 2025", dominant_strategy="Agentic AI Leadership", key_events=["Computer use beta", "Salesforce partnership"], confidence=0.91),
                ],
                synthesized_strategy="Safety-First Enterprise AI with Aggressive Pricing and Agentic Differentiation",
                evidence_summary="Anthropic secured massive funding, won on benchmarks, undercut on price, then moved to first-mover agentic computer use.",
                confidence_score=0.92,
                trend_direction=TrendDirection.ACCELERATING,
            ),
            StrategyEvolution(
                competitor="Google DeepMind",
                timeline=[
                    StrategyPhase(period="Mar 2025", dominant_strategy="Context Window Race", key_events=["Gemini 1.5 Pro 1M tokens"], confidence=0.99),
                    StrategyPhase(period="May 2025", dominant_strategy="Research Consolidation", key_events=["DeepMind + Brain merger"], confidence=0.98),
                    StrategyPhase(period="Jul 2025", dominant_strategy="Developer Acquisition", key_events=["Free tier 1M tokens/day"], confidence=0.95),
                    StrategyPhase(period="Sep 2025", dominant_strategy="Consumer & Mobile Scale", key_events=["Samsung Galaxy AI", "NotebookLM viral growth"], confidence=0.92),
                ],
                synthesized_strategy="Scale-First AI via Free Tiers, Mobile Distribution, and Research Compounding",
                evidence_summary="Google plays a long game: give away tokens for developer mindshare, distribute via Samsung's 300M device install base, compound through research superiority.",
                confidence_score=0.88,
                trend_direction=TrendDirection.ACCELERATING,
            ),
            StrategyEvolution(
                competitor="Microsoft Copilot",
                timeline=[
                    StrategyPhase(period="Mar 2025", dominant_strategy="Enterprise Bundling", key_events=["M365 Copilot GA at $30/user"], confidence=0.99),
                    StrategyPhase(period="May 2025", dominant_strategy="Talent & Talent Acquisition", key_events=["10K AI hires", "Inflection acqui-hire"], confidence=0.95),
                    StrategyPhase(period="Jul 2025", dominant_strategy="Consumer Entry", key_events=["Copilot Pro $20/month", "Copilot Studio launch"], confidence=0.93),
                    StrategyPhase(period="Sep 2025", dominant_strategy="Platform Ecosystem", key_events=["SAP integration", "Copilot Pages launch"], confidence=0.90),
                ],
                synthesized_strategy="Productivity AI Platform Lock-in via M365 Bundle and Enterprise Ecosystem Integrations",
                evidence_summary="Microsoft leverages existing enterprise relationships to force Copilot adoption through M365 bundling, then extends to SAP, Salesforce, and developer tools.",
                confidence_score=0.91,
                trend_direction=TrendDirection.STABLE,
            ),
        ]

        with self._lock:
            for strat in strategies:
                self._strategies[strat.competitor] = strat
            self._persist_strategies()

        # Seed predictions
        predictions = [
            Prediction(
                competitor="OpenAI",
                prediction_text="OpenAI will launch a dedicated agentic AI product (Operator) for enterprise workflow automation at $100+/user/month",
                confidence=0.82,
                supporting_evidence=[
                    "o1 reasoning model demonstrates deep task planning capability",
                    "Enterprise tier pricing already at $60/user shows premium tolerance",
                    "Anthropic computer use success validates market demand",
                ],
                historical_pattern="OpenAI consistently follows successful beta features with paid enterprise tiers within 90 days",
                predicted_timeframe="Next 30-60 days",
                category="product",
                status=PredictionStatus.PENDING,
            ),
            Prediction(
                competitor="Anthropic",
                prediction_text="Anthropic will launch Claude API multi-agent orchestration with native computer use GA, targeting enterprise DevOps workflows",
                confidence=0.78,
                supporting_evidence=[
                    "Computer use beta has strong developer uptake signals",
                    "Salesforce partnership gives enterprise pipeline access",
                    "Safety-first narrative resonates with regulated industries",
                ],
                historical_pattern="Anthropic betas typically graduate to GA within 60-90 days based on Claude 3 release cadence",
                predicted_timeframe="Next 45-75 days",
                category="product",
                status=PredictionStatus.PENDING,
            ),
            Prediction(
                competitor="Google DeepMind",
                prediction_text="Google will cut Gemini API prices by 40-60% to defend developer market share against OpenAI's pricing pressure",
                confidence=0.85,
                supporting_evidence=[
                    "Already offered 1M free tokens/day to acquire developers",
                    "OpenAI's 50% price cut forced competitive response historically",
                    "Google has infrastructure cost advantages at scale",
                ],
                historical_pattern="Google responds to OpenAI pricing moves within 30 days — pattern confirmed twice in last 6 months",
                predicted_timeframe="Next 20-45 days",
                category="pricing",
                status=PredictionStatus.PENDING,
            ),
            Prediction(
                competitor="Microsoft Copilot",
                prediction_text="Microsoft will lower Copilot M365 price to $20/user to accelerate adoption after underwhelming uptake signals",
                confidence=0.71,
                supporting_evidence=[
                    "Enterprise adoption of $30 tier has been slower than projected per analyst reports",
                    "Consumer Copilot Pro at $20 shows willingness to price at this tier",
                    "Google Workspace AI bundling at lower price creates pressure",
                ],
                historical_pattern="Microsoft has historically adjusted enterprise SaaS pricing after 12-18 month adoption review cycles",
                predicted_timeframe="Next 60-90 days",
                category="pricing",
                status=PredictionStatus.PENDING,
            ),
        ]

        with self._lock:
            for pred in predictions:
                self._predictions.append(pred)
            self._persist_predictions()
