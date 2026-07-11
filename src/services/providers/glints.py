"""Glints Malaysia provider — GraphQL searchJobsV3 (throttled secondary, VALIDATION.md).

POST glints.com/api/v2-alc/graphql, op searchJobsV3, CountryCode=MY → structured salary.

Glints rate-limits bursts, so this provider MUST behave (ARCHITECTURE §7):
  - ≥1s jittered delay between requests,
  - a realistic User-Agent,
  - graceful degradation: on a rate-limit / shell / empty response it logs and returns
    a partial-or-empty list, it never crashes discovery.
HTTP goes through a single `_post` seam so tests can stub it and run offline.
"""
from __future__ import annotations

import logging
import random
import time

import requests

from src.models import JobPosting, SearchTarget

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_GRAPHQL_URL = "https://glints.com/api/v2-alc/graphql"
_QUERY = (
    "query searchJobsV3($data: JobSearchConditionInput!){ "
    "searchJobsV3(data:$data){ jobsInPage{ id title company{ name } "
    "city{ name } salaries{ minAmount maxAmount CurrencyCode salaryMode } } } }"
)


class GlintsProvider:
    id = "glints"

    def __init__(self, country: str = "MY", page_size: int = 30, session=None,
                 min_delay: float = 1.0):
        self.country = country
        self.page_size = page_size
        self.min_delay = min_delay
        self._session = session or requests.Session()
        self._last_request_at: float | None = None

    # --- throttle + HTTP seam --------------------------------------------- #
    def _throttle(self) -> None:
        """Sleep ≥ min_delay (jittered) since the last request, to avoid rate limits."""
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            wait = self.min_delay + random.uniform(0, 0.5) - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _post(self, payload: dict) -> dict:
        self._throttle()
        resp = self._session.post(
            _GRAPHQL_URL,
            json=payload,
            headers={"User-Agent": _UA, "Accept": "application/json",
                     "Content-Type": "application/json"},
            timeout=40,
        )
        resp.raise_for_status()
        return resp.json()

    # --- Provider protocol ------------------------------------------------- #
    def search(self, target: SearchTarget) -> list[JobPosting]:
        payload = {
            "operationName": "searchJobsV3",
            "query": _QUERY,
            "variables": {"data": {
                "SearchTerm": " ".join(target.keywords),
                "CountryCode": self.country,
                "includeExternalJobs": True,
                "pageSize": self.page_size,
                "page": 1,
            }},
        }
        try:
            data = self._post(payload)
        except (requests.RequestException, ValueError) as e:
            # Rate-limited / shell / non-JSON response → degrade, don't crash.
            log.warning("Glints search degraded (rate limit or bad response): %s", e)
            return []

        page = (((data or {}).get("data") or {}).get("searchJobsV3") or {}).get("jobsInPage")
        if not page:
            log.warning("Glints returned no jobsInPage (possible rate limit / empty).")
            return []
        return [self._to_posting(j) for j in page if j.get("id")]

    def fetch_detail(self, posting: JobPosting) -> str:
        # Glints JD detail (Draft.js in __NEXT_DATA__) is a Stage 11 concern; the
        # structured listing already carries the useful fields. Degrade to "".
        return ""

    # --- parsing ----------------------------------------------------------- #
    @staticmethod
    def _to_posting(j: dict) -> JobPosting:
        job_id = str(j.get("id"))
        company = (j.get("company") or {}).get("name") or ""
        city = (j.get("city") or {}).get("name") if j.get("city") else None
        sal = (j.get("salaries") or [{}])[0] or {}
        fields: dict = {}
        text = None
        if sal.get("minAmount"):
            mode = (sal.get("salaryMode") or "").lower()
            fields = {
                "salary_min": float(sal["minAmount"]),
                "salary_max": float(sal["maxAmount"]) if sal.get("maxAmount") else None,
                "salary_currency": sal.get("CurrencyCode"),
                "salary_period": "month" if mode == "month" else ("year" if mode else None),
            }
            text = (f"{sal.get('minAmount')}-{sal.get('maxAmount')} "
                    f"{sal.get('CurrencyCode')} /{sal.get('salaryMode')}")
        return JobPosting(
            id=job_id,
            source="glints",
            title=j.get("title") or "",
            company=company,
            location=city,
            url=f"https://glints.com/opportunities/jobs/{job_id}",
            salary_text=text,
            **fields,
        )
