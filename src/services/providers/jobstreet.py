"""JobStreet Malaysia provider — SEEK v5 API (proven primary, VALIDATION.md).

Search:  GET my.jobstreet.com/api/jobsearch/v5/search?siteKey=MY-Main&keywords=..&where=..
Detail:  GET my.jobstreet.com/job/{id}  → parse window.SEEK_REDUX_DATA → longest non-CSS content.

Ported from scripts/poc_search.py. HTTP goes through a single `_get` seam so tests can
stub it and run offline against saved fixtures (no network). v4 chalice-search is dead (404).
"""
from __future__ import annotations

import html
import json
import re

import requests

from src.models import JobPosting, SearchTarget

_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_SEARCH_URL = "https://my.jobstreet.com/api/jobsearch/v5/search"
_JOB_URL = "https://my.jobstreet.com/job/{id}"
_REDUX_MARKER = "window.SEEK_REDUX_DATA = "


def parse_salary(label: str) -> dict:
    """Best-effort parse of a JobStreet salary label into structured numbers.

    "RM 5,000 - RM 8,000 per month" -> {min:5000, max:8000, currency:"MYR", period:"month"}
    Returns only the keys it can confidently extract; text-only labels yield {}.
    """
    if not label:
        return {}
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", label)]
    out: dict = {}
    if nums:
        out["salary_min"] = min(nums)
        out["salary_max"] = max(nums)
    low = label.lower()
    if "rm" in low or "myr" in low:
        out["salary_currency"] = "MYR"
    if "month" in low:
        out["salary_period"] = "month"
    elif "year" in low or "annum" in low or "p.a" in low:
        out["salary_period"] = "year"
    return out


class JobStreetProvider:
    id = "jobstreet"

    def __init__(self, site_key: str = "MY-Main", page_size: int = 30, session=None):
        self.site_key = site_key
        self.page_size = page_size
        self._session = session or requests.Session()

    # --- HTTP seam (stub this in tests) ------------------------------------ #
    def _get(self, url: str, params: dict | None = None, accept: str = "*/*") -> str:
        resp = self._session.get(
            url,
            params=params,
            headers={"User-Agent": _BROWSER_UA, "Accept": accept},
            timeout=40,
        )
        resp.raise_for_status()
        return resp.text

    # --- Provider protocol ------------------------------------------------- #
    def search(self, target: SearchTarget) -> list[JobPosting]:
        params = {
            "siteKey": self.site_key,
            "keywords": " ".join(target.keywords),
            "where": target.location,
            "pageSize": self.page_size,
            "page": 1,
        }
        data = json.loads(self._get(_SEARCH_URL, params=params, accept="application/json"))
        return [self._to_posting(j) for j in data.get("data", []) if j.get("id")]

    def fetch_detail(self, posting: JobPosting) -> str:
        page = self._get(_JOB_URL.format(id=posting.id), accept="text/html")
        return self._parse_jd(page)

    # --- parsing helpers --------------------------------------------------- #
    @staticmethod
    def _to_posting(j: dict) -> JobPosting:
        job_id = str(j.get("id"))
        loc = (j.get("locations") or [{}])[0].get("label", "") or None
        label = j.get("salaryLabel") or ""
        return JobPosting(
            id=job_id,
            source="jobstreet",
            title=j.get("title") or "",
            company=j.get("companyName") or "",
            location=loc,
            url=_JOB_URL.format(id=job_id),
            salary_text=label or None,
            **parse_salary(label),
        )

    @staticmethod
    def _parse_jd(page: str) -> str:
        idx = page.find(_REDUX_MARKER)
        if idx == -1:
            return ""
        start = idx + len(_REDUX_MARKER)
        try:
            state, _ = json.JSONDecoder().raw_decode(page, start)
        except (json.JSONDecodeError, ValueError):
            return ""

        contents: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "content" and isinstance(v, str):
                        contents.append(v)
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(state)
        real = [c for c in contents if "capsize" not in c and "lmis-" not in c]
        if not real:
            return ""
        text = re.sub(r"<[^>]+>", " ", max(real, key=len))
        return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()
