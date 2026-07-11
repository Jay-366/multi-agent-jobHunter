"""search_comp — typical salary band for a role+location (read-only).

Wraps a deterministic comp-lookup. Today it's a small built-in heuristic table (a real
provider — levels.fyi / Glassdoor scrape — can replace the lookup without changing the
tool's schema). Returns a typed CompResult. It NEVER writes anything.
"""
from __future__ import annotations

from pydantic import BaseModel


class CompResult(BaseModel):
    role: str
    location: str
    currency: str
    low: float
    high: float
    period: str  # "month"
    source: str


# Coarse MYR/month bands by seniority keyword — deterministic stand-in for a real service.
_BANDS: list[tuple[tuple[str, ...], float, float]] = [
    (("principal", "staff", "head", "lead"), 15000, 28000),
    (("senior", "sr"), 9000, 16000),
    (("mid", "intermediate"), 6000, 10000),
    (("junior", "graduate", "entry", "intern"), 2500, 6000),
]
_DEFAULT = (5000.0, 9000.0)


def _lookup(role: str, location: str) -> tuple[float, float]:
    r = role.lower()
    for keys, low, high in _BANDS:
        if any(k in r for k in keys):
            return low, high
    return _DEFAULT


class SearchCompTool:
    name = "search_comp"
    description = "Look up a typical monthly salary band (MYR) for a role in a location."
    schema = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "Job title, e.g. 'senior software engineer'"},
            "location": {"type": "string", "description": "City/region, e.g. 'Kuala Lumpur'"},
        },
        "required": ["role", "location"],
    }

    def run(self, role: str, location: str) -> CompResult:
        low, high = _lookup(role, location)
        return CompResult(role=role, location=location, currency="MYR",
                          low=low, high=high, period="month", source="builtin-heuristic")
