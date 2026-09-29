"""PDF export for CI Copilot briefings using reportlab.

Generates professional dark-themed PDFs from briefing data.
"""
from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ── Color palette ─────────────────────────────────────────────────────────────
BG_DARK = colors.HexColor("#08111F")
CARD_BG = colors.HexColor("#0F172A")
PRIMARY = colors.HexColor("#00E5FF")
ACCENT = colors.HexColor("#4ADE80")
WARNING = colors.HexColor("#F59E0B")
DANGER = colors.HexColor("#EF4444")
TEXT_WHITE = colors.HexColor("#E2E8F0")
TEXT_MUTED = colors.HexColor("#94A3B8")
BORDER = colors.HexColor("#1E3A5F")


def _styles():
    """Build a set of custom styles for the CI Copilot PDF."""
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CITitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=PRIMARY,
        spaceAfter=6,
        alignment=TA_CENTER,
    )

    subtitle_style = ParagraphStyle(
        "CISubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        textColor=TEXT_MUTED,
        spaceAfter=4,
        alignment=TA_CENTER,
    )

    h1_style = ParagraphStyle(
        "CIH1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=PRIMARY,
        spaceBefore=12,
        spaceAfter=6,
        borderPad=4,
    )

    h2_style = ParagraphStyle(
        "CIH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=ACCENT,
        spaceBefore=8,
        spaceAfter=4,
    )

    body_style = ParagraphStyle(
        "CIBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=TEXT_WHITE,
        leading=16,
        spaceAfter=4,
    )

    bullet_style = ParagraphStyle(
        "CIBullet",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=TEXT_WHITE,
        leading=14,
        leftIndent=16,
        spaceAfter=2,
        bulletIndent=8,
    )

    caption_style = ParagraphStyle(
        "CICaption",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        textColor=TEXT_MUTED,
        spaceAfter=2,
    )

    return {
        "title": title_style,
        "subtitle": subtitle_style,
        "h1": h1_style,
        "h2": h2_style,
        "body": body_style,
        "bullet": bullet_style,
        "caption": caption_style,
    }


def generate_pdf_bytes(briefing_data: dict[str, Any]) -> bytes:
    """Generate a professional PDF from a briefing data dict."""
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = _styles()
    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    topic = briefing_data.get("topic", "Competitive Intelligence")
    competitors = briefing_data.get("competitors", [])
    metadata = briefing_data.get("metadata", {})
    run_id = metadata.get("run_id", "")
    started_at = metadata.get("started_at", "")[:10] if metadata.get("started_at") else ""
    status = metadata.get("status", "completed")

    story.append(Paragraph("🧠 CI Copilot — Memory-First Intelligence", styles["title"]))
    story.append(Paragraph(f"Weekly Briefing: {topic}", styles["subtitle"]))
    story.append(Paragraph(
        f"Generated: {started_at} | Run ID: {run_id} | Status: {status.upper()}",
        styles["caption"]
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceAfter=8))

    # ── Competitors tracked ────────────────────────────────────────────────────
    if competitors:
        story.append(Paragraph("Competitors Analyzed", styles["h2"]))
        comp_str = " • ".join(competitors)
        story.append(Paragraph(comp_str, styles["body"]))
        story.append(Spacer(1, 4 * mm))

    # ── Memory Stats ──────────────────────────────────────────────────────────
    memory_events = metadata.get("execution_steps", 0)
    story.append(Paragraph("Memory Intelligence", styles["h2"]))
    story.append(Paragraph(
        f"This briefing leverages persistent Hindsight memory with "
        f"{memory_events} tracked audit events. Memory enables pattern "
        f"recognition across 6+ months of competitor activity.",
        styles["body"]
    ))
    story.append(Spacer(1, 4 * mm))

    # ── Main sections from markdown ───────────────────────────────────────────
    markdown = briefing_data.get("markdown", "")

    sections = [
        ("Executive Summary", briefing_data.get("executive_summary", "")),
        ("Competitor Moves", briefing_data.get("pricing_and_product_moves", "")),
        ("Market Signals", briefing_data.get("market_signals", "")),
        ("Strategic Recommendations", briefing_data.get("strategic_recommendations", "")),
    ]

    for section_title, content in sections:
        if not content:
            # Try to extract from full markdown
            content = _extract_section_from_markdown(markdown, section_title)

        if content:
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=8))
            story.append(Paragraph(section_title, styles["h1"]))

            for line in content.split("\n"):
                line = line.strip()
                if not line:
                    story.append(Spacer(1, 2 * mm))
                    continue
                if line.startswith("### "):
                    story.append(Paragraph(line[4:], styles["h2"]))
                elif line.startswith("## "):
                    story.append(Paragraph(line[3:], styles["h1"]))
                elif line.startswith("- ") or line.startswith("• "):
                    text = _clean_md(line[2:])
                    story.append(Paragraph(f"• {text}", styles["bullet"]))
                elif line.startswith("**") and line.endswith("**"):
                    story.append(Paragraph(_clean_md(line), styles["h2"]))
                else:
                    story.append(Paragraph(_clean_md(line), styles["body"]))

    # ── Sources ───────────────────────────────────────────────────────────────
    sources = briefing_data.get("sources", [])
    if sources:
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=8))
        story.append(Paragraph("Sources & Citations", styles["h1"]))
        for src in sources[:20]:
            if isinstance(src, dict):
                title = src.get("title", "")
                url = src.get("url", "")
                sid = src.get("id", "")
                story.append(Paragraph(
                    f"[{sid}] {title} — {url}",
                    styles["bullet"]
                ))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=PRIMARY))
    story.append(Paragraph(
        "Generated by CI Copilot v2.0 — Memory-First Competitive Intelligence",
        styles["caption"]
    ))

    doc.build(story)
    return buffer.getvalue()


def _extract_section_from_markdown(markdown: str, heading: str) -> str:
    lines = markdown.split("\n")
    out, capture = [], False
    for line in lines:
        if line.strip().startswith("##") and heading in line:
            capture = True
            continue
        if capture and line.strip().startswith("##"):
            break
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def _clean_md(text: str) -> str:
    """Remove basic Markdown formatting for plain text."""
    import re
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # Inline code
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Links
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    # Citations [1], [1,2]
    text = re.sub(r"\[[\d,\s]+\]", "", text)
    return text.strip()
