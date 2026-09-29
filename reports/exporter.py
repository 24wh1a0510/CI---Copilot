"""Exports a Briefing's markdown to a standalone .md file and a styled PDF."""
from __future__ import annotations

from pathlib import Path

import markdown2

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_PDF_CSS = """
@page { margin: 2.2cm; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #1a1a2e; font-size: 11pt; line-height: 1.55; }
h1 { color: #4338ca; border-bottom: 3px solid #7c3aed; padding-bottom: 8px; }
h2 { color: #5b21b6; margin-top: 28px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #ddd; padding: 6px 10px; font-size: 9.5pt; }
th { background: #ede9fe; }
code { background: #f3f4f6; padding: 1px 4px; border-radius: 3px; }
a { color: #6d28d9; }
"""


def save_markdown(run_id: str, markdown_text: str) -> Path:
    path = OUTPUT_DIR / f"{run_id}.md"
    path.write_text(markdown_text, encoding="utf-8")
    return path


def save_pdf(run_id: str, markdown_text: str) -> Path | None:
    html_body = markdown2.markdown(markdown_text, extras=["tables", "fenced-code-blocks"])
    html = f"<html><head><meta charset='utf-8'><style>{_PDF_CSS}</style></head><body>{html_body}</body></html>"
    path = OUTPUT_DIR / f"{run_id}.pdf"
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(path))
        return path
    except Exception:
        # WeasyPrint has native deps (Pango/Cairo) that may be unavailable in some
        # environments; fall back to reportlab-based plain PDF so export never hard-fails.
        return _fallback_pdf(run_id, markdown_text)


def _fallback_pdf(run_id: str, markdown_text: str) -> Path:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    path = OUTPUT_DIR / f"{run_id}.pdf"
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    x, y = 0.9 * inch, height - 0.9 * inch
    c.setFont("Helvetica", 10)
    for raw_line in markdown_text.split("\n"):
        line = raw_line.rstrip()
        if y < 0.9 * inch:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 0.9 * inch
        c.drawString(x, y, line[:110])
        y -= 13
    c.save()
    return path
