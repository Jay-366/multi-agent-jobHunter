"""Routing — pure gate functions on state (ARCHITECTURE §4.1, §11).

No side effects, no I/O of their own (liveness takes an injected checker). Each is a plain
predicate the graph consults to decide the next step. Tested per branch.
"""
from __future__ import annotations

from typing import Callable

from src.models import Evaluation, JobPosting


def above_threshold(evaluation: Evaluation) -> bool:
    """True if scoring marked this posting worth applying to (verdict == 'Apply')."""
    return evaluation.verdict == "Apply"


def needs_review(evaluations: list[Evaluation]) -> bool:
    """The human-review gate: True if ANY evaluation is above threshold.

    Nothing goes outbound automatically — a True here means 'present these for a human
    to review', never 'apply'.
    """
    return any(above_threshold(e) for e in evaluations)


def passes_liveness(posting: JobPosting, is_live_fn: Callable[[str], bool]) -> bool:
    """Liveness gate: only spend an LLM evaluation on a posting that is still reachable."""
    return bool(is_live_fn(posting.url))
