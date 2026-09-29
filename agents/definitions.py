"""CrewAI Agent definitions for the Memory-First CI Copilot.

Seven agents in the pipeline:
  Supervisor → Discovery → Research → Memory (Hindsight) → Analyst
             → Strategy Evolution → Prediction → Writer

The Memory Agent is deeply integrated: it stores every event from Research
into HindsightStore and enriches Analyst input with 6-month historical context,
making every subsequent analysis visibly better over time.
"""
from __future__ import annotations

import json
from typing import Any, Optional, Type

from crewai import Agent, LLM
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config.settings import settings
from logging_.audit_logger import AuditLogger
from memory.hindsight_store import HindsightStore
from models.memory_schemas import (
    CompetitorEvent,
    EventType,
    Prediction,
    PredictionStatus,
    StrategyEvolution,
    StrategyPhase,
    TrendDirection,
)
from tools.search_tool import BoundedWebSearchTool, SearchBudget


# ── LLM Factory ───────────────────────────────────────────────────────────────

def get_llm() -> LLM:
    if settings.openrouter_api_key:
        model_name = settings.openrouter_model
        if not model_name.startswith("openrouter/"):
            model_name = f"openrouter/{model_name}"
        return LLM(
            model=model_name,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
    if settings.openai_api_key:
        kwargs: dict = dict(
            model=f"openai/{settings.openai_model}",
            api_key=settings.openai_api_key,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        return LLM(**kwargs)
    raise RuntimeError(
        "No LLM provider configured. Set OPENROUTER_API_KEY or OPENAI_API_KEY in .env."
    )


# ── Hindsight Tool Schema & Implementation ────────────────────────────────────

class HindsightToolInput(BaseModel):
    operation: str = Field(
        description=(
            "One of: store_event | get_history | get_profile | search_memory | "
            "get_predictions | get_strategy"
        )
    )
    competitor: Optional[str] = Field(default=None, description="Competitor name")
    event_type: Optional[str] = Field(
        default=None,
        description="Event type: feature_launch|pricing_change|hiring|acquisition|funding|partnership|market_signal",
    )
    query: Optional[str] = Field(default=None, description="Search query for search_memory")
    days: Optional[int] = Field(default=180, description="Number of days to look back")
    limit: Optional[int] = Field(default=20, description="Max results to return")
    # Fields for store_event
    event_title: Optional[str] = Field(default=None, description="Title of the event")
    event_description: Optional[str] = Field(default=None, description="Description of the event")
    event_date: Optional[str] = Field(default=None, description="Date of the event YYYY-MM-DD")
    impact_score: Optional[float] = Field(default=5.0, description="Impact 0-10")
    confidence: Optional[float] = Field(default=0.7, description="Confidence 0-1")
    source_ids: Optional[list[int]] = Field(default=None, description="Source IDs from research")
    evidence_urls: Optional[list[str]] = Field(default=None, description="Evidence URLs")


class HindsightStoreTool(BaseTool):
    """A CrewAI tool that wraps the HindsightStore for agent use.

    Agents call this tool to:
    - store_event: persist a new competitor event
    - get_history: retrieve historical events for a competitor
    - get_profile: get the current intelligence profile
    - search_memory: keyword search across all stored events
    - get_predictions: retrieve existing predictions
    - get_strategy: get strategy evolution data
    """

    name: str = "hindsight_memory"
    description: str = (
        "Persistent competitive intelligence memory. Use this to: "
        "(1) store_event — save a new competitor event with impact_score and confidence; "
        "(2) get_history — retrieve last N months of events for a competitor; "
        "(3) get_profile — get the evolving intelligence profile for a competitor; "
        "(4) search_memory — keyword search across all stored memory; "
        "(5) get_predictions — retrieve existing predictions for a competitor; "
        "(6) get_strategy — get strategy evolution analysis for a competitor. "
        "Memory visibly improves analysis quality over time."
    )
    args_schema: Type[BaseModel] = HindsightToolInput
    store: Any = None  # HindsightStore instance, set at creation

    def _run(
        self,
        operation: str,
        competitor: Optional[str] = None,
        event_type: Optional[str] = None,
        query: Optional[str] = None,
        days: int = 180,
        limit: int = 20,
        event_title: Optional[str] = None,
        event_description: Optional[str] = None,
        event_date: Optional[str] = None,
        impact_score: float = 5.0,
        confidence: float = 0.7,
        source_ids: Optional[list[int]] = None,
        evidence_urls: Optional[list[str]] = None,
    ) -> str:
        store: HindsightStore = self.store

        if operation == "store_event":
            if not all([competitor, event_title, event_description, event_date, event_type]):
                return "ERROR: store_event requires competitor, event_title, event_description, event_date, event_type"
            try:
                ev_type = EventType(event_type)
            except ValueError:
                ev_type = EventType.MARKET_SIGNAL
            event = CompetitorEvent(
                competitor=competitor,
                event_type=ev_type,
                date=event_date,
                title=event_title,
                description=event_description,
                impact_score=impact_score,
                confidence=confidence,
                source_ids=source_ids or [],
                evidence_urls=evidence_urls or [],
            )
            stored = store.store_event(event)
            return (
                f"✓ Stored event: [{stored.id}] {event_type.upper()} for {competitor} "
                f"on {event_date}. Impact: {impact_score}/10. Confidence: {confidence:.0%}. "
                f"Memory now has {store.get_stats().total_events} total events."
            )

        elif operation == "get_history":
            if not competitor:
                return "ERROR: get_history requires competitor"
            events = store.get_events(competitor=competitor, days=days, limit=limit)
            if not events:
                return f"No memory events found for {competitor} in the last {days} days."
            lines = [f"## Memory History: {competitor} (last {days} days, {len(events)} events)\n"]
            for ev in events:
                lines.append(
                    f"- [{ev.date}] **{ev.event_type.value.upper()}**: {ev.title} "
                    f"(impact: {ev.impact_score}/10, confidence: {ev.confidence:.0%})\n"
                    f"  {ev.description}"
                )
            return "\n".join(lines)

        elif operation == "get_profile":
            if not competitor:
                return "ERROR: get_profile requires competitor"
            prof = store.get_memory_profile(competitor)
            if not prof:
                return f"No profile found for {competitor}. Store events first."
            return (
                f"## Intelligence Profile: {competitor}\n"
                f"- Market Focus: {prof.market_focus}\n"
                f"- Innovation Score: {prof.innovation_score:.1f}/10\n"
                f"- Pricing Strategy: {prof.pricing_strategy}\n"
                f"- Hiring Trend: {prof.hiring_trend.value}\n"
                f"- Risk Level: {prof.risk_level.value.upper()}\n"
                f"- Confidence: {prof.confidence_score:.0%}\n"
                f"- Total Events in Memory: {prof.total_events}\n"
                f"- Opportunities: {'; '.join(prof.opportunities[:3])}\n"
                f"- Threats: {'; '.join(prof.threats[:3])}\n"
                f"- Last Updated: {prof.last_updated.strftime('%Y-%m-%d')}"
            )

        elif operation == "search_memory":
            if not query:
                return "ERROR: search_memory requires query"
            results = store.search_memory(query)
            if not results:
                return f"No memory events match '{query}'."
            lines = [f"## Memory Search: '{query}' ({len(results)} matches)\n"]
            for ev in results[:limit]:
                lines.append(
                    f"- [{ev.date}] {ev.competitor}: {ev.title} "
                    f"[{ev.event_type.value}] impact={ev.impact_score}"
                )
            return "\n".join(lines)

        elif operation == "get_predictions":
            preds = store.get_predictions(competitor=competitor)
            if not preds:
                return f"No predictions found{' for ' + competitor if competitor else ''}."
            lines = [f"## Predictions ({len(preds)} total)\n"]
            for p in preds[:limit]:
                lines.append(
                    f"- [{p.competitor}] {p.prediction_text} "
                    f"(confidence: {p.confidence:.0%}, timeframe: {p.predicted_timeframe})"
                )
            return "\n".join(lines)

        elif operation == "get_strategy":
            if not competitor:
                return "ERROR: get_strategy requires competitor"
            strat = store.get_strategy_evolution(competitor)
            if not strat:
                return f"No strategy evolution data for {competitor} yet."
            lines = [
                f"## Strategy Evolution: {competitor}",
                f"**Synthesized Strategy:** {strat.synthesized_strategy}",
                f"**Trend:** {strat.trend_direction.value} | **Confidence:** {strat.confidence_score:.0%}",
                "\n### Timeline:",
            ]
            for phase in strat.timeline:
                lines.append(
                    f"- **{phase.period}**: {phase.dominant_strategy} "
                    f"(confidence: {phase.confidence:.0%})"
                )
                for event in phase.key_events:
                    lines.append(f"  • {event}")
            return "\n".join(lines)

        return f"ERROR: Unknown operation '{operation}'. Valid: store_event|get_history|get_profile|search_memory|get_predictions|get_strategy"


# ── Agent Factory ─────────────────────────────────────────────────────────────

def build_agents(
    budget: SearchBudget,
    audit: AuditLogger,
    store: Optional[HindsightStore] = None,
) -> dict[str, Agent]:
    llm = get_llm()
    search_tool = BoundedWebSearchTool(budget=budget, audit=audit, collected_sources=[])

    if store is None:
        store = HindsightStore(base_path=settings.hindsight_memory_path)

    hindsight_tool = HindsightStoreTool(store=store)

    # ── Supervisor ───────────────────────────────────────────────────────────
    supervisor = Agent(
        role="Supervisor",
        goal=(
            "Orchestrate all agents — Discovery, Research, Memory, Analyst, "
            "Strategy Evolution, Prediction, and Writer — to produce a memory-enriched, "
            "governed, cited weekly competitive intelligence briefing. "
            f"Enforce {budget.max_sources} sources and {budget.max_steps} steps. "
            "If any agent fails, log it and ensure the pipeline produces the best "
            "possible partial result rather than crashing."
        ),
        backstory=(
            "A meticulous strategy-operations lead who has run hundreds of intelligence "
            "sprints. You never let a flaky source derail a deliverable, and you know "
            "that memory-enriched analysis is always superior to one-shot research."
        ),
        allow_delegation=True,
        verbose=True,
        llm=llm,
    )

    # ── Discovery ────────────────────────────────────────────────────────────
    discovery = Agent(
        role="Competitor Discovery Agent",
        goal=(
            "Given only a market/topic name, identify 3-6 most relevant real, "
            "currently-operating companies. Use bounded_web_search with queries like "
            "'<topic> top companies 2026'. Only include companies confirmed in search "
            "results — never invent names. Output a numbered list plus ## Source Index."
        ),
        backstory=(
            "A market-mapping specialist who scans industry roundups, comparison "
            "articles, and analyst reports to identify who actually competes in a space."
        ),
        tools=[search_tool],
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )

    # ── Researcher ───────────────────────────────────────────────────────────
    researcher = Agent(
        role="Research Agent",
        goal=(
            "Find recent, credible information on each competitor's pricing changes, "
            "product launches, partnerships, acquisitions, funding, and market trends. "
            "For EVERY source, record its exact integer ID and URL from tool output. "
            "Output MUST include ## Findings and ## Source Index sections."
        ),
        backstory=(
            "A former equity-research analyst turned OSINT specialist. Fast at scanning "
            "search results for what matters to a VP of Strategy. Rigorous about sourcing."
        ),
        tools=[search_tool],
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )

    # ── Memory Agent (Hindsight) ──────────────────────────────────────────────
    memory_agent = Agent(
        role="Memory Agent (Hindsight)",
        goal=(
            "You are the institutional memory of this intelligence system. Your job: "
            "(1) Extract every competitor event from the Research Agent's findings and "
            "    store them in Hindsight memory using the hindsight_memory tool. "
            "(2) Retrieve 6-month historical context for each competitor from memory. "
            "(3) Produce a MEMORY-ENRICHED CONTEXT report that shows: "
            "    - New events found (with impact scores and confidence) "
            "    - Historical patterns from memory (what happened in last 6 months) "
            "    - Memory-augmented confidence scores for each finding. "
            "The Analyst Agent MUST receive this memory context to make better decisions. "
            "Without memory, analysis is generic. With memory, it is strategic."
        ),
        backstory=(
            "You never forget a competitor move. Every event you store today makes "
            "tomorrow's analysis better. You have perfect recall of 6+ months of "
            "competitor activity and you synthesize patterns humans would miss. "
            "Your memory is the primary value proposition of this entire system."
        ),
        tools=[hindsight_tool],
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )

    # ── Analyst ──────────────────────────────────────────────────────────────
    analyst = Agent(
        role="Analyst Agent",
        goal=(
            "Compare competitors using the Memory Agent's enriched context (which includes "
            "BOTH new research findings AND 6 months of historical memory). "
            "Identify pricing changes, product updates, market signals, risks, and "
            "opportunities. Your analysis must explicitly reference historical patterns "
            "from memory. Label single-source claims 'Needs Verification'. Keep all source IDs. "
            "Reproduce the ## Source Index verbatim at end of output."
        ),
        backstory=(
            "A skeptical market analyst who uses both fresh research and historical memory "
            "to produce analysis that no one-shot researcher can match. You know that "
            "a competitor's current pricing change is only meaningful in the context "
            "of their pricing history stored in memory."
        ),
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )

    # ── Strategy Evolution Agent ──────────────────────────────────────────────
    strategy_agent = Agent(
        role="Strategy Evolution Agent",
        goal=(
            "Analyze all stored memory events for each competitor to identify strategic "
            "patterns across time. Group events into phases (4-8 week periods). "
            "For each competitor synthesize a 1-sentence strategy label like "
            "'Enterprise AI Expansion via Tiered Pricing + Partner Distribution'. "
            "Use the hindsight_memory tool with get_history and get_strategy operations. "
            "Output strategy phases with confidence scores and a trend direction."
        ),
        backstory=(
            "A strategy consultant who specializes in pattern recognition across "
            "competitive timelines. You see the forest, not just the trees. "
            "When OpenAI cuts prices, hires sales people, and launches a team plan "
            "in the same quarter — you recognize that as an Enterprise Expansion strategy, "
            "not three unrelated events."
        ),
        tools=[hindsight_tool],
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )

    # ── Prediction Agent ──────────────────────────────────────────────────────
    prediction_agent = Agent(
        role="Prediction Agent",
        goal=(
            "Using the Strategy Evolution Agent's analysis and all historical memory, "
            "generate 2-3 specific, evidence-backed predictions for each competitor's "
            "next move. EVERY prediction MUST: "
            "(1) Cite specific historical events from memory as supporting evidence. "
            "(2) Reference the historical pattern that supports the prediction. "
            "(3) Include a confidence score (0.0-1.0) based on evidence strength. "
            "(4) Specify a predicted timeframe (e.g. 'Next 30-60 days'). "
            "Use hindsight_memory get_history and get_strategy to gather evidence. "
            "Never make a prediction without citing specific stored memory events."
        ),
        backstory=(
            "A competitive intelligence analyst who has accurately predicted 7 of the "
            "last 10 major product moves in the AI market by systematically tracking "
            "patterns in competitor behavior stored in memory. You never guess — "
            "every prediction is grounded in specific historical evidence."
        ),
        tools=[hindsight_tool],
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )

    # ── Writer ────────────────────────────────────────────────────────────────
    writer = Agent(
        role="Writer Agent",
        goal=(
            "Turn the full pipeline outputs into a polished Memory-First Weekly Briefing. "
            "Every factual sentence ends with a bracketed citation [id]. "
            "The report must include: Executive Summary, Competitor Moves, Market Signals, "
            "Strategy Evolution Summary, Predictions (with evidence), Recommendations, "
            "and Sources & Citations. "
            "Highlight where memory improved the analysis vs. a one-shot approach. "
            "Never invent URLs — copy verbatim from Source Index."
        ),
        backstory=(
            "A former McKinsey communications lead who turns complex intelligence into "
            "executive-ready briefings. You understand that this system's unique value "
            "is persistent memory, so you always highlight memory-driven insights prominently."
        ),
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )

    return {
        "supervisor": supervisor,
        "discovery": discovery,
        "researcher": researcher,
        "memory": memory_agent,
        "analyst": analyst,
        "strategy": strategy_agent,
        "prediction": prediction_agent,
        "writer": writer,
    }
