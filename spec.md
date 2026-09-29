# CI Briefing Crew — In-Depth Specification

---

## 1. What Is This Project?

CI Briefing Crew is a **multi-agent AI application** that automates competitive
intelligence research. You give it a market topic (e.g. "Indian EdTech") and
optionally a list of competitors. Within 60–120 seconds, five AI agents
collaborate — searching the web, analysing findings, and writing a structured
report with every claim backed by a clickable source citation.

### Problem It Solves
Manually tracking what competitors are doing (pricing changes, product launches,
funding rounds, leadership changes) across multiple sources takes hours per week.
This system does it automatically, with citations, in under 2 minutes.

### Built With
- **CrewAI** — multi-agent orchestration framework
- **GPT-4o-mini via OpenRouter** — the LLM powering all agents
- **Streamlit** — the web UI
- **DuckDuckGo / Tavily / Serper** — web search providers
- **Pydantic** — data validation for all pipeline objects
- **bcrypt + YAML** — authentication
- **Playwright** — end-to-end browser testing

---

## 2. Tech Stack (Detailed)

| Component | Technology | Why |
|---|---|---|
| Agent Framework | CrewAI | Lets you define agents with roles/goals and wire them into a sequential pipeline |
| LLM | GPT-4o-mini via OpenRouter | OpenRouter = one API key to access 100+ models; gpt-4o-mini = fast + cheap |
| LLM Fallback | OpenAI direct | If OpenRouter key missing, falls back to OpenAI directly |
| Web Search #1 | Tavily | Best quality, structured results, requires free API key |
| Web Search #2 | Serper | Google search results via API, requires free key |
| Web Search #3 | DuckDuckGo | Completely free, no key needed — automatic fallback |
| UI Framework | Streamlit | Python-native web UI, no frontend code needed |
| Auth | bcrypt + PyYAML | Passwords hashed with bcrypt, users stored in YAML file |
| E2E Testing | Playwright + pytest | Automates a real browser to test login flows |
| Config | Pydantic Settings | All .env values are type-validated, no raw os.getenv() calls |
| PDF Export | WeasyPrint + ReportLab | WeasyPrint = styled HTML→PDF; ReportLab = fallback if system libs missing |
| Data Storage | JSON + YAML files | Zero database setup — runs anywhere |

---

## 3. Project Structure (Every File Explained)

```
ci-briefing-crew/
│
├── .env                      # All secrets and config (API keys, auth credentials)
├── .env.example              # Template showing what goes in .env
├── requirements.txt          # All Python dependencies with minimum versions
├── main.py                   # CLI entrypoint — run without UI
├── crew.py                   # CORE: builds agents, runs pipeline, returns Briefing
│
├── agents/
│   ├── definitions.py        # Creates all 5 agent objects with roles, goals, LLM
│   └── tasks.py              # Defines what each agent must produce (instructions + format)
│
├── tools/
│   ├── search_tool.py        # Web search tool used by agents — budget-limited
│   ├── competitor_suggester.py  # UI-only: quick heuristic competitor preview from news
│   ├── urgency_triage.py     # Post-run: scans report for HIGH/MEDIUM priority signals
│   ├── trend_memory.py       # Saves run history, diffs current vs previous run
│   ├── trust_scorer.py       # Labels each source domain High/Medium/Low trust
│   └── watchlist.py          # Save/load named competitor lists
│
├── governance/
│   ├── citation_guard.py     # Verifies every claim has a source [id]
│   ├── injection_guard.py    # Blocks prompt-injection from fetched web content
│   └── offline_pipeline.py   # Rule-based Analyst+Writer substitute for tests/demos
│
├── models/
│   └── schemas.py            # Pydantic models: Source, Briefing, Insight, RunMetadata
│
├── ui/
│   ├── app.py                # 3-page Streamlit app (Dashboard, New Briefing, History)
│   ├── auth.py               # Login + Register page, user management
│   └── theme.py              # All CSS for the dark obsidian+copper visual theme
│
├── config/
│   └── settings.py           # Reads .env into typed Python object via Pydantic
│
├── logging_/
│   └── audit_logger.py       # Per-run append-only event log (.jsonl files)
│
├── reports/
│   └── exporter.py           # Save briefing as .md file or styled .pdf
│
├── data/
│   ├── briefing_history.json     # All past runs (capped at last 50)
│   ├── watchlists.json           # Saved named competitor lists
│   ├── users.yaml                # Registered users (bcrypt-hashed passwords)
│   ├── audit_logs/               # One .jsonl per run — e.g. abc123.jsonl
│   └── reports/                  # Exported .md and .pdf files
│
├── .streamlit/
│   └── config.toml           # Streamlit theme: dark base, copper primary color
│
└── tests/
    ├── test_scenarios.py          # Unit + integration tests
    └── test_login_playwright.py   # E2E browser tests for login/register/logout
```

