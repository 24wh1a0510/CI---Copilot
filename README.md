# Competitive Intelligence Briefing Crew

A production-ready **multi-agent AI system** built with **CrewAI** that automatically
generates a cited, governed, weekly **Competitive Intelligence Briefing** for a VP of
Strategy — researching competitors, analyzing market signals, and producing a
professional Markdown/PDF report.

> This is **not a chatbot**. It is a supervised pipeline of specialized agents:
>
> **User → Supervisor Agent → Research Agent → Analyst Agent → Writer Agent → Final Briefing**

---

## Architecture

```
User Request
     │
     ▼
┌─────────────────┐   enforces limits, retries, audit trail
│ Supervisor Agent │──────────────────────────────────────────┐
└─────────────────┘                                           │
     │ delegates                                              │
     ▼                                                        │
┌─────────────────┐  web search (Tavily/Serper)                │
│  Research Agent  │──► collects URLs + metadata               │
└─────────────────┘  skips/logs failed sources                 │
     │                                                        │
     ▼                                                        │
┌─────────────────┐  dedupes, compares competitors,            │
│  Analyst Agent    │  flags weak evidence "Needs Verification" │
└─────────────────┘                                           │
     │                                                        │
     ▼                                                        │
┌─────────────────┐  Executive Summary, Pricing/Product Moves, │
│  Writer Agent     │  Market Signals, Recommendations,        │
└─────────────────┘  Sources, Run Metadata                     │
     │                                                        │
     ▼                                                        │
Final Weekly Briefing (Markdown + PDF) ◄────────── Audit log ──┘
```

## Project Layout

```
ci-briefing-crew/
├── agents/            # Supervisor, Research, Analyst, Writer (CrewAI Agents + Tasks)
├── tools/              # Web search tool wrapper (Tavily/Serper) with failure handling
├── models/             # Pydantic schemas for every inter-agent artifact
├── governance/         # Citation enforcement, hallucination checks, injection guard
├── evaluation/         # DeepEval + pytest suites, sample datasets
├── logging_/            # Structured audit-trail logger
├── reports/             # Markdown -> PDF exporter
├── ui/                  # Premium Streamlit dashboard
├── config/              # Settings (Pydantic BaseSettings) + limits
├── data/                 # Sample competitor / source datasets
├── tests/                 # Required test scenarios (pytest)
├── crew.py                # Wires agents+tasks into the CrewAI Crew
├── main.py                 # CLI entrypoint
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY / OPENROUTER_API_KEY and TAVILY_API_KEY
```

## Run

CLI:
```bash
python main.py --topic "Cloud Data Warehousing" --competitors "Snowflake,Databricks,BigQuery" --max-sources 15 --max-steps 20
```

Dashboard:
```bash
streamlit run ui/app.py
```

## Evaluation

```bash
pytest tests/ -v
python evaluation/run_deepeval.py
```

## Governance Guarantees

- Every claim in the final report must carry a citation `[n]` resolving to a source in
  the Sources section, enforced by `governance/citation_guard.py`.
- Claims that cannot be traced to at least one retrieved source are either dropped or
  rewritten and tagged **"Needs Verification"** by the Analyst Agent, and re-checked by
  the governance layer before the Writer Agent is allowed to publish them.
- All tool calls, retries, failures, and agent decisions are appended to an immutable
  JSONL audit log (`logging_/audit_logger.py`), one file per run, surfaced live in the UI.
- Supervisor enforces `MAX_SOURCES` and `MAX_STEPS` (config/settings.py) and stops the
  crew cleanly (not a crash) when reached, returning a partial-but-valid briefing.
- A prompt-injection guard (`governance/injection_guard.py`) strips/quarantines
  instruction-like content found inside fetched web pages before it reaches the LLM.

## Notes on API keys

This project requires your own `OPENAI_API_KEY` (or `OPENROUTER_API_KEY`) and
`TAVILY_API_KEY` (or `SERPER_API_KEY`) — no keys are bundled. Without network access /
keys, `evaluation/sample_data/` lets you run the Analyst+Writer+governance+UI pipeline
fully offline against pre-captured research results, so you can validate the whole
system end-to-end before spending API credits.
