"""Render — turn an ApplicationDraft into Markdown / HTML (ARCHITECTURE §5, Stage 9).

Deterministic, no LLM. Markdown is the canonical human-readable form; HTML is a minimal,
self-contained wrapper (no external deps). PDF is intentionally left out (optional/later).
"""
from __future__ import annotations

import html as _html

from src.models import ApplicationDraft


def render_markdown(draft: ApplicationDraft) -> str:
    parts = []
    if draft.cv_markdown:
        parts.append(draft.cv_markdown.strip())
    if draft.highlighted_skills:
        parts.append("## Highlighted skills\n\n" + ", ".join(draft.highlighted_skills))
    if draft.cover_letter:
        parts.append("## Cover letter\n\n" + draft.cover_letter.strip())
    return "\n\n".join(parts) + "\n"


def render_html(draft: ApplicationDraft) -> str:
    body = _html.escape(render_markdown(draft))
    return (
        "<!doctype html>\n<html><head><meta charset='utf-8'>"
        "<title>Tailored application</title></head><body>\n"
        f"<pre>{body}</pre>\n</body></html>\n"
    )