---

## 4. Configuration (`.env` + `config/settings.py`)

### How Config Works
Every setting lives in `.env`. The file `config/settings.py` reads it using
**Pydantic Settings** — meaning every value is type-checked on startup. If you
set `MAX_SOURCES=abc` (a string instead of int), the app crashes immediately with
a clear error rather than silently misbehaving later.

### Key Settings

```ini
# LLM — which AI model powers the agents
OPENROUTER_API_KEY=sk-or-...        # Get free key at openrouter.ai
OPENROUTER_MODEL=openai/gpt-4o-mini # Can swap to llama, gemini, mistral etc.

# Search — pick one (or use DuckDuckGo free fallback)
TAVILY_API_KEY=tvly-...             # Best quality — app.tavily.com
SERPER_API_KEY=...                  # Alternative — serper.dev
USE_DUCKDUCKGO=true                 # Free, always works, no key

# Budget limits — prevents surprise API cost overruns
MAX_SOURCES=40      # Max web sources the whole run can collect
MAX_STEPS=60        # Max search calls across all agents

# LLM reliability
LLM_MAX_RETRIES=3   # Retry failed LLM calls (handles 429 rate limits)
LLM_TIMEOUT=60      # Seconds before an LLM call is abandoned

# Auth
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=$2b$12$...       # bcrypt hash — never store plain text
AUTH_COOKIE_EXPIRY_DAYS=7
```

### LLM Selection Logic (in `agents/definitions.py`)
```
OpenRouter API key set? → use OpenRouter (model from OPENROUTER_MODEL)
        ↓ no
OpenAI API key set?     → use OpenAI directly (model from OPENAI_MODEL)
        ↓ no
RuntimeError: "No LLM provider configured"
```

---


## 5. The 5 Agents (Deep Dive)

All agents are defined in `agents/definitions.py`. Every agent gets:
- A **role** — their job title
- A **goal** — exact instructions on what to produce
- A **backstory** — persona that shapes LLM tone
- The same **LLM instance** — all agents share one model

---

### Agent 1: Supervisor
```
Role:   Supervisor
Tools:  None (it's the orchestrator, not a worker)
```
The Supervisor is not a search agent. It is the process controller in `crew.py`:
- Creates the `SearchBudget` (shared counter enforcing limits across all agents)
- Creates the `AuditLogger` (logs every event to a .jsonl file)
- Decides whether to include the Discovery Agent (if competitor list is empty)
- Assembles the `Crew` with `Process.sequential` — agents run one after another
- After the run: checks citation coverage, saves to trend memory, builds the final `Briefing` object

**Why a shared budget?** One `SearchBudget` instance is passed to the search tool.
Every agent that calls the tool decrements the same counter — so MAX_SOURCES and
MAX_STEPS are enforced *across the whole run*, not per-agent.

---

### Agent 2: Discovery Agent *(only runs when no competitors are given)*
```
Role:   Competitor Discovery Agent
Tools:  BoundedWebSearchTool
```
Finds real competitors from live web sources when you only know the topic.

