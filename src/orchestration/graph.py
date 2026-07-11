"""Pipeline — the framework-free imperative flow (ARCHITECTURE §10).

    discover → (cap) → liveness gate → fetch JD → analyst → score → rank → set flags

Everything is quarantined here so the engine can later become LangGraph without touching
another file. State updates are immutable (JobHuntState.with_/add_trace/add_errors). All
external collaborators are injectable, so the whole pipeline runs hermetically in tests
with a stubbed LLM and fixture postings.
"""
from __future__ import annotations

import logging
from typing import Callable

from src.events import AgentEvent
from src.models import Candidate, JobPosting, SearchTarget
from src.orchestration.routing import needs_review, passes_liveness
from src.orchestration.state import JobHuntState
from src.services.discovery import discover as _discover
from src.services.discovery import fetch_detail as _fetch_detail
from src.services.liveness import is_live as _is_live
from src.services.scoring import rank, score_evaluation

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        analyst=None,
        discover_fn: Callable[[SearchTarget], list[JobPosting]] = _discover,
        fetch_detail_fn: Callable[[JobPosting], str] = _fetch_detail,
        live_fn: Callable[[str], bool] = _is_live,
        max_evaluations: int = 5,
        progress: Callable[[str], None] | None = None,
        check_liveness: bool = True,
    ):
        self._analyst = analyst
        self._discover = discover_fn
        self._fetch_detail = fetch_detail_fn
        self._live = live_fn
        self._max = max_evaluations
        self._progress = progress
        self._check_liveness = check_liveness

    def _emit(self, message) -> None:
        # Progress is best-effort: a sink that raises (e.g. a console that can't encode a
        # character) must never corrupt the run or be mistaken for an evaluation failure.
        # `message` may be a plain string (legacy) or a rich AgentEvent.
        if self._progress is not None:
            try:
                self._progress(message)
            except Exception:
                pass

    def _get_analyst(self):
        if self._analyst is None:
            from src.agents.analyst import AnalystAgent
            self._analyst = AnalystAgent()
        return self._analyst

    def invoke(self, candidate: Candidate, target: SearchTarget) -> JobHuntState:
        state = JobHuntState(candidate=candidate, target=target)

        # 1) discover
        self._emit(AgentEvent("discovery", "phase", "Discovering live postings…"))
        try:
            postings = self._discover(target)
        except Exception as e:
            return state.add_errors(f"discovery failed: {e}").with_(is_complete=True)
        state = state.with_(postings=postings).add_trace(
            f"discovered {len(postings)} postings"
        )
        subset = postings[: self._max]
        self._emit(AgentEvent("discovery", "result",
                              f"Discovered {len(postings)} postings; evaluating {len(subset)}…"))

        # 2) evaluate a capped subset: liveness gate → fetch JD → analyst → score
        evaluations = []
        enriched: dict[str, JobPosting] = {}  # id -> posting with JD, so the tracker has it
        for i, posting in enumerate(subset, 1):
            tag = f"[{i}/{len(subset)}]"
            self._emit(AgentEvent("analyst", "job",
                                  f"{tag} {posting.title} @ {posting.company}"))
            if self._check_liveness and not passes_liveness(posting, self._live):
                state = state.add_trace(f"skip dead posting {posting.id}")
                self._emit(AgentEvent("analyst", "info", f"{tag} skipped (posting not live)"))
                continue
            p = posting
            if not p.description:
                jd = self._fetch_detail(p)
                p = p.model_copy(update={"description": jd})
            enriched[p.id] = p
            try:
                ev = self._get_analyst().run(candidate, p, emit=self._emit)
                ev = score_evaluation(ev)
                evaluations.append(ev)
                state = state.add_trace(
                    f"scored {p.id}: overall={ev.overall} verdict={ev.verdict}"
                )
                self._emit(AgentEvent("analyst", "result",
                                      f"{tag} scored {ev.overall}/10 · {ev.verdict}"))
            except Exception as e:
                state = state.add_errors(f"evaluation of {p.id} failed: {e}")
                self._emit(AgentEvent("analyst", "error", f"{tag} failed: {e}"))

        # 3) rank + set control flags; fold enriched (JD-bearing) postings back into state
        ranked = rank(evaluations)
        review = needs_review(ranked)
        merged_postings = [enriched.get(p.id, p) for p in postings]
        state = state.with_(
            postings=merged_postings,
            evaluations=ranked,
            needs_human_review=review,
            is_complete=True,
        ).add_trace(f"ranked {len(ranked)} evaluations; needs_human_review={review}")
        return state
