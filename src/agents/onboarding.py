"""Onboarding agent — resume + wish -> Candidate + SearchTarget (single-shot).

A single `pro` call extracts structured data, validated into the Stage 1 models. The
never-fabricate rule (ARCHITECTURE §11) is enforced in CODE, not just prompted: any skill
the model returns that does not actually appear in the resume text is dropped before the
Candidate is handed on. Thin agent — the LLM call + validation is the whole job.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.models import Candidate, SearchTarget
from src.prompts import ONBOARDING_PROMPT


class OnboardingOutput(BaseModel):
    """The two shapes onboarding produces, together (what the LLM returns as JSON)."""

    candidate: Candidate
    target: SearchTarget


def _drop_fabricated_skills(candidate: Candidate, resume_text: str) -> Candidate:
    """Keep only skills whose text actually appears in the resume (case-insensitive)."""
    hay = resume_text.lower()
    kept = [s for s in candidate.skills if s.strip() and s.strip().lower() in hay]
    if kept != candidate.skills:
        candidate = candidate.model_copy(update={"skills": kept})
    return candidate


class OnboardingAgent:
    name = "onboarding"

    def __init__(self, llm=None):
        # lazy default so importing this module needs no API key
        self._llm = llm

    def _get_llm(self):
        if self._llm is None:
            from src.config import settings
            self._llm = settings.make_llm("pro")
        return self._llm

    def run(self, resume_text: str, wish: str) -> OnboardingOutput:
        user = f"RESUME:\n{resume_text}\n\nWISH:\n{wish}"
        data = self._get_llm().complete(
            system=ONBOARDING_PROMPT, user=user, schema=OnboardingOutput
        )
        out = OnboardingOutput.model_validate(data)
        # never-fabricate guard, and make sure raw_text is preserved
        candidate = out.candidate
        if not candidate.raw_text:
            candidate = candidate.model_copy(update={"raw_text": resume_text})
        candidate = _drop_fabricated_skills(candidate, resume_text)
        return OnboardingOutput(candidate=candidate, target=out.target)