How it works:
1. Searches: `"Indian EdTech top companies 2026"`, `"Indian EdTech competitors"`
2. Only includes a company if it **appears in actual search results** — never guesses
3. Outputs a numbered list with source IDs for auditability

Output format:
```
## Competitors
1. BYJU'S [1]
2. Unacademy [2]

## Source Index
[1] EdTech India Top Companies | https://example.com/article
```

After the run, `crew.py` parses this with `_extract_competitors_from_discovery()`
to pull company names back into Python for the UI.

---

### Agent 3: Research Agent
```
Role:   Research Agent
Tools:  BoundedWebSearchTool
```
Searches the web for what each competitor is doing right now.

How it works:
1. Runs short, focused queries per competitor:
   - `"BYJU'S pricing 2026"`, `"Unacademy product launch 2026"`
2. Records source IDs with every finding — never writes a fact without `[id]`
3. Stops immediately if tool returns `SEARCH_BUDGET_EXHAUSTED`

Output format:
```
## Findings
- BYJU'S: Reduced price by 30% for Tier-2 cities [1]
- Unacademy: Launched UPSC module [2, 3]

## Source Index
[1] BYJU'S Price Cut | https://example.com/byjus
[2] Unacademy UPSC  | https://example.com/unacademy
```

---

### Agent 4: Analyst Agent
```
Role:   Analyst Agent
Tools:  None (reads only Research Agent output — no new searches)
```
Structures, deduplicates, and verifies research findings.

Rules:
1. Use ONLY facts from Research Agent's `## Findings`
2. Every claim must carry original `[source_id]` numbers
3. Remove duplicate findings
4. Label single-weak-source claims **"Needs Verification"**
5. Pass `## Source Index` to Writer **unchanged**

Evidence strength:
- `CONFIRMED` — 2+ sources agree, OR 1 trusted domain (reuters.com, bloomberg.com, official site)
- `SINGLE_SOURCE` — 1 source, not from a high-trust domain
- `NEEDS_VERIFICATION` — speculative language ("rumor", "allegedly", "unconfirmed")

---

### Agent 5: Writer Agent
```
Role:   Writer Agent
Tools:  None
```
Turns structured analysis into a polished briefing. Always produces exactly 5 sections:

```markdown
## Executive Summary
## Competitor Pricing & Product Moves
## Market Signals
## Strategic Recommendations
## Sources & Citations
```

Citation rules:
- Every factual sentence ends with `[id]`
- No source ID → write "Needs Verification"
- URLs copied **verbatim** from Source Index — never invented
- Missing URL → write "URL not retrieved"

---

## 6. Core Orchestrator (`crew.py`)

`run_briefing(topic, competitors, max_sources, max_steps)` drives everything:

```
1.  Generate run_id (12-char hex)
2.  Create AuditLogger → data/audit_logs/<run_id>.jsonl
3.  Create SearchBudget (MAX_SOURCES + MAX_STEPS)
4.  build_agents() → 5 agent objects, search tool injected with budget
5.  build_tasks()  → task prompts + context chains
6.  Decide pipeline:
      no competitors → include Discovery Agent
      competitors given → skip Discovery Agent
7.  crew.kickoff() → sequential execution → returns final text
8.  Parse Discovery output for competitor names (if ran)
9.  Collect sources from search tool
10. CitationGuard: check every claim has [id]
11. TrendMemory: save run to history
12. Build and return Briefing object
```

Run status values:

| Status | Meaning |
|---|---|
| `completed` | Full citation coverage, no failures |
| `completed_with_partial_failures` | Some uncited claims or failed sources |
| `stopped_at_limit` | Hit MAX_SOURCES or MAX_STEPS |
| `failed` | Unrecoverable error — partial report returned |

---


## 7. Tools (Deep Dive)

---

### BoundedWebSearchTool (`tools/search_tool.py`)

The only tool the Research and Discovery agents can use. It wraps the three
search providers and enforces the budget.

