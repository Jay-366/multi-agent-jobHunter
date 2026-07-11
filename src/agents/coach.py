"""Coach agent — skill-gap + study plan + mock questions (ARCHITECTURE §4.2, Stage 10).

Single-shot: one LLM call returns the JD's required skills, a study plan, and ≥10 mock
questions. The skill-GAP itself is computed DETERMINISTICALLY (required minus what the
candidate already has), so a skill the candidate holds can never show up as a gap — the
guarantee doesn't depend on the LLM. Returns a typed PrepPack.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.events import AgentEvent, Emit, emit_to
from src.models import Candidate, Evaluation, JobPosting, PrepPack
from src.prompts import COACH_PROMPT


class _CoachOut(BaseModel):
    required_skills: list[str] = []
    study_plan: list[str] = []
    mock_questions: list[str] = []


class CoachAgent:
    name = "coach"

    def __init__(self, llm=None):
        self._llm = llm

    def _get_llm(self):
        if self._llm is None:
            from src.config import settings
            self._llm = settings.make_llm("flash")  # single-shot prep: fast model
        return self._llm

    def run(self, candidate: Candidate, evaluation: Evaluation,
            posting: Optional[JobPosting] = None, emit: Emit | None = None) -> PrepPack:
        jd = (posting.description if posting else "") or "(JD text unavailable)"
        user = (
            f"CANDIDATE:\n  skills: {', '.join(candidate.skills)}\n"
            f"  summary: {candidate.summary}\n\n"
            f"TARGET JOB (posting {evaluation.posting_id}):\n{jd[:4000]}\n"
        )
        emit_to(emit, AgentEvent("coach", "phase",
                                 "reading the JD for required skills + prep…"))
        out = _CoachOut.model_validate(
            self._get_llm().complete(system=COACH_PROMPT, user=user, schema=_CoachOut)
        )
        gaps = self._skill_gaps(out.required_skills, candidate)
        emit_to(emit, AgentEvent("coach", "result",
                                 f"{len(gaps)} skill gap(s), {len(out.mock_questions)} "
                                 "mock question(s)"))
        return PrepPack(
            posting_id=evaluation.posting_id,
            skill_gaps=gaps,
            study_plan=out.study_plan,
            mock_questions=out.mock_questions,
        )

    @staticmethod
    def _skill_gaps(required: list[str], candidate: Candidate) -> list[str]:
        have = {s.lower() for s in candidate.skills}
        resume = candidate.raw_text.lower()
        gaps: list[str] = []
        for r in required:
            key = r.strip().lower()
            if key and key not in have and key not in resume and r not in gaps:
                gaps.append(r)
        return gaps
