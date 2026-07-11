"""Scoring — deterministic weighting, gating, and ranking (ARCHITECTURE §9).

The analyst (LLM) emits raw 0-10 per-dimension scores; THIS module turns them into a
verdict with pure math. No LLM. Same inputs → same output, every time. Weights, threshold,
and the legitimacy floor come from config.yaml, so the user tunes priorities without any
prompt-fiddling or re-running the model.

Scale: dimension raw scores and `overall` are all 0-10.
"""
from __future__ import annotations

from src.config import settings
from src.models import Evaluation, Verdict


def _weights(weights: dict | None) -> dict:
    return weights if weights is not None else dict(settings.scoring["weights"])


def _threshold(threshold: float | None) -> float:
    return float(settings.scoring.get("threshold", 6.0)) if threshold is None else threshold


def _legitimacy_floor(floor: float | None) -> float:
    return float(settings.scoring.get("legitimacy_floor", 4.0)) if floor is None else floor


def apply_weights(evaluation: Evaluation, weights: dict | None = None) -> float:
    """Weighted average (0-10) of the dimensions that have a configured weight.

    Normalized by the weights actually present, so a missing dimension doesn't silently
    deflate the score. Deterministic: same dimensions + weights → same float, always.
    """
    weights = _weights(weights)
    acc = 0.0
    total_w = 0.0
    for d in evaluation.dimensions:
        w = weights.get(d.name)
        if w is None:
            continue
        acc += w * d.raw
        total_w += w
    return acc / total_w if total_w else 0.0


def gate(
    overall: float,
    threshold: float | None = None,
    legitimacy: float | None = None,
    legitimacy_floor: float | None = None,
) -> Verdict:
    """Turn an overall score into a verdict. Legitimacy below the floor is a hard Skip."""
    if legitimacy is not None and legitimacy < _legitimacy_floor(legitimacy_floor):
        return "Skip"
    return "Apply" if overall >= _threshold(threshold) else "Skip"


def score_evaluation(
    evaluation: Evaluation,
    weights: dict | None = None,
    threshold: float | None = None,
) -> Evaluation:
    """Return a copy of `evaluation` with `overall` and `verdict` filled in (rank later)."""
    overall = apply_weights(evaluation, weights)
    verdict = gate(overall, threshold, evaluation.legitimacy)
    return evaluation.model_copy(update={"overall": round(overall, 4), "verdict": verdict})


def rank(evaluations: list[Evaluation]) -> list[Evaluation]:
    """Return evaluations ordered by `overall` descending, with 1-based `rank` set."""
    ordered = sorted(
        evaluations,
        key=lambda e: (e.overall if e.overall is not None else float("-inf")),
        reverse=True,
    )
    return [e.model_copy(update={"rank": i + 1}) for i, e in enumerate(ordered)]