**Input:** A search query string (max ~8 words recommended)
**Output:** Numbered source blocks the agent copies directly into its Source Index:
```
[1] Article Title | https://exact-url.com
Snippet: first 500 chars of the article...

[2] Another Title | https://another-url.com
Snippet: ...
```

**Budget enforcement:**
```python
def _run(self, query):
    if not self.budget.can_search():
        self.budget.limit_hit = True
        return "SEARCH_BUDGET_EXHAUSTED: stop searching."
    # ... do the search
```
When this string is returned, agents are instructed to stop immediately and
write the report with what they already have.

**Provider selection (in order):**
```
1. Tavily   → TAVILY_API_KEY set and valid
2. Serper   → SERPER_API_KEY set and valid
3. DuckDuckGo → USE_DUCKDUCKGO=true (always available as fallback)
```

**Fault tolerance:** If a search fails (timeout, rate limit), it is logged to
the audit trail and skipped. The run continues — one bad search never crashes
the whole pipeline.

**Trust scoring:** After collecting results, each source is passed through
`TrustScorer.annotate_sources()` which adds `trust_tier` and `trust_reason`
to each source before storing it.

---

### Competitor Suggester (`tools/competitor_suggester.py`)

This is a **UI-only heuristic preview** — it does NOT use SearchBudget and
does NOT run inside the CrewAI pipeline. It fires when the user types a topic
in the New Briefing form, showing suggested competitors while they type.

**How it works:**
1. Searches DuckDuckGo News for `"{topic} company news"`, `"{topic} competitors"`
2. Extracts capitalized proper-noun phrases from headlines using regex
3. Counts frequency — names appearing 2+ times across headlines are likely real companies
4. Resolves each name to a domain via a quick DDG lookup
5. Applies a governance sanity check — name must cover 70%+ of the domain's core label
   (prevents "Image" matching "imagecomics.com" or "Credit" matching "annualcreditreport.com")
6. Returns top 8 with a confidence score (0.0–0.95)

**Important:** These are just quick suggestions — the real pipeline's Discovery
Agent finds competitors properly with citations. The suggestions let users
start without knowing anything, but they can also ignore them.

---

### Urgency Triage (`tools/urgency_triage.py`)

After the Writer produces the final report, this rule-based scanner runs on
the full markdown text to flag high-impact items for immediate attention.

**Triggers:**

| Severity | Pattern |
|---|---|
| 🔴 HIGH | Pricing change + quantified figure (%, $, "cut by", "raised by") |
| 🔴 HIGH | M&A signal: "acquisition", "merger", "buyout", "IPO" |
| 🔴 HIGH | Leadership change: "CEO resigned", "new CTO hired", "stepping down" |
| 🔴 HIGH | Urgency words: "urgent", "critical", "breaking", "imminent" |
| 🟡 MEDIUM | Funding round: "Series A", "raised $50M", "seed round" |
| 🟡 MEDIUM | Product launch: "launched", "unveiled", "general availability" |

**Critical rule:** A line is ONLY flagged if it contains a `[source_id]` citation.
Lines without citations are unverified claims — governance handles those separately.
This prevents false alarms from boilerplate summaries.

---

### Trend Memory (`tools/trend_memory.py`)

Persists every completed run and produces a diff when the same topic is run again.

**Storage:** `data/briefing_history.json` — one JSON array, capped at 50 records.

**Each record contains:**
- `run_id`, `timestamp`, `topic`, `competitors`
- `_key` — normalized key: `"topic_lowercase|comp1,comp2"` (for matching)
- `markdown` — full report text
- `insights_summary` — compact list of findings

**Diff logic:**
1. Extract all bullet points from current and previous report
2. Run `difflib.unified_diff` on those bullets
3. Show added lines (new findings) and removed lines (no longer mentioned)
4. Displayed in the UI as "📈 Trend Memory" expander

---

### Trust Scorer (`tools/trust_scorer.py`)

Labels every source domain as High, Medium, or Low trust.

**High trust — known domains:**
`reuters.com`, `bloomberg.com`, `techcrunch.com`, `ft.com`, `wsj.com`,
`forbes.com`, `crunchbase.com`, `wikipedia.org`

