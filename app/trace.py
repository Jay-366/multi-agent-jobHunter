"""Render agent-activity events as Markdown for the Hunt page's live feed.

Pure (no Streamlit), so the formatting is unit-testable. The page feeds each progress item
through `event_markdown()` and writes the result into an `st.status` container, producing a
Claude/OpenAI-style trace: bold phase headers, grey *thinking* blockquotes, monospace tool
calls, and ✅/⚠️ results. Plain strings (legacy sinks) pass through untouched.
"""
from __future__ import annotations

from src.events import AgentEvent

_MAX_OBS = 240  # tool observations can be long JSON; keep the feed readable


def event_markdown(item) -> str:
    """Turn one progress item (AgentEvent or str) into a Markdown line for the feed."""
    if not isinstance(item, AgentEvent):
        return str(item)

    who = item.agent
    step = f" · step {item.step}" if item.step else ""
    text = item.text

    if item.kind == "reasoning_delta":
        # Live-streamed reasoning is normally coalesced into one updating block by the page;
        # this fallback keeps it readable if rendered as a standalone line.
        return f"> 🧠 {text}"
    if item.kind == "job":
        return f"\n**📋 {text}**"
    if item.kind == "phase":
        return f"**⚙️ {who}{step}** — {text}"
    if item.kind == "thought":
        return f"> 🧠 *{who}{step} is thinking:* {text}"
    if item.kind == "tool":
        return f"&nbsp;&nbsp;🔧 `{who} → {text}`"
    if item.kind == "observation":
        clipped = text if len(text) <= _MAX_OBS else text[:_MAX_OBS] + "…"
        return f"&nbsp;&nbsp;↳ _{clipped}_"
    if item.kind == "result":
        return f"✅ {text}"
    if item.kind == "error":
        return f"⚠️ **{who}:** {text}"
    return f"ℹ️ {text}"
