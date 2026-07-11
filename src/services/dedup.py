"""Cross-source de-duplication (ARCHITECTURE §5).

The same role often appears on more than one board (or twice on one). We collapse by
two independent keys: a normalized (title, company) pair, and the exact URL. First
occurrence wins; order is otherwise preserved. Pure function — no network, no LLM.
"""
from __future__ import annotations

import re

from src.models import JobPosting

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _norm(s: str) -> str:
    """lowercase, drop punctuation, collapse whitespace."""
    s = (s or "").lower()
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def dedup(postings: list[JobPosting]) -> list[JobPosting]:
    seen_pairs: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    out: list[JobPosting] = []
    for p in postings:
        pair = (_norm(p.title), _norm(p.company))
        if pair in seen_pairs or (p.url and p.url in seen_urls):
            continue
        seen_pairs.add(pair)
        if p.url:
            seen_urls.add(p.url)
        out.append(p)
    return out