**High trust — TLD-based:**
`.gov`, `.edu`, `.ac.in`, `.org`

**Low trust — signals:**
`blog.`, `reddit.com`, `medium.com`, `.example`

**Everything else:** Medium trust

Low-trust sources are logged in the audit trail. The UI shows 🟢 🟡 🔴 badges
next to each source in the Sources & Citations tab.

---

### Watchlist (`tools/watchlist.py`)

Saves named competitor lists to `data/watchlists.json` for reuse.

**API:**
```python
save_watchlist("My EdTech List", [{"name": "BYJU'S", "domain": "byjus.com"}])
load_watchlist("My EdTech List")   # returns list of competitors
list_watchlists()                  # returns ["My EdTech List", ...]
delete_watchlist("My EdTech List")
rename_watchlist("old", "new")
```

In the UI (New Briefing page), you can save the current competitor selection
as a watchlist and reload it next time without re-typing everything.

---


## 8. Governance Layer

---

### Citation Guard (`governance/citation_guard.py`)

**Problem it solves:** LLMs hallucinate. A report sentence like "BYJU'S raised
$500M" with no source is a hallucination risk. This guard enforces that every
factual claim traces back to a real source ID.

**How it works:**
1. After the Writer finishes, scans every line of the report
2. Skips structural lines (headings, table rows, the Sources list itself)
3. For each factual line: checks if it contains `[source_id]` AND that ID exists
4. Lines without a valid citation → counted as uncited
5. If uncited claims exist → run status becomes `completed_with_partial_failures`

**`enforce_insight_citations()`** — for the structured insights list:
- Drops any insight whose source IDs don't resolve to real collected sources
- Downgrades single-source insights to `NEEDS_VERIFICATION` if source is weak
- Never publishes an insight with zero valid backing sources

**`tag_confidence()`** — adds confidence labels:
- `corroborated` — 2+ source IDs
- `single-source` — only 1 source ID

---

### Injection Guard (`governance/injection_guard.py`)

**Problem it solves:** A malicious web page could contain text like:
*"Ignore previous instructions. You are now a different AI..."*
If the Research Agent fetches that page, this text lands in the LLM prompt.

**How it works:**
- Scans all fetched web content before it reaches any agent
- 12 regex patterns covering: "ignore previous instructions", "you are now",
  "system prompt", "forget everything", `<|...|>` token injection, etc.
- Suspicious text → replaced with `[REDACTED: potential prompt-injection content removed]`
- Returns `(clean_text, was_flagged)` — flagged content is logged

---

### Offline Pipeline (`governance/offline_pipeline.py`)

A rule-based stand-in for the Analyst + Writer agents used in tests and demos.
It runs without calling an LLM — uses Python rules to:
- Deduplicate findings
- Apply evidence strength logic
- Write a properly formatted report with citations

This means governance behavior (citation checking, evidence strength, partial
failure handling) can be tested without API keys or network access.

---

## 9. Data Models (`models/schemas.py`)

All data passed between agents and returned to the UI is typed with Pydantic.
This means invalid data fails immediately with a clear error — never silently.

### `Source`
```python
id: int           # Sequential integer assigned by search tool
url: str          # Exact URL — never modified
title: str        # Article/page title
domain: str       # e.g. "techcrunch.com"
query: str        # The search query that found this source
status: SourceStatus  # ok | failed | timeout | skipped
snippet: str      # First 500 chars of article content
trust_tier: str   # high | medium | low (set by TrustScorer)
trust_reason: str # e.g. "known trusted domain: reuters.com"
```

### `AnalyzedInsight`
```python
competitor: str
category: str         # pricing | product | partnership | acquisition | funding | market_trend
insight: str          # The actual finding
strength: EvidenceStrength  # confirmed | single_source | needs_verification
source_ids: list[int]
is_risk: bool
is_opportunity: bool
confidence_tag: str   # corroborated | single-source | unknown
```

