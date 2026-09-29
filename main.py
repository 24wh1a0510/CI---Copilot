"""CLI entrypoint: python main.py --topic "..." --competitors "A,B,C" --max-sources 15 --max-steps 20"""
from __future__ import annotations

import argparse

from crew import run_briefing
from reports.exporter import save_markdown, save_pdf


def main():
    parser = argparse.ArgumentParser(description="Generate a weekly Competitive Intelligence Briefing")
    parser.add_argument("--topic", required=True, help="Market / topic, e.g. 'Cloud Data Warehousing'")
    parser.add_argument("--competitors", required=True, help="Comma-separated competitor names")
    parser.add_argument("--max-sources", type=int, default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--pdf", action="store_true", help="Also export a PDF")
    args = parser.parse_args()

    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]

    briefing = run_briefing(
        topic=args.topic,
        competitors=competitors,
        max_sources=args.max_sources,
        max_steps=args.max_steps,
    )

    md_path = save_markdown(briefing.metadata.run_id, briefing.markdown)
    print(f"\nMarkdown saved to: {md_path}")

    if args.pdf:
        pdf_path = save_pdf(briefing.metadata.run_id, briefing.markdown)
        print(f"PDF saved to: {pdf_path}")

    print(f"\nStatus: {briefing.metadata.status}")
    print(f"Execution time: {briefing.metadata.execution_time_seconds}s")
    print(f"Search count: {briefing.metadata.search_count}")


if __name__ == "__main__":
    main()
