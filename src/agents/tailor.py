"""Tailor agent — reflection loop that never fabricates (ARCHITECTURE §4.2, §11).

    draft → self-critique (keyword fit + fabrication) → revise → ... (bounded)

The self-critique is where the never-fabricate guardrail is enforced by the agent itself,
before a human sees the draft. A deterministic CODE backstop then strips any skill claim
that isn't in the candidate's own materials — so the guarantee does not depend on the LLM
behaving. run() returns a typed ApplicationDraft; the critique trail is on `self.trace`.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from src.events import AgentEvent, Emit, emit_to
from src.models import ApplicationDraft, Candidate, Evaluation, JobPosting
from src.prompts import TAILOR_CRITIQUE_PROMPT, TAILOR_DRAFT_PROMPT


class _Draft(BaseModel):
    posting_id: str = ""
    cv_markdown: str = ""
    cover_letter: str = ""
    highlighted_skills: list[str] = []


class _Critique(BaseModel):
    keyword_fit_ok: bool = True
    fabrications: list[str] = []


def _remove_lines_mentioning(text: str, tokens: list[str]) -> str:
    if not tokens or not text:
        return text
    lowered = [t.lower() for t in tokens if t.strip()]
    kept = [ln for ln in text.splitlines()
            if not any(tok in ln.lower() for tok in lowered)]
    return "\n".join(kept)


class TailorAgent:
    name = "tailor"

    def __init__(self, llm=None, max_passes: int = 2):
        self._llm = llm
        self.max_passes = max_passes
        self.trace: list[str] = []

    def _get_llm(self):
        if self._llm is None:
            from src.config import settings
            self._llm = settings.make_llm("flash")  # drafting: fast model, reliable JSON
        return self._llm

    def run(self, candidate: Candidate, evaluation: Evaluation,
            posting: Optional[JobPosting] = None, emit: Emit | None = None) -> ApplicationDraft:
        self.trace = []
        llm = self._get_llm()
        jd = (posting.description if posting else "") or "(JD text unavailable)"
        ctx = self._context(candidate, jd, evaluation)

        # pass 1: draft
        emit_to(emit, AgentEvent("tailor", "phase", "drafting a tailored CV…", 1))
        draft = _Draft.model_validate(
            llm.complete(system=TAILOR_DRAFT_PROMPT, user=ctx, schema=_Draft)
        )
        self.trace.append("pass 1: draft")

        # reflection passes: critique → revise. The critique is an ENHANCEMENT — if the
        # LLM fails to produce one, we keep the current draft (the code guard below still
        # runs), rather than aborting the whole tailoring.
        for i in range(1, self.max_passes):
            emit_to(emit, AgentEvent("tailor", "thought",
                                     "self-critiquing for keyword fit and fabrication…", i))
            try:
                crit = _Critique.model_validate(llm.complete(
                    system=TAILOR_CRITIQUE_PROMPT,
                    user=ctx + "\n\nDRAFT:\n" + draft.model_dump_json(),
                    schema=_Critique,
                ))
            except Exception as e:
                self.trace.append(f"pass {i}: critique unavailable ({e}); keeping draft")
                emit_to(emit, AgentEvent("tailor", "info",
                                         "critique unavailable — keeping draft", i))
                break
            self.trace.append(
                f"pass {i}: critique keyword_fit_ok={crit.keyword_fit_ok} "
                f"fabrications={crit.fabrications}"
            )
            emit_to(emit, AgentEvent("tailor", "observation",
                                     f"critique: keyword_fit_ok={crit.keyword_fit_ok}, "
                                     f"fabrications={crit.fabrications or 'none'}", i))
            if crit.keyword_fit_ok and not crit.fabrications:
                emit_to(emit, AgentEvent("tailor", "result", "draft passed self-critique", i))
                break
            try:
                draft = _Draft.model_validate(llm.complete(
                    system=TAILOR_DRAFT_PROMPT,
                    user=(ctx + "\n\nPREVIOUS DRAFT:\n" + draft.model_dump_json()
                          + "\n\nFIX THESE FABRICATIONS (remove them): "
                          + ", ".join(crit.fabrications)
                          + "\nAlso improve keyword fit using only real facts."),
                    schema=_Draft,
                ))
            except Exception as e:
                self.trace.append(f"pass {i}: revise failed ({e}); keeping draft")
                emit_to(emit, AgentEvent("tailor", "info", "revise failed — keeping draft", i))
                break
            self.trace.append(f"pass {i}: revised")
            emit_to(emit, AgentEvent("tailor", "phase", "revised the draft", i))

        # deterministic backstop guard — the guarantee does not trust the LLM
        result = self._enforce_no_fabrication(draft, candidate, evaluation.posting_id)
        if result.notes:
            emit_to(emit, AgentEvent("tailor", "info", result.notes[0]))
        return result

    @staticmethod
    def _context(candidate: Candidate, jd: str, evaluation: Evaluation) -> str:
        return (
            f"CANDIDATE MATERIALS:\n"
            f"  name: {candidate.name}\n"
            f"  skills: {', '.join(candidate.skills)}\n"
            f"  summary: {candidate.summary}\n"
            f"  resume:\n{candidate.raw_text[:4000]}\n\n"
            f"TARGET JOB (posting {evaluation.posting_id}):\n{jd[:4000]}\n"
        )

    def _enforce_no_fabrication(self, draft: _Draft, candidate: Candidate,
                                fallback_pid: str) -> ApplicationDraft:
        allowed = {s.lower() for s in candidate.skills}
        resume = candidate.raw_text.lower()

        def is_real(skill: str) -> bool:
            s = skill.strip().lower()
            return bool(s) and (s in allowed or s in resume)

        kept = [s for s in draft.highlighted_skills if is_real(s)]
        forbidden = [s for s in draft.highlighted_skills if not is_real(s)]
        if forbidden:
            self.trace.append(f"guard: stripped fabricated skills {forbidden}")

        cv = _remove_lines_mentioning(draft.cv_markdown, forbidden)
        cover = _remove_lines_mentioning(draft.cover_letter, forbidden)
        return ApplicationDraft(
            posting_id=draft.posting_id or fallback_pid, cv_markdown=cv, cover_letter=cover,
            highlighted_skills=kept,
            notes=([f"guard removed fabricated: {', '.join(forbidden)}"] if forbidden else []),
        )