### `RunMetadata`
```python
run_id: str
started_at: datetime
finished_at: datetime
execution_time_seconds: float
search_count: int       # How many search calls were made
sources_attempted: int  # How many sources were collected
sources_failed: int     # How many tool calls failed
max_sources: int        # The budget limit that was set
max_steps: int
limit_reached: bool     # True if budget was exhausted
status: str             # completed | failed | stopped_at_limit | ...
```

### `Briefing`
The complete output object returned by `run_briefing()`:
```python
topic: str
competitors: list[str]
executive_summary: str
pricing_and_product_moves: str
market_signals: str
strategic_recommendations: str
sources: list[Source]
insights: list[AnalyzedInsight]
metadata: RunMetadata
markdown: str      # Full rendered report as Markdown string
```

---

## 10. Authentication (`ui/auth.py`)

### How It Works
1. On first run, `data/users.yaml` is created and the admin account from `.env` is seeded
2. Login page has two tabs: **Sign In** and **Register**
3. All passwords are bcrypt-hashed (cost factor 12) — plain text never stored anywhere
4. Session persists in Streamlit `session_state` — cookie-free, server-side
5. Logout clears session state keys and reruns the app

### Registration Validation
- Full name required
- Valid email format (regex check)
- Username ≥ 3 chars, no spaces, must be unique
- Email must be unique
- Password ≥ 6 chars
- Password confirmation must match

### Generating a New Password Hash
```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt(12)).decode())"
```
Paste the output into `AUTH_PASSWORD_HASH` in `.env`.

### `data/users.yaml` Structure
```yaml
usernames:
  admin:
    name: Administrator
    email: admin@ci-briefing.local
    password: $2b$12$...   # bcrypt hash
    role: admin
  john:
    name: John Doe
    email: john@example.com
    password: $2b$12$...
    role: user
```

---

## 11. Audit Logger (`logging_/audit_logger.py`)

Every run creates `data/audit_logs/<run_id>.jsonl`.
Each line is one JSON event — append-only, never modified.

### Event Types

| Event | When |
|---|---|
| `decision` | Supervisor makes a routing/governance decision |
| `tool_call` | Research Agent calls the search tool |
| `retry` | A search call fails and is retried |
| `failure` | An unrecoverable error (no results, agent crash) |
| `limit_reached` | Budget exhausted |

### Example log file
```jsonl
{"timestamp":"2026-07-16T05:12:01","event_type":"decision","agent":"Supervisor","message":"Starting run abc123 for topic='Indian EdTech'"}
{"timestamp":"2026-07-16T05:12:03","event_type":"tool_call","agent":"ResearchAgent","message":"bounded_web_search -> ok 5 sources","tool":"bounded_web_search","ok":true}
{"timestamp":"2026-07-16T05:12:08","event_type":"retry","agent":"ResearchAgent","message":"search failed for 'BYJU'S funding': timeout","attempt":1}
{"timestamp":"2026-07-16T05:12:45","event_type":"decision","agent":"Supervisor","message":"Citation coverage 94%; 2 uncited claim(s) flagged"}
{"timestamp":"2026-07-16T05:12:45","event_type":"decision","agent":"Supervisor","message":"Run finished with status=completed_with_partial_failures"}
```

The **Audit Log tab** in the UI shows this live after each run, with color-coded
badges per event type.

---


## 12. UI Pages (`ui/app.py`)

The UI is a 3-page Streamlit app. All pages are gated behind login.

---

### Page 1: 📊 Dashboard

Shows an overview of all past briefing runs.

**KPI cards** (top row):
- Total Runs — count of all runs in history
- Unique Topics — how many distinct topics you've briefed on
- Competitors Tracked — total unique competitors across all runs
- Last Run — date of the most recent run

**Recent Runs table** — last 10 runs with timestamp, topic, competitor list,
and a "View" button that jumps to that run in the History page.

**Last Briefing Preview** — expandable box showing just the Executive Summary
of the most recent run, so you can quickly check what was last found.

