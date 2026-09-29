"""Task definitions for the 7-agent Memory-First CI Copilot pipeline.

Pipeline order:
  [Discovery →] Research → Memory (Hindsight) → Analyst
              → Strategy Evolution → Prediction → Writer
"""
from __future__ import annotations

from crewai import Agent, Task


def build_tasks(
    agents: dict[str, Agent],
    topic: str,
    competitors: list[str],
) -> list[Task]:
    tasks: list[Task] = []
    discovery_task: Task | None = None

    # ── Discovery (optional when competitors not supplied) ────────────────────
    if not competitors:
        discovery_task = Task(
            description=(
                f"Identify the 3-6 most relevant real, currently-operating competitors "
                f"in the '{topic}' market.\n\n"
                "STRICT RULES:\n"
                "1. Use bounded_web_search with queries like "
                f"'{topic} top companies 2026', '{topic} market leaders'.\n"
                "2. Only include a company confirmed in search results — never invent names.\n"
                "3. Stop if tool returns SEARCH_BUDGET_EXHAUSTED.\n\n"
                "OUTPUT FORMAT:\n"
                "## Competitors\n"
                "Numbered list, one per line, with supporting source id(s):\n"
                "1. Acme Corp [1]\n\n"
                "## Source Index\n"
                "[<id>] <title> | <URL>"
            ),
            expected_output=(
                "## Competitors — numbered list of confirmed company names with [source_id].\n"
                "## Source Index — [id] Title | https://exact-url"
            ),
            agent=agents["discovery"],
        )
        tasks.append(discovery_task)

    comp_list = ", ".join(competitors) if competitors else (
        "the competitors identified in the Discovery Agent's ## Competitors section "
        "(use those exact names — do not invent others)"
    )
    first = competitors[0] if competitors else "the first discovered competitor"

    research_context = [discovery_task] if discovery_task else []

    # ── Research ──────────────────────────────────────────────────────────────
    research_task = Task(
        description=(
            f"Research competitors ONLY in the '{topic}' market: {comp_list}.\n\n"
            "STRICT RULES:\n"
            f"1. Every finding MUST be about: {comp_list}.\n"
            "2. Use bounded_web_search with SHORT queries (max 8 words).\n"
            f"   Examples: '{first} pricing 2026', '{first} product launch 2026'.\n"
            "3. Stop if tool returns SEARCH_BUDGET_EXHAUSTED.\n"
            "4. Do NOT reuse source IDs from the Discovery Agent.\n\n"
            "OUTPUT FORMAT:\n"
            "## Findings\n"
            "One bullet per finding:\n"
            f"- {first}: <exact finding> [<source_id>]\n\n"
            "## Source Index\n"
            "[<id>] <title> | <URL>  (copy URL verbatim from tool output)"
        ),
        expected_output=(
            "## Findings — bullets with [source_id] after each fact.\n"
            "## Source Index — [id] Title | https://exact-url"
        ),
        agent=agents["researcher"],
        context=research_context,
    )
    tasks.append(research_task)

    # ── Memory Agent (Hindsight) ───────────────────────────────────────────────
    memory_task = Task(
        description=(
            f"You are the Memory Agent. Process the Research Agent's findings for '{topic}'.\n\n"
            "REQUIRED STEPS:\n\n"
            "1. STORE NEW EVENTS: For EACH finding in the Research Agent's ## Findings, "
            "   call hindsight_memory with operation='store_event'. Include:\n"
            "   - competitor (exact name)\n"
            "   - event_type (feature_launch|pricing_change|hiring|acquisition|funding|partnership|market_signal)\n"
            "   - event_date (YYYY-MM-DD, use today's date if not specified)\n"
            "   - event_title (concise)\n"
            "   - event_description (what happened and why it matters)\n"
            "   - impact_score (0-10: 9-10=industry-changing, 7-8=major, 5-6=moderate, 3-4=minor)\n"
            "   - confidence (0-1 based on source quality)\n\n"
            "2. RETRIEVE HISTORY: For EACH competitor, call hindsight_memory with "
            "   operation='get_history', days=180, limit=10.\n\n"
            "3. RETRIEVE PROFILES: For EACH competitor, call hindsight_memory with "
            "   operation='get_profile'.\n\n"
            "OUTPUT FORMAT:\n"
            "## Memory Storage Report\n"
            "List each event stored: [competitor] [event_type] [date] [title]\n\n"
            "## Historical Context (6 months)\n"
            "For each competitor: past events from memory that provide context for "
            "the new findings. Explicitly note patterns (e.g., 'OpenAI has now cut "
            "prices 3 times in 6 months — clear commoditization strategy').\n\n"
            "## Memory-Augmented Confidence\n"
            "For each key finding, state whether memory corroborates or contradicts "
            "the new finding, and adjust confidence accordingly.\n\n"
            "## Memory Stats\n"
            "Total events stored: X | Competitors tracked: Y"
        ),
        expected_output=(
            "## Memory Storage Report: list of stored events\n"
            "## Historical Context: 6-month patterns per competitor\n"
            "## Memory-Augmented Confidence: adjusted confidence scores\n"
            "## Memory Stats: total events and competitors"
        ),
        agent=agents["memory"],
        context=[research_task] + ([discovery_task] if discovery_task else []),
    )
    tasks.append(memory_task)

    # ── Analyst ───────────────────────────────────────────────────────────────
    analysis_task = Task(
        description=(
            f"Analyse findings for '{topic}' using BOTH the Research Agent's new data "
            "AND the Memory Agent's historical context.\n\n"
            "STRICT RULES:\n"
            "1. Use ONLY facts from Research ## Findings and Memory ## Historical Context.\n"
            "2. Every claim must carry original source ID(s) in brackets.\n"
            f"3. Only reference: {comp_list}.\n"
            "4. Label single-weak-source claims 'Needs Verification'.\n"
            "5. EXPLICITLY note where memory changed your analysis vs. new-data-only.\n"
            "6. Reproduce the ## Source Index from Research Agent verbatim at end.\n\n"
            "OUTPUT STRUCTURE:\n"
            "## Pricing & Product Analysis\n"
            "## Market Signals\n"
            "## Risk Assessment (use historical threat patterns from memory)\n"
            "## Opportunity Mapping\n"
            "## Memory-Driven Insights (analysis only possible because of historical memory)\n"
            "## Source Index (verbatim from Research Agent)"
        ),
        expected_output=(
            "Structured analysis with 5 sections. Every bullet has [source_id]. "
            "## Memory-Driven Insights section explicitly shows memory value. "
            "## Source Index reproduced verbatim."
        ),
        agent=agents["analyst"],
        context=[research_task, memory_task] + ([discovery_task] if discovery_task else []),
    )
    tasks.append(analysis_task)

    # ── Strategy Evolution ────────────────────────────────────────────────────
    strategy_task = Task(
        description=(
            f"Synthesize strategic evolution for each competitor in '{topic}'.\n\n"
            "For EACH competitor:\n"
            "1. Call hindsight_memory operation='get_history' days=180 to retrieve events.\n"
            "2. Call hindsight_memory operation='get_strategy' to get existing strategy data.\n"
            "3. Group events into 3-4 chronological phases (4-8 weeks each).\n"
            "4. Synthesize ONE strategic label per phase (e.g., 'Enterprise Pricing Expansion').\n"
            "5. Synthesize ONE overall strategy label for the competitor "
            "   (e.g., 'Enterprise AI Domination via Tiered Pricing + Partner Distribution').\n\n"
            "OUTPUT FORMAT:\n"
            "## Strategy Evolution: [Competitor Name]\n"
            "**Overall Strategy**: <one-line label>\n"
            "**Trend Direction**: accelerating|stable|pivoting|declining\n"
            "**Confidence**: X%\n"
            "**Evidence Summary**: <2-3 sentences>\n"
            "**Timeline**:\n"
            "- [Phase Period]: [Strategy Label] (confidence: X%)\n"
            "  Key events: event1, event2\n\n"
            "Repeat for each competitor."
        ),
        expected_output=(
            "## Strategy Evolution section for each competitor with: "
            "Overall Strategy label, Trend Direction, Timeline of phases with confidence, "
            "Evidence Summary."
        ),
        agent=agents["strategy"],
        context=[memory_task, analysis_task],
    )
    tasks.append(strategy_task)

    # ── Prediction ────────────────────────────────────────────────────────────
    prediction_task = Task(
        description=(
            f"Generate evidence-backed predictions for each competitor in '{topic}'.\n\n"
            "For EACH competitor:\n"
            "1. Call hindsight_memory operation='get_history' to retrieve stored events.\n"
            "2. Review the Strategy Evolution Agent's analysis.\n"
            "3. Generate 2-3 specific predictions about the competitor's next move.\n\n"
            "EVERY prediction MUST:\n"
            "- Be specific (not 'will expand' but 'will launch X at $Y/month')\n"
            "- Cite SPECIFIC historical events from memory as supporting_evidence\n"
            "- State the historical pattern (e.g., 'OpenAI launched GPT-4 Team 90 days "
            "  after GPT-4 API — suggesting same pattern for o1')\n"
            "- Include confidence score (0.0-1.0)\n"
            "- Specify timeframe\n\n"
            "OUTPUT FORMAT:\n"
            "## Predictions: [Competitor Name]\n"
            "### Prediction 1\n"
            "**Prediction**: <specific next move>\n"
            "**Confidence**: X%\n"
            "**Timeframe**: Next X-Y days\n"
            "**Category**: product|pricing|hiring|partnership\n"
            "**Supporting Evidence**:\n"
            "- <specific historical event from memory>\n"
            "**Historical Pattern**: <pattern description>\n\n"
            "Repeat for each competitor."
        ),
        expected_output=(
            "## Predictions sections for each competitor. Each prediction: "
            "specific text, confidence score, timeframe, 2+ supporting evidence items "
            "from memory, historical pattern."
        ),
        agent=agents["prediction"],
        context=[strategy_task, memory_task],
    )
    tasks.append(prediction_task)

    # ── Writer ────────────────────────────────────────────────────────────────
    writing_task = Task(
        description=(
            f"Write the final Memory-First Weekly Competitive Intelligence Briefing.\n\n"
            f"Topic: {topic}\n"
            f"Competitors: {comp_list}\n\n"
            "REQUIRED HEADINGS:\n"
            "  ## Executive Summary\n"
            "  ## Competitor Moves (new findings with citations)\n"
            "  ## Market Signals\n"
            "  ## Strategy Evolution Summary (from Strategy Evolution Agent)\n"
            "  ## Predictions (from Prediction Agent, with evidence)\n"
            "  ## Strategic Recommendations\n"
            "  ## Sources & Citations\n\n"
            "MEMORY HIGHLIGHTING RULE:\n"
            "In the Executive Summary, include a 'Memory Advantage' paragraph that "
            "explicitly states what this analysis reveals that a one-shot (no memory) "
            "approach would have missed.\n\n"
            "CITATION RULES:\n"
            "1. Every factual sentence ends with [id] or [id1, id2].\n"
            "2. If no source ID: write 'Needs Verification'.\n"
            "3. ## Sources & Citations: [id] Title — <exact URL from Source Index>.\n"
            "4. Never write 'URL needs verification'. Never invent URLs.\n\n"
            "CONTENT RULES:\n"
            f"- Cover ONLY {topic} and listed competitors.\n"
            "- Predictions section: reproduce predictions with confidence scores.\n"
            "- Strategy Evolution: summarize each competitor's trajectory.\n"
            "- Do NOT add a Run Metadata section.\n"
        ),
        expected_output=(
            "Complete Markdown briefing with 7 ## headings. "
            "Every factual sentence ends with [id] or 'Needs Verification'. "
            "Executive Summary has 'Memory Advantage' paragraph. "
            "## Sources & Citations: [id] Title — https://url"
        ),
        agent=agents["writer"],
        context=[
            research_task,
            memory_task,
            analysis_task,
            strategy_task,
            prediction_task,
        ]
        + ([discovery_task] if discovery_task else []),
    )
    tasks.append(writing_task)

    return tasks
