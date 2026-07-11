"""JobHuntState — the one shared contract (ARCHITECTURE §6).

Every agent and service communicates only through this object; no agent calls another.
The model is frozen: nodes never mutate it in place. They produce a NEW state via the
immutable helpers below, so the input to any node is always left unchanged. `errors` and
`trace` use append-style reducers (accumulate, never clobber) — this is the audit log and
the merge point a future parallel fan-out would reduce into.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.models import Candidate, Evaluation, JobPosting, SearchTarget


class JobHuntState(BaseModel):
    model_config = ConfigDict(frozen=True)  # nodes must copy, not mutate

    # --- input ---
    candidate: Candidate
    target: SearchTarget

    # --- discovery output (a service writes this) ---
    postings: list[JobPosting] = Field(default_factory=list)

    # --- per-agent outputs (analyst owns evaluations) ---
    evaluations: list[Evaluation] = Field(default_factory=list)

    # --- control flags (explicit, drive routing) ---
    needs_human_review: bool = False
    is_complete: bool = False

    # --- reducer fields (accumulate, never clobber) ---
    errors: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)

    # --- immutable update helpers ---------------------------------------- #
    def with_(self, **updates) -> "JobHuntState":
        """Return a copy with the given fields replaced (never mutates self)."""
        return self.model_copy(update=updates)

    def add_trace(self, *messages: str) -> "JobHuntState":
        """Return a copy with messages appended to the trace (reducer)."""
        return self.model_copy(update={"trace": [*self.trace, *messages]})

    def add_errors(self, *messages: str) -> "JobHuntState":
        """Return a copy with messages appended to errors (reducer)."""
        return self.model_copy(update={"errors": [*self.errors, *messages]})