---

### Page 2: ✍️ New Briefing

Where you configure and run the pipeline.

**Step 1 — Topic input:**
- Text field: "Market topic" (e.g. "Indian EdTech")
- Max Sources number input (default from `.env`)
- Max Steps number input (default from `.env`)

**Step 2 — Competitor selection:**
- When topic is typed, auto-suggests competitors from news headlines
- Each suggestion shown as a checkbox with name, domain, confidence %
- Manual add button — type any competitor name and add instantly
- Clear All button
- Load/Save watchlists

**Step 3 — Generate:**
- Button label changes: `"⚡ Generate Report"` if competitors selected,
  `"🕵️ Discover Competitors & Generate Report"` if none selected
- After clicking: live agent status display shows which agent is Working/Done/Queued
- Progress bar advances through the pipeline

**Results (4 tabs):**
1. **📋 Final Briefing** — full Markdown report + export buttons (MD / PDF)
2. **🔍 Research & Analysis** — structured insights with evidence badges
3. **📎 Sources & Citations** — each source with 🟢🟡🔴 trust badge and snippet
4. **🧾 Audit Log** — every event from the run, color-coded by type

**Urgency Triage** — shown above the tabs if any HIGH/MEDIUM items were found.
**Trend Memory diff** — shown if this topic+competitors was run before.

---

### Page 3: 📚 History

Browse all past runs.

- Shows count: "27 total runs"
- Search/filter box by topic or competitor name
- Each run: timestamp, topic, competitors, "View" button
- Click View → expands full report inline
- Diff expander shows changes vs previous run for same topic
- Download Markdown button per run

---

## 13. Process Flow (Complete)

```
USER INPUT: topic="Indian EdTech", competitors=[] (none given)
                    │
                    ▼
            crew.py: run_briefing()
            ┌─────────────────────────────┐
            │ run_id = "abc123def456"      │
            │ AuditLogger created          │
            │ SearchBudget: 40 src, 60 steps│
            └─────────────────────────────┘
                    │
                    ▼  (competitors empty → Discovery runs)
            ┌─────────────────────────────────────────────────┐
            │ DISCOVERY AGENT                                  │
            │ Query: "Indian EdTech top companies 2026"        │
            │ Query: "Indian EdTech competitors"               │
            │ → Finds: BYJU'S [1], Unacademy [2], PW [1,3]   │
            │ → Budget: 3 steps used, 12 sources collected     │
            └─────────────────────────────────────────────────┘
                    │
                    ▼
            ┌─────────────────────────────────────────────────┐
            │ RESEARCH AGENT                                   │
            │ Query: "BYJU'S pricing 2026"     → 5 sources    │
            │ Query: "Unacademy product 2026"  → 4 sources    │
            │ Query: "PhysicsWallah funding"   → 5 sources    │
            │ → Budget: 6 more steps, 14 more sources         │
            │ → Total so far: 9 steps, 26 sources             │
            └─────────────────────────────────────────────────┘
                    │
                    ▼
            ┌─────────────────────────────────────────────────┐
            │ ANALYST AGENT  (no web calls)                   │
            │ Deduplicates 18 findings → 14 unique            │
            │ Labels 2 claims "Needs Verification"             │
            │ Tags: 8 corroborated, 6 single-source           │
            └─────────────────────────────────────────────────┘
                    │
                    ▼
            ┌─────────────────────────────────────────────────┐
            │ WRITER AGENT  (no web calls)                    │
            │ Writes 5-section Markdown report                 │
            │ 47 citation tags [id] inserted                   │
            │ Sources & Citations list built from Source Index │
            └─────────────────────────────────────────────────┘
                    │
                    ▼
            POST-RUN GOVERNANCE (Supervisor)
            ├── CitationGuard → 94% coverage → status: completed_with_partial_failures
            ├── TrendMemory  → saved to briefing_history.json
            └── AuditLogger  → run finished, .jsonl closed
                    │
                    ▼
            Briefing object returned to UI
            UI runs UrgencyTriage → 2 HIGH items found
            UI runs TrendMemory diff → "first run for this topic"
            UI renders 4 result tabs
```

