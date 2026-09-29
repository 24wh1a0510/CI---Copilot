"""Pre-captured research results used for offline testing, DeepEval, and the
Streamlit UI's demo mode — lets the full Analyst -> Writer -> Governance pipeline
run deterministically without any API keys or network access."""
from __future__ import annotations

from models.schemas import Source, SourceStatus

SAMPLE_TOPIC = "Cloud Data Warehousing"
SAMPLE_COMPETITORS = ["Snowflake", "Databricks", "BigQuery"]

SAMPLE_SOURCES: list[Source] = [
    Source(id=1, url="https://www.snowflake.com/en/news/press-releases/pricing-update-2026/",
           title="Snowflake Announces Consumption Pricing Update", domain="snowflake.com",
           query="Snowflake pricing changes 2026", status=SourceStatus.OK,
           snippet="Snowflake reduced standard-tier compute pricing by 8% for new contracts starting Q2 2026."),
    Source(id=2, url="https://techcrunch.com/2026/03/databricks-lakebase-launch/",
           title="Databricks launches Lakebase, a transactional database layer", domain="techcrunch.com",
           query="Databricks product launch 2026", status=SourceStatus.OK,
           snippet="Databricks unveiled Lakebase, aiming to unify transactional and analytical workloads on one platform."),
    Source(id=3, url="https://cloud.google.com/blog/products/data-analytics/bigquery-2026-roadmap",
           title="BigQuery 2026 roadmap", domain="cloud.google.com", query="BigQuery roadmap 2026",
           status=SourceStatus.OK,
           snippet="Google announced deeper Gemini integration in BigQuery, including natural-language query generation."),
    Source(id=4, url="https://www.reuters.com/technology/snowflake-databricks-competition-2026",
           title="Snowflake and Databricks battle for AI workloads", domain="reuters.com",
           query="Snowflake Databricks competition", status=SourceStatus.OK,
           snippet="Analysts note both vendors are converging on similar AI/ML feature sets, intensifying price competition."),
    Source(id=5, url="https://sec.gov/example/some-flaky-filing-endpoint", title="",
           domain="sec.gov", query="Databricks funding round", status=SourceStatus.TIMEOUT,
           snippet=""),
    Source(id=6, url="https://random-blog.example/databricks-going-bankrupt-rumor",
           title="Is Databricks in trouble?", domain="random-blog.example",
           query="Databricks financial trouble", status=SourceStatus.OK,
           snippet="Anonymous forum poster speculates Databricks is 'running out of cash' with no supporting evidence."),
]

SAMPLE_RESEARCH_FINDINGS = [
    {"competitor": "Snowflake", "category": "pricing",
     "statement": "Snowflake cut standard-tier compute pricing 8% for new Q2 2026 contracts.",
     "source_ids": [1]},
    {"competitor": "Databricks", "category": "product",
     "statement": "Databricks launched Lakebase, a transactional database layer on its lakehouse.",
     "source_ids": [2]},
    {"competitor": "BigQuery", "category": "product",
     "statement": "Google added deeper Gemini integration to BigQuery, including natural-language querying.",
     "source_ids": [3]},
    {"competitor": "Snowflake", "category": "market_trend",
     "statement": "Snowflake and Databricks are converging on similar AI/ML features, intensifying price competition.",
     "source_ids": [4]},
    {"competitor": "Databricks", "category": "funding",
     "statement": "Databricks funding filing lookup failed (source timed out).",
     "source_ids": [5]},
    {"competitor": "Databricks", "category": "market_trend",
     "statement": "An anonymous blog claims Databricks is 'going bankrupt' with no corroboration.",
     "source_ids": [6]},
]
