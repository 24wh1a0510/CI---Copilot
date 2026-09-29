"""Bounded, fault-tolerant web-search tool used by the Research Agent.

Wraps Tavily (preferred) or Serper. Every call is:
  - time-limited (SEARCH_TIMEOUT_SECONDS)
  - retried up to MAX_RETRIES_PER_TOOL_CALL times with backoff
  - capped globally by MAX_SOURCES (enforced by the Supervisor via SearchBudget)
  - logged to the AuditLogger regardless of outcome (never fails silently)
"""
from __future__ import annotations

from urllib.parse import urlparse

from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, Field

from config.settings import settings
from logging_.audit_logger import AuditLogger
from models.schemas import Source, SourceStatus

try:
    from crewai.tools import BaseTool
except ImportError:  # crewai is an optional heavy dependency; offline tests/governance
    # code (SearchBudget, injection/citation guards) must work without it installed.
    class BaseTool:  # type: ignore[no-redef]
        name: str = ""
        description: str = ""
        args_schema: type | None = None

        def _run(self, *args, **kwargs):
            raise NotImplementedError


class SearchBudget:
    """Shared, mutable budget object the Supervisor hands to the Research Agent so the
    MAX_SOURCES / MAX_STEPS limits are enforced across the whole crew, not per-call."""

    def __init__(self, max_sources: int | None = None, max_steps: int | None = None):
        self.max_sources = max_sources or settings.max_sources
        self.max_steps = max_steps or settings.max_steps
        self.sources_collected = 0
        self.steps_taken = 0
        self.limit_hit = False

    def can_search(self) -> bool:
        return self.sources_collected < self.max_sources and self.steps_taken < self.max_steps

    def register_step(self):
        self.steps_taken += 1

    def register_sources(self, n: int):
        self.sources_collected += n


class BoundedSearchInput(BaseModel):
    query: str = Field(..., description="Search query, e.g. 'Snowflake pricing changes 2026'")


class BoundedWebSearchTool(BaseTool):
    """CrewAI tool: searches the web but refuses once the run's search budget is spent,
    and never raises — failed/timed-out sources are logged and skipped."""

    name: str = "bounded_web_search"
    description: str = (
        "Search the web for competitor news, pricing, product launches, funding, and "
        "market signals. Input: a focused query string. Returns a list of sources with "
        "url, title, and snippet. Automatically stops once the run's source/step budget "
        "is exhausted."
    )
    args_schema: type[BaseModel] = BoundedSearchInput

    budget: SearchBudget
    audit: AuditLogger
    collected_sources: list = []   # shared registry — populated during run, read by crew.py

    class Config:
        arbitrary_types_allowed = True

    def _run(self, query: str) -> str:
        if not self.budget.can_search():
            self.budget.limit_hit = True
            self.audit.limit_reached("ResearchAgent", "max_sources or max_steps")
            return "SEARCH_BUDGET_EXHAUSTED: stop searching and proceed with what you have."

        self.budget.register_step()
        results = self._search_with_retry(query)

        next_id = len(self.collected_sources) + 1
        accepted: list[Source] = []
        for r in results:
            if self.budget.sources_collected + len(accepted) >= self.budget.max_sources:
                break
            url = r.get("url", "") or r.get("href", "") or ""
            if not url or not url.startswith("http"):
                continue   # never accept a source without a real URL
            src = Source(
                id=next_id + len(accepted),
                url=url,
                title=r.get("title", ""),
                domain=urlparse(url).netloc,
                query=query,
                status=SourceStatus.OK,
                snippet=(r.get("content") or r.get("snippet") or "")[:500],
            )
            accepted.append(src)

        # Stretch 4: annotate sources with trust tier
        try:
            from tools.trust_scorer import annotate_sources
            accepted = annotate_sources(accepted)
            for src in accepted:
                if src.trust_tier == "low":
                    self.audit.decision(
                        "ResearchAgent",
                        f"Low-trust source included: {src.domain} ({src.trust_reason})",
                    )
        except Exception:
            pass

        self.collected_sources.extend(accepted)
        self.budget.register_sources(len(accepted))
        self.audit.tool_call(
            "ResearchAgent", "bounded_web_search", {"query": query}, ok=True,
            note=f"{len(accepted)} sources"
        )

        if not accepted:
            self.audit.failure("ResearchAgent", f"No usable results for query: {query}")
            return f"No reachable sources found for '{query}'. Skipping and continuing."

        # Return format: structured so the Researcher can copy the Source Index directly.
        # Each source block: [id] title | URL on first line, then snippet.
        lines = [
            f"[{s.id}] {s.title} | {s.url}\nSnippet: {s.snippet}"
            for s in accepted
        ]
        return "\n\n".join(lines)

    @retry(stop=stop_after_attempt(settings.max_retries_per_tool_call + 1),
           wait=wait_exponential(multiplier=1, min=1, max=6))
    def _search_with_retry(self, query: str) -> list[dict]:
        try:
            return self._do_search(query)
        except Exception as e:
            self.audit.retry("ResearchAgent", f"search failed for '{query}': {e}", attempt=1)
            raise

    def _do_search(self, query: str) -> list[dict]:
        # 1. Tavily — best quality, requires real API key
        if settings._tavily_key:
            from tavily import TavilyClient
            client = TavilyClient(api_key=settings._tavily_key)
            resp = client.search(query, max_results=5, search_depth="basic",
                                  timeout=settings.search_timeout_seconds)
            return resp.get("results", [])

        # 2. Serper — good quality, requires real API key
        if settings._serper_key:
            import requests
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": settings._serper_key, "Content-Type": "application/json"},
                json={"q": query},
                timeout=settings.search_timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"url": r.get("link"), "title": r.get("title"), "content": r.get("snippet")}
                for r in data.get("organic", [])
            ]

        # 3. DuckDuckGo — free, no API key needed, automatic fallback
        if settings.use_duckduckgo:
            try:
                from ddgs import DDGS  # pip install ddgs (renamed from duckduckgo_search)
            except ImportError:
                from duckduckgo_search import DDGS  # legacy fallback
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    results.append({
                        "url": r.get("href", ""),
                        "title": r.get("title", ""),
                        "content": r.get("body", ""),
                    })
            return results

        raise RuntimeError(
            "No search provider configured. Set TAVILY_API_KEY, SERPER_API_KEY, "
            "or USE_DUCKDUCKGO=true in .env"
        )