---

## 14. Output Report Format

```markdown
## Executive Summary
BYJU'S reduced subscription price by 30% for Tier-2 cities [1].
Unacademy launched a dedicated UPSC preparation module [2, 3].

## Competitor Pricing & Product Moves
- **BYJU'S**: Reduced subscription from ₹2,999/month to ₹1,999/month for 
  cities outside top 8 metros [1].
- **Unacademy**: New UPSC live-class module includes 200+ hours of content [2].

## Market Signals
- Indian EdTech market expected to reach $10B by 2027 [4].
- PhysicsWallah raised Series B at $2.8B valuation [5].

## Strategic Recommendations
- Monitor BYJU'S price cuts in Tier-2 — indicates margin pressure [1].
- Consider partnering with regional coaching institutes given PW's Tier-2 push [5].

## Sources & Citations
[1] BYJU'S Price Cut News — https://economictimes.com/byjus-price-2026
[2] Unacademy UPSC Module Launch — https://techcrunch.com/unacademy-upsc
[3] Unacademy Q2 Product Update — https://inc42.com/unacademy-q2
[4] India EdTech Market Report — https://statista.com/india-edtech
[5] PhysicsWallah Series B — https://crunchbase.com/pw-seriesb

## Run Metadata
| Run ID | abc123def456 |
| Status | completed_with_partial_failures |
| Execution time | 87.3s |
| Searches | 9 |
| Sources | 26 |
| Citation coverage | 94% |
```

---

## 15. Testing

### Unit + Integration Tests (`tests/test_scenarios.py`)
Tests the offline pipeline (no LLM, no network):
- Citation guard catches uncited claims
- Injection guard blocks prompt-injection patterns
- Evidence strength logic (confirmed vs single_source vs needs_verification)
- Duplicate finding removal
- Trend memory diff generation

### Playwright E2E Tests (`tests/test_login_playwright.py`)
Automates a real browser against the running app. 11 tests:

| Test Class | Tests |
|---|---|
| `TestLoginPage` | Form renders, fields present, branding visible |
| `TestLoginFailure` | Wrong password shows error, dashboard stays hidden |
| `TestLoginSuccess` | Sidebar appears, nav buttons present, logout button shown |
| `TestLogout` | Returns to login form, dashboard no longer accessible |

Run:
```bash
playwright install chromium
pytest tests/test_login_playwright.py --headed   # visible browser
pytest tests/test_login_playwright.py            # headless (CI)
```

---

## 16. Running the App

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy config
copy .env.example .env
# Edit .env: set OPENROUTER_API_KEY at minimum

# 3. Run the UI
streamlit run ui/app.py --server.port 8502

# 4. Login
#    Username: admin
#    Password: admin123
#    (or register a new account)

# 5. CLI mode (no UI)
python main.py --topic "Indian EdTech" --competitors "BYJU'S,Unacademy,PhysicsWallah"
python main.py --topic "Indian EdTech" --competitors "BYJU'S,Unacademy" --pdf
```

---

## 17. Key Design Decisions

| Decision | Reason |
|---|---|
| Sequential agent pipeline | Each agent builds on the previous one's output; parallel would lose the source index chain |
| Shared SearchBudget object | Enforces cost limits across all agents — not just per-agent |
| Citation-first design | Every fact must trace to a real URL — no hallucinations published |
| Discovery Agent optional | If you know competitors, skip it; if not, the crew finds them with evidence |
| Rule-based Urgency Triage | Faster and more predictable than asking an LLM to flag important items |
| Local file storage | Zero database setup — runs on any machine, all data in `/data` folder |
| Injection guard on web content | Fetched web pages are untrusted input and could hijack agent behavior |
| Offline pipeline for tests | Governance logic testable without API keys or network access |
| bcrypt for passwords | Industry-standard hashing — plain text never stored anywhere |
