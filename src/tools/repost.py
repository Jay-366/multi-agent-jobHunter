"""check_repost — is this posting a likely repost / ghost job? (read-only)

Wraps dedup/scan-history reasoning. Today it applies deterministic heuristics to the
posting's own fields (a real scan-history backend can replace it behind the same schema).
Never writes anything.
"""
from __future__ import annotations

from pydantic import BaseModel


class RepostResult(BaseModel):
    is_repost: bool
    reason: str


_GHOST_SIGNALS = ("always hiring", "urgent hiring", "immediate joiner", "evergreen")


class CheckRepostTool:
    name = "check_repost"
    description = "Heuristic check whether a posting looks like a repost or evergreen ghost job."
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string", "description": "JD text, if available"},
        },
        "required": ["title"],
    }

    def run(self, title: str, description: str = "") -> RepostResult:
        blob = f"{title}\n{description}".lower()
        hits = [s for s in _GHOST_SIGNALS if s in blob]
        if hits:
            return RepostResult(is_repost=True, reason=f"ghost-job signal(s): {', '.join(hits)}")
        return RepostResult(is_repost=False, reason="no repost/ghost signals detected")
