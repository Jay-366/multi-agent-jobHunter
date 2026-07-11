"""fetch_company_brief — a short read-only brief about a company.

Wraps enrichment/web-search. Today it's a deterministic stub that echoes a neutral brief
(a real web-search backend can replace it behind the same schema). Never writes anything.
"""
from __future__ import annotations

from pydantic import BaseModel


class CompanyBrief(BaseModel):
    name: str
    summary: str
    known: bool  # did we have real info? (stub → False)


class FetchCompanyBriefTool:
    name = "fetch_company_brief"
    description = "Fetch a short neutral brief about a company (stage, reputation signal)."
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Company name"}},
        "required": ["name"],
    }

    def run(self, name: str) -> CompanyBrief:
        return CompanyBrief(
            name=name,
            summary=f"No enrichment source configured; treat '{name}' as unknown and judge "
                    "legitimacy from the JD text alone.",
            known=False,
        )
