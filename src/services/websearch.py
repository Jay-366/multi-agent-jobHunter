"""Web search (read-only) — Tavily backend with graceful degradation.

One function, `web_search(query)`, returns a typed `WebSearchResult`. If no `TAVILY_API_KEY`
is configured (or the call fails), it returns `available=False` with empty results instead
of raising — so callers (the company-brief tool) degrade to JD-only judgement rather than
crashing, and unit tests stay offline until a key is present.

Injectable: pass `post=` (a requests.post-shaped callable) to test without the network.
"""
from __future__ import annotations

from typing import Callable, Optional

from pydantic import BaseModel

TAVILY_URL = "https://api.tavily.com/search"


class SearchHit(BaseModel):
    title: str = ""
    url: str = ""
    content: str = ""


class WebSearchResult(BaseModel):
    query: str
    answer: str = ""              # Tavily's synthesized answer (if include_answer)
    results: list[SearchHit] = []
    available: bool = False       # did a real search backend actually run?
    error: str = ""               # populated when a configured search failed


def web_search(
    query: str,
    *,
    api_key: Optional[str] = None,
    max_results: Optional[int] = None,
    search_depth: Optional[str] = None,
    timeout: Optional[int] = None,
    post: Optional[Callable] = None,
) -> WebSearchResult:
    """Search the web via Tavily. Reads config/env defaults when args are omitted.

    Returns available=False (no error) when unconfigured, so this is safe to call anywhere.
    """
    cfg = _config()
    if api_key is None:
        api_key = cfg["api_key"]
    if not api_key:
        return WebSearchResult(query=query, available=False)

    max_results = max_results or cfg["max_results"]
    search_depth = search_depth or cfg["search_depth"]
    timeout = timeout or cfg["timeout"]

    payload = {
        "api_key": api_key,          # Tavily REST accepts the key in the body
        "query": query,
        "search_depth": search_depth,
        "include_answer": True,
        "max_results": max_results,
    }
    try:
        if post is None:
            import requests  # lazy: only needed for a real call
            post = requests.post
        resp = post(TAVILY_URL, json=payload, timeout=timeout,
                    headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # network/HTTP/JSON — degrade, never crash the agent loop
        return WebSearchResult(query=query, available=False, error=f"{type(e).__name__}: {e}")

    hits = [
        SearchHit(title=r.get("title", ""), url=r.get("url", ""), content=r.get("content", ""))
        for r in (data.get("results") or [])
    ]
    return WebSearchResult(
        query=query,
        answer=(data.get("answer") or "").strip(),
        results=hits,
        available=True,
    )


def _config() -> dict:
    """Pull websearch settings + key from central config; fall back to safe defaults."""
    try:
        from src.config import settings
        ws = settings.websearch()
        return {
            "api_key": settings.tavily_api_key,
            "max_results": int(ws.get("max_results", 5)),
            "search_depth": str(ws.get("search_depth", "basic")),
            "timeout": int(ws.get("timeout", 15)),
        }
    except Exception:
        return {"api_key": "", "max_results": 5, "search_depth": "basic", "timeout": 15}
