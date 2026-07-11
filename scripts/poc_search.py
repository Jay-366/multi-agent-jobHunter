"""
poc_search.py — Proof-of-concept: how the job search actually works.

This is the CLEANED-UP version of the code that fetched real Malaysian jobs
during our testing. It has ZERO external dependencies (only Python's standard
library), so you can run it with just:

    python scripts/poc_search.py

WHAT IT DOES (the whole mechanism in 3 functions):
    1. jobstreet_search()  -> STEP 1: ask JobStreet's "data desk" for a LIST of jobs
    2. jobstreet_jd()      -> STEP 2: use one job's ID to fetch its FULL description
    3. glints_search()     -> same STEP 1 idea, but Glints uses a different style of desk

KEY MENTAL MODEL:
    A website = a pretty page (what you see)  +  a "data desk" API (what the page
    secretly talks to). We skip the pretty page and talk to the data desk directly.
    No login. No browser. No AI needed for this part — it's just HTTP requests.
"""

import json
import re
import gzip
import html
from urllib.request import Request, urlopen
from urllib.parse import urlencode

# A "User-Agent" is just us saying "hi, I'm a normal browser" so the server replies.
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def _get(url, headers=None):
    """Send a plain GET message to a data desk and return the text it replies with."""
    req = Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "*/*", **(headers or {})})
    with urlopen(req, timeout=40) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def _post_json(url, payload, headers=None):
    """Send a POST message carrying a JSON body (used for Glints' GraphQL desk)."""
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"User-Agent": BROWSER_UA, "Content-Type": "application/json",
                 "Accept": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# ENDPOINT NOTE — v5 vs v4 (tested live, 2026-07-11)
#   v5  api/jobsearch/v5/search        -> HTTP 200, application/json  ✅ LIVE (we use this)
#   v4  api/chalice-search/v4/search   -> HTTP 404 on my.jobstreet.com AND www.seek.com.au  ❌ DEAD
#         (the old www.jobstreet.com.my/...v4 path just 308-redirects to the homepage HTML)
#   Conclusion: the "v4 chalice-search is the real one" claim is OUTDATED. For JobStreet MY
#   today, v5 is the working endpoint. Keeping v5. v4 is documented here only so we don't
#   re-test a dead path later.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# STEP 1 — JOBSTREET SEARCH  (the "menu": a list of jobs, no full text yet)
# ---------------------------------------------------------------------------
def jobstreet_search(keywords, location, size=6):
    """
    Ask JobStreet Malaysia's data desk for jobs matching keywords + location.

    The URL below IS the "quiet message" your browser normally sends.
    - siteKey=MY-Main  -> the Malaysia branch (SG-Main = Singapore, ID-Main = Indonesia)
    - keywords, where  -> exactly what you'd type in the two search boxes
    """
    base = "https://my.jobstreet.com/api/jobsearch/v5/search"
    query = urlencode({
        "siteKey": "MY-Main",
        "keywords": keywords,
        "where": location,
        "pageSize": size,
        "page": 1,
    })
    data = json.loads(_get(f"{base}?{query}", headers={"Accept": "application/json"}))

    print(f"JobStreet: {data.get('totalCount')} total matches for '{keywords}' in {location}")
    jobs = []
    for j in data.get("data", []):
        loc = (j.get("locations") or [{}])[0].get("label", "")
        jobs.append({
            "id": j.get("id"),
            "title": j.get("title"),
            "company": j.get("companyName"),
            "location": loc,
            "salary": j.get("salaryLabel") or "n/a",
        })
    return jobs


# ---------------------------------------------------------------------------
# STEP 2 — JOBSTREET DETAIL  (the "full recipe": the complete JD text)
# ---------------------------------------------------------------------------
def jobstreet_jd(job_id):
    """
    Fetch ONE job's full description using its ID.

    JobStreet doesn't hand the full text over a clean API; instead its job page
    ships a big hidden blob of data called `window.SEEK_REDUX_DATA`. We grab that
    blob, read it as JSON, and pull out the description. (This is 'scraping'.)
    """
    page = _get(f"https://my.jobstreet.com/job/{job_id}", headers={"Accept": "text/html"})

    marker = "window.SEEK_REDUX_DATA = "
    start = page.find(marker) + len(marker)
    # raw_decode reads exactly one JSON object starting at `start` and stops.
    state, _ = json.JSONDecoder().raw_decode(page, start)

    # The description is stored under a "content" key (as HTML). There are a few
    # "content" keys; the real JD is the longest one that isn't CSS styling.
    contents = []
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

    def strip_html(t):
        t = re.sub(r"<[^>]+>", " ", t or "")
        t = html.unescape(t)
        return re.sub(r"[ \t]+", " ", t).strip()

    real = [c for c in contents if "capsize" not in c and "lmis-" not in c]
    return strip_html(max(real, key=len)) if real else "(no JD found)"


# ---------------------------------------------------------------------------
# STEP 1 (Glints flavour) — a "GraphQL" data desk
# ---------------------------------------------------------------------------
def glints_search(keywords, size=6):
    """
    Glints' data desk is a 'GraphQL' desk: instead of a URL with ?query params,
    you POST a little JSON note saying exactly which fields you want back.
    Bonus: Glints returns STRUCTURED salary numbers (min/max/currency), which is
    cleaner than JobStreet's salary-as-text.

    NOTE: fetching Glints *details* too fast gets you rate-limited (they block
    bursts). Be gentle: add delays between requests in real use.
    """
    query = ("query searchJobsV3($data: JobSearchConditionInput!){ "
             "searchJobsV3(data:$data){ jobsInPage{ id title company{ name } "
             "city{ name } salaries{ minAmount maxAmount CurrencyCode salaryMode } } } }")
    payload = {
        "operationName": "searchJobsV3",
        "query": query,
        "variables": {"data": {
            "SearchTerm": keywords,
            "CountryCode": "MY",          # Malaysia
            "includeExternalJobs": True,
            "pageSize": size,
            "page": 1,
        }},
    }
    data = _post_json("https://glints.com/api/v2-alc/graphql", payload)
    jobs = []
    for j in data.get("data", {}).get("searchJobsV3", {}).get("jobsInPage", []):
        s = (j.get("salaries") or [{}])[0]
        salary = (f"{s.get('minAmount')}-{s.get('maxAmount')} {s.get('CurrencyCode')} "
                  f"/{s.get('salaryMode')}") if s.get("minAmount") else "n/a"
        jobs.append({
            "id": j.get("id"),
            "title": j.get("title"),
            "company": (j.get("company") or {}).get("name", ""),
            "salary": salary,
        })
    return jobs


# ---------------------------------------------------------------------------
# Run it: search -> show list -> fetch ONE full JD
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("STEP 1: JobStreet search (the menu)")
    print("=" * 70)
    js = jobstreet_search("software engineer", "Kuala Lumpur", size=5)
    for i, job in enumerate(js, 1):
        print(f"{i}. {job['title']} | {job['company']} | {job['location']} | {job['salary']}")

    print("\n" + "=" * 70)
    print("STEP 2: fetch the FULL description of the first job (the recipe)")
    print("=" * 70)
    first = js[0]
    print(f"Job: {first['title']} @ {first['company']} (id {first['id']})\n")
    jd = jobstreet_jd(first["id"])
    print(jd[:1200] + ("..." if len(jd) > 1200 else ""))

    print("\n" + "=" * 70)
    print("STEP 1 (Glints): same idea, structured salary")
    print("=" * 70)
    for i, job in enumerate(glints_search("software engineer", size=5), 1):
        print(f"{i}. {job['title']} | {job['company']} | {job['salary']}")
