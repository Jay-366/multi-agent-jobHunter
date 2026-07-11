"""Provider protocol — the contract every job source implements (ARCHITECTURE §5, §7).

Add a job source = add one file here that satisfies this Protocol. No orchestration,
agent, or discovery change is needed. Providers are deterministic (no LLM) and read-only.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.models import JobPosting, SearchTarget


@runtime_checkable
class Provider(Protocol):
    id: str

    def search(self, target: SearchTarget) -> list[JobPosting]:
        """Return postings matching `target`. Must not raise on empty results — return []."""
        ...

    def fetch_detail(self, posting: JobPosting) -> str:
        """Return the full JD text for one posting (empty string if unavailable)."""
        ...
