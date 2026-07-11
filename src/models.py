"""All typed data shapes for the system — ONE file (no src/models/ folder).

Every model the pipeline passes around lives here: the candidate, the search target,
a job posting, a per-dimension score, a full evaluation, and the (stub) draft/prep-pack
shapes filled in by later stages. Everything is a Pydantic v2 model, so a good example
validates and a wrong-typed one is rejected at the boundary.

Layering note (ARCHITECTURE §5): this is Layer 4. It imports nothing from the app —
`services/`, `tools/`, `agents/`, and `orchestration/` all depend on it, never the reverse.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

__all__ = [
    "ExperienceItem",
    "EducationItem",
    "Candidate",
    "SearchTarget",
    "Source",
    "JobPosting",
    "DimensionScore",
    "Verdict",
    "Evaluation",
    "ApplicationDraft",
    "PrepPack",
]

# A job source tag. Kept as a Literal (not an Enum) so it is a plain string that
# round-trips cleanly through model_dump()/model_validate() without mode juggling.
Source = Literal["jobstreet", "glints"]

# The deterministic scoring gate's decision. Free of weighting logic — scoring.py sets it.
Verdict = Literal["Apply", "Review", "Skip"]


# --------------------------------------------------------------------------- #
# Candidate (parsed resume) — written by the onboarding agent (Stage 4)
# --------------------------------------------------------------------------- #
class ExperienceItem(BaseModel):
    """One role in the candidate's history. Only `title`+`company` are required."""

    title: str
    company: str
    duration: Optional[str] = None
    highlights: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    degree: str
    institution: str
    year: Optional[str] = None


class Candidate(BaseModel):
    """A parsed resume. `raw_text` is the original text; the rest is extracted from it.

    Never-fabricate rule (ARCHITECTURE §11): everything here must trace to `raw_text`.
    """

    name: str
    contact: dict[str, str] = Field(default_factory=dict)  # email/phone/linkedin/location…
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    raw_text: str = ""


# --------------------------------------------------------------------------- #
# SearchTarget — what to hunt for (written by the onboarding agent)
# --------------------------------------------------------------------------- #
class SearchTarget(BaseModel):
    keywords: list[str]
    location: str
    country: str = "MY"
    salary_min: Optional[float] = None
    salary_period: Optional[Literal["month", "year"]] = None
    employment_type: Optional[str] = None  # full-time | contract | internship | …
    remote_ok: Optional[bool] = None
    filters: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# JobPosting — one discovered posting (written by discovery service, Stage 2)
# --------------------------------------------------------------------------- #
class JobPosting(BaseModel):
    """A single posting from a provider.

    Salary is intentionally dual-shaped so both providers fit one model:
    - JobStreet gives salary as free text  → set `salary_text`, leave the numbers None.
    - Glints gives structured numbers       → set `salary_min/max/currency/period`.
    Either (or both, or neither) may be present.

    `description` is None until `fetch_detail()` is called (postings arrive from the
    list endpoint without the full JD, to avoid paying for detail on jobs we discard).
    """

    id: str
    source: Source
    title: str
    company: str
    location: Optional[str] = None
    url: str

    # salary — text form (JobStreet) and/or structured form (Glints)
    salary_text: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_period: Optional[Literal["month", "year"]] = None

    description: Optional[str] = None  # full JD text; None until fetched
    posted_at: Optional[str] = None


# --------------------------------------------------------------------------- #
# Evaluation — the analyst's output (raw scores) + the scoring service's verdict
# --------------------------------------------------------------------------- #
class DimensionScore(BaseModel):
    """One scored dimension. `raw` is the LLM's 0–10 judgement; `evidence` justifies it.

    The analyst emits these; the deterministic scoring service turns them into `overall`.
    """

    name: str
    raw: float = Field(ge=0.0, le=10.0)
    evidence: str


class Evaluation(BaseModel):
    """A full evaluation of one posting against the candidate.

    The analyst (LLM, ReAct) fills `posting_id`, `dimensions`, and `legitimacy` with RAW
    scores + evidence — and stops there. The deterministic scoring service (Stage 5) fills
    `overall`, `verdict`, and `rank`; they stay None until it runs. `legitimacy` is surfaced
    separately (mirroring its dimension) because a scam/ghost posting is a hard skip gate,
    independent of the weighted score.
    """

    posting_id: str
    dimensions: list[DimensionScore] = Field(default_factory=list)
    legitimacy: Optional[float] = Field(default=None, ge=0.0, le=10.0)

    overall: Optional[float] = None
    verdict: Optional[Verdict] = None
    rank: Optional[int] = None


# --------------------------------------------------------------------------- #
# Stubs for later stages (Tailor = Stage 9, Coach = Stage 10) — minimal now
# --------------------------------------------------------------------------- #
class ApplicationDraft(BaseModel):
    posting_id: str
    cv_markdown: str = ""
    cover_letter: str = ""
    highlighted_skills: list[str] = Field(default_factory=list)  # skills to emphasize (guarded)
    notes: list[str] = Field(default_factory=list)


class PrepPack(BaseModel):
    posting_id: str
    skill_gaps: list[str] = Field(default_factory=list)
    study_plan: list[str] = Field(default_factory=list)
    mock_questions: list[str] = Field(default_factory=list)
