"""Liveness check — is a posting still reachable? (ARCHITECTURE §7)

A cheap, zero-token HTTP check that runs BEFORE the analyst so we never spend an LLM
evaluation on a dead posting. Deterministic and unit-testable; any error → not live.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_MIN_CONTENT = 500  # a real job page is far larger; a redirect-to-empty stub is not


def is_live(url: str, timeout: int = 15, session=None) -> bool:
    """True iff `url` returns HTTP 200 with a non-trivial body. Any failure → False."""
    if not url:
        return False
    sess = session or requests
    try:
        resp = sess.get(
            url, headers={"User-Agent": _UA}, timeout=timeout, allow_redirects=True
        )
    except requests.RequestException as e:
        log.info("liveness: %s → not live (%s)", url, e)
        return False
    if resp.status_code != 200:
        return False
    return len(resp.text or "") >= _MIN_CONTENT
