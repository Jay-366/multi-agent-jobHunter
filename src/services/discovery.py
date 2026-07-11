"""Discovery — run the enabled providers, merge, blacklist, dedup (ARCHITECTURE §7).

This is the deterministic entry point the orchestration graph calls. It builds providers
from config (or takes injected ones for tests), fans the target across them, drops
blacklisted companies, and returns a single deduped list. A failing provider degrades
(logged) instead of sinking the whole run.
"""
from __future__ import annotations

import logging

from src.config import settings
from src.models import JobPosting, SearchTarget
from src.services.dedup import dedup
from src.services.providers.base import Provider
from src.services.providers.glints import GlintsProvider
from src.services.providers.jobstreet import JobStreetProvider

log = logging.getLogger(__name__)


def build_providers(names: list[str] | None = None) -> list[Provider]:
    """Instantiate providers by name using config defaults."""
    disc = settings.discovery
    names = names if names is not None else disc.get("providers", ["jobstreet"])
    page_size = int(disc.get("max_results_per_provider", 30))
    site_key = disc.get("site_key", "MY-Main")
    country = disc.get("country", "MY")
    registry = {
        "jobstreet": lambda: JobStreetProvider(site_key=site_key, page_size=page_size),
        "glints": lambda: GlintsProvider(country=country, page_size=page_size),
    }
    providers: list[Provider] = []
    for name in names:
        make = registry.get(name)
        if make is None:
            log.warning("Unknown provider %r in config; skipping.", name)
            continue
        providers.append(make())
    return providers


def fetch_detail(posting: JobPosting) -> str:
    """Fetch full JD text for one posting by dispatching to its source provider.

    Used by orchestration to fill `description` only for the (small) capped subset it
    actually evaluates — never for every discovered posting.
    """
    provs = {p.id: p for p in build_providers([posting.source])}
    provider = provs.get(posting.source)
    if provider is None:
        log.warning("No provider for source %r; cannot fetch detail.", posting.source)
        return ""
    try:
        return provider.fetch_detail(posting)
    except Exception as e:
        log.warning("fetch_detail failed for %s: %s", posting.id, e)
        return ""


def discover(
    target: SearchTarget,
    providers: list[Provider] | None = None,
    blacklist: list[str] | None = None,
    deduplicate: bool = True,
) -> list[JobPosting]:
    """Return postings for `target`, merged across providers (deduped unless disabled)."""
    if providers is None:
        providers = build_providers()
    blocked = {b.strip().lower() for b in (blacklist or [])}

    merged: list[JobPosting] = []
    for p in providers:
        try:
            found = p.search(target)
        except Exception as e:  # a provider must never sink the whole run
            log.warning("Provider %r failed: %s", getattr(p, "id", p), e)
            continue
        log.info("Provider %r returned %d postings.", getattr(p, "id", p), len(found))
        merged.extend(found)

    if blocked:
        merged = [p for p in merged if (p.company or "").strip().lower() not in blocked]

    return dedup(merged) if deduplicate else merged
