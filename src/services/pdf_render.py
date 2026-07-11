"""PDF render — turn a tailored CV (Markdown) into a clean Harvard-style résumé PDF.

Deterministic, no LLM, no network, no system binaries: pure `reportlab` (Platypus), which
ships as a wheel on Windows. We keep Markdown canonical (`render.py`) and treat the PDF as a
derived, printable view — a line-oriented Markdown subset is enough for a résumé:

    # Name                → centered title
    (first line after)    → centered contact line (email · phone · links)
    ## Section            → bold heading + full-width rule (Education, Experience, …)
    ### Sub-heading       → bold entry line (Role — Company, dates)
    - bullet / * bullet   → hanging bullet
    1. item               → numbered item
    ---                   → horizontal rule
    **bold** *italic*     → inline emphasis; [text](url) → link

Anything unrecognized renders as a normal justified paragraph, so no input is ever lost.
"""
from __future__ import annotations

import html
import io
import re

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus.flowables import HRFlowable

_RULE = HexColor("#8A8A8A")
_INK = HexColor("#222222")
_MUTED = HexColor("#555555")
_LINK = HexColor("#1A4B8C")

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_NUM_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")
_CONTACTISH = re.compile(r"[@|·•]|https?://|\d{3}")


def _inline(text: str) -> str:
    """Convert a Markdown span to reportlab's mini-HTML, escaping first so JD text is safe."""
    text = html.escape(text, quote=False)
    text = _LINK_RE.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" color="#1A4B8C">'
                  f"{m.group(1)}</a>",
        text,
    )
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    return text


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10, leading=13, textColor=_INK)
    return {
        "name": ParagraphStyle("name", parent=base, fontName="Helvetica-Bold",
                               fontSize=20, leading=23, alignment=TA_CENTER, spaceAfter=2),
        "contact": ParagraphStyle("contact", parent=base, fontSize=9.5, leading=12,
                                  alignment=TA_CENTER, textColor=_MUTED, spaceAfter=6),
        "section": ParagraphStyle("section", parent=base, fontName="Helvetica-Bold",
                                  fontSize=11.5, leading=14, spaceBefore=11, spaceAfter=0),
        "subhead": ParagraphStyle("subhead", parent=base, fontName="Helvetica-Bold",
                                  fontSize=10.5, leading=13, spaceBefore=5, spaceAfter=1),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=15, bulletIndent=3,
                                 spaceAfter=2, alignment=TA_JUSTIFY),
        "body": ParagraphStyle("body", parent=base, spaceAfter=3, alignment=TA_JUSTIFY),
    }


def render_resume_pdf(markdown_text: str, *, name: str | None = None,
                      title: str = "Resume") -> bytes:
    """Render a tailored CV Markdown string into Harvard-style PDF bytes.

    `name` is used as the centered title only when the Markdown has no leading `# ` heading,
    so an LLM draft that already opens with the name is never duplicated.
    """
    st = _styles()
    lines = (markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    has_h1 = any(ln.lstrip().startswith("# ") for ln in lines)

    story: list = []
    seen_name = False
    expect_contact = False

    if name and not has_h1:
        story.append(Paragraph(_inline(name), st["name"]))
        seen_name = True
        expect_contact = True

    for raw in lines:
        s = raw.strip()
        if not s:
            expect_contact = False
            if story and not isinstance(story[-1], Spacer):
                story.append(Spacer(1, 4))
            continue

        # Name (first H1 only). A later H1 is demoted to a section heading.
        if s.startswith("# ") and not seen_name:
            story.append(Paragraph(_inline(s[2:].strip()), st["name"]))
            seen_name = True
            expect_contact = True
            continue

        if s.startswith("## ") or s.startswith("# "):
            story.append(Paragraph(_inline(s.lstrip("#").strip().upper()), st["section"]))
            story.append(HRFlowable(width="100%", thickness=0.6, color=_RULE,
                                    spaceBefore=1, spaceAfter=4))
            expect_contact = False
            continue

        if s.startswith("### ") or s.startswith("#### "):
            story.append(Paragraph(_inline(s.lstrip("#").strip()), st["subhead"]))
            expect_contact = False
            continue

        if s[:2] in ("- ", "* ", "+ "):
            story.append(Paragraph(_inline(s[2:].strip()), st["bullet"], bulletText="•"))
            expect_contact = False
            continue

        num = _NUM_RE.match(s)
        if num:
            story.append(Paragraph(_inline(num.group(2)), st["bullet"],
                                   bulletText=f"{num.group(1)}."))
            expect_contact = False
            continue

        if len(s) >= 3 and set(s) <= set("-*_ "):  # a --- / *** rule line
            story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE,
                                    spaceBefore=3, spaceAfter=3))
            continue

        # The line right after the name, if it looks like contact info, is centered + muted.
        if expect_contact and _CONTACTISH.search(s):
            story.append(Paragraph(_inline(s), st["contact"]))
            expect_contact = False
            continue

        story.append(Paragraph(_inline(s), st["body"]))
        expect_contact = False

    if not story:
        story.append(Paragraph("(empty résumé)", st["body"]))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER, title=title,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )
    doc.build(story)
    return buf.getvalue()
