"""fetch_company_brief — a short read-only brief about a company, backed by web search.

Uses the Tavily-backed `web_search` service to gather a legitimacy/reputation signal the
analyst can weigh. When no `TAVILY_API_KEY` is configured (or a search fails), it degrades
to a neutral 'unknown' brief so the agent judges legitimacy from the JD alone — never
crashing and never writing anything.
"""
from __future__ import annotations

from typing import Callable, Optional

from pydantic import BaseModel


class CompanyBrief(BaseModel):
    name: str
    summary: str
    known: bool                 # did we get real web info?
    sources: list[str] = []     # URLs backing the summary (for the analyst's evidence)


def _company_query(name: str) -> str:
    return (f'"{name}" company Malaysia — official website, what they do, reputation, '
            "legitimacy, reviews, scam reports")


def _summarize(res, name: str) -> CompanyBrief:
    # Prefer Tavily's synthesized answer; else stitch the top result snippets.
    answer = (res.answer or "").strip()
    if not answer and res.results:
        answer = " • ".join(h.content.strip() for h in res.results[:3] if h.content.strip())
    answer = answer[:600].strip()
    if not answer:
        return _unknown(name)
    return CompanyBrief(
        name=name, summary=answer, known=True,
        sources=[h.url for h in res.results[:3] if h.url],
    )


def _unknown(name: str) -> CompanyBrief:
    return CompanyBrief(
        name=name,
        summary=f"No web enrichment available; treat '{name}' as unknown and judge "
                "legitimacy from the JD text alone.",
        known=False,
    )


class FetchCompanyBriefTool:
    name = "fetch_company_brief"
    description = ("Search the web for a short brief about a company — what they do, "
                  "reputation, and legitimacy signals (scam/ghost-job red flags).")
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Company name"}},
        "required": ["name"],
    }

    def __init__(self, search_fn: Optional[Callable] = None):
        # search_fn(query:str) -> WebSearchResult. Injectable for tests; defaults to Tavily.
        self._search_fn = search_fn

    def run(self, name: str) -> CompanyBrief:
        name = (name or "").strip()
        if not name:
            return _unknown(name)
        search = self._search_fn
        if search is None:
            from src.services.websearch import web_search
            search = web_search
        try:
            res = search(_company_query(name))
        except Exception:  # a flaky backend must not break the ReAct loop
            return _unknown(name)
        if not getattr(res, "available", False):
            return _unknown(name)
        return _summarize(res, name)
