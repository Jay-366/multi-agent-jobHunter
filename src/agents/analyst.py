"""Analyst agent — ReAct loop that scores a posting's fit (ARCHITECTURE §4.2, §9).

Each step the LLM either (a) calls a read-only tool to fetch a fact the JD lacks, or
(b) emits the final per-dimension RAW scores + evidence. It NEVER computes the overall
verdict — that is deterministic math in services/scoring.py. The loop is bounded by
`max_steps`; the last step forces a final evaluation so the agent always terminates.

Agency is encapsulated: run() returns a typed Evaluation (overall/verdict/rank still None).
The tool-call trail is exposed on `self.trace` so a caller (or a test) can observe that a
tool was used and that the loop stayed within bounds.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator

from src.events import AgentEvent, Emit, emit_to
from src.models import Candidate, DimensionScore, Evaluation, JobPosting
from src.prompts import ANALYST_PROMPT
from src.tools import default_tools, tool_registry

_DIMENSION_NAMES = ["role_match", "skills", "comp", "location", "growth", "legitimacy"]

_RESPONSE_FORMAT = (
    "\n\nRESPONSE FORMAT — return EXACTLY ONE JSON object, set EITHER action OR evaluation:\n"
    '  to call a tool: {"thought":"...","action":{"tool":"<exact tool name>",'
    '"args":{<the tool\'s arguments as a JSON OBJECT, never a list>}}}\n'
    '  to finish:      {"thought":"...","evaluation":{"posting_id":"<id>","dimensions":'
    '[{"name":"role_match","raw":0-10,"evidence":"..."}, ...one per dimension...],'
    '"legitimacy":0-10}}\n'
    "  Score ALL of these dimensions: " + ", ".join(_DIMENSION_NAMES) + ".\n"
    "  'raw' is a number 0-10. Never set both action and evaluation."
)


class ToolCall(BaseModel):
    # tolerate the model naming the field "name" instead of "tool"
    tool: str = Field(validation_alias=AliasChoices("tool", "name"))
    args: dict = Field(default_factory=dict)

    @field_validator("args", mode="before")
    @classmethod
    def _coerce_args(cls, v: Any) -> dict:
        return v if isinstance(v, dict) else {}


class RawEvaluation(BaseModel):
    """What the analyst emits — raw scores only, no verdict."""

    posting_id: str
    dimensions: list[DimensionScore]
    legitimacy: Optional[float] = None


class AnalystStep(BaseModel):
    """One ReAct turn: think, then either act (call a tool) or finish (evaluate)."""

    thought: str = ""
    action: Optional[ToolCall] = None
    evaluation: Optional[RawEvaluation] = None


class AnalystError(RuntimeError):
    pass


def _tool_specs(tools) -> str:
    lines = []
    for t in tools.values():
        lines.append(f"- {t.name}: {t.description} args={list(t.schema.get('properties', {}))}")
    return "\n".join(lines)


def _context(candidate: Candidate, posting: JobPosting) -> str:
    return (
        f"CANDIDATE:\n"
        f"  name: {candidate.name}\n"
        f"  summary: {candidate.summary}\n"
        f"  skills: {', '.join(candidate.skills)}\n\n"
        f"POSTING (id={posting.id}, source={posting.source}):\n"
        f"  title: {posting.title}\n"
        f"  company: {posting.company}\n"
        f"  location: {posting.location}\n"
        f"  salary: {posting.salary_text or f'{posting.salary_min}-{posting.salary_max} {posting.salary_currency}'}\n"
        f"  JD:\n{(posting.description or '(no JD text available)')[:6000]}\n"
    )


class AnalystAgent:
    name = "analyst"

    def __init__(self, llm=None, tools=None, max_steps: int | None = None,
                 thinking: bool | None = None):
        self._llm = llm
        self._tools = tool_registry(*(tools if tools is not None else default_tools()))
        self._max_steps = max_steps
        self._thinking_flag = thinking
        self.trace: list[str] = []

    def _thinking(self) -> bool:
        """Whether to stream the model's chain-of-thought (thinking mode). Config-driven,
        overridable via the constructor. Off by default so speed/cost are opt-in."""
        if self._thinking_flag is not None:
            return self._thinking_flag
        from src.config import settings
        return bool(settings.analyst.get("thinking", False))

    def _get_llm(self):
        if self._llm is None:
            from src.config import settings
            self._llm = settings.make_llm("pro")
        return self._llm

    def _max(self) -> int:
        if self._max_steps is not None:
            return self._max_steps
        from src.config import settings
        return int(settings.analyst.get("max_steps", 5))

    def run(self, candidate: Candidate, posting: JobPosting,
            emit: Emit | None = None) -> Evaluation:
        self.trace = []
        llm = self._get_llm()
        max_steps = self._max()
        ctx = _context(candidate, posting)
        system = (ANALYST_PROMPT + "\n\nAVAILABLE TOOLS:\n"
                  + _tool_specs(self._tools) + _RESPONSE_FORMAT)
        observations: list[str] = []
        stream = bool(emit) and self._thinking()

        for step in range(1, max_steps + 1):
            force_final = step == max_steps
            obs = ("\n\nOBSERVATIONS SO FAR:\n" + "\n".join(observations)) if observations else ""
            # When thinking is on, stream the model's raw reasoning tokens to the feed.
            on_reasoning = (
                (lambda d, s=step: emit_to(emit, AgentEvent("analyst", "reasoning_delta", d, s)))
                if stream else None
            )

            if force_final:
                # Last step: no more tools — must produce the evaluation now.
                user = (ctx + obs + "\n\nYou have no more steps. Return ONLY the final "
                        "evaluation JSON: {\"posting_id\":\"" + posting.id + "\",\"dimensions\":"
                        "[{\"name\":\"role_match\",\"raw\":0-10,\"evidence\":\"...\"}, ...one per "
                        "dimension: " + ", ".join(_DIMENSION_NAMES) + "...],\"legitimacy\":0-10}.")
                data = llm.complete(system=system, user=user, schema=RawEvaluation,
                                    on_reasoning=on_reasoning)
                raw = RawEvaluation.model_validate(data)
                self.trace.append(f"step {step}: forced final evaluation")
                emit_to(emit, AgentEvent("analyst", "info",
                                         "step budget reached — finalizing scores", step))
                return self._to_evaluation(raw, posting)

            user = (ctx + obs + "\n\nDecide the next step: either call ONE tool (set "
                    "'action'), or finish by setting 'evaluation'. Do not do both.")
            data = llm.complete(system=system, user=user, schema=AnalystStep,
                                on_reasoning=on_reasoning)
            stp = AnalystStep.model_validate(data)
            # If we streamed the raw reasoning, skip the short structured thought (no dupes).
            if stp.thought and not stream:
                emit_to(emit, AgentEvent("analyst", "thought", stp.thought, step))

            if stp.evaluation is not None:
                self.trace.append(f"step {step}: final evaluation")
                emit_to(emit, AgentEvent("analyst", "info", "reached a verdict", step))
                return self._to_evaluation(stp.evaluation, posting)

            if stp.action is not None:
                name = stp.action.tool
                tool = self._tools.get(name)
                if tool is None:
                    observations.append(f"[{name}] error: unknown tool")
                    self.trace.append(f"step {step}: unknown tool {name!r}")
                    emit_to(emit, AgentEvent("analyst", "error", f"unknown tool {name!r}", step))
                    continue
                emit_to(emit, AgentEvent("analyst", "tool",
                                         f"{name}({stp.action.args})", step))
                try:
                    result = tool.run(**stp.action.args)
                    observations.append(f"[{name}] -> {result.model_dump_json()}")
                    self.trace.append(f"step {step}: called {name}({stp.action.args})")
                    emit_to(emit, AgentEvent("analyst", "observation",
                                             f"{name} → {result.model_dump_json()}", step))
                except Exception as e:  # a bad tool call must not crash the loop
                    observations.append(f"[{name}] error: {e}")
                    self.trace.append(f"step {step}: tool {name} errored: {e}")
                    emit_to(emit, AgentEvent("analyst", "error", f"{name} errored: {e}", step))
                continue

            # Neither action nor evaluation — nudge and continue.
            self.trace.append(f"step {step}: no-op (no action or evaluation)")
            observations.append("[system] previous step returned neither action nor evaluation")

        raise AnalystError("analyst loop exhausted without an evaluation")  # unreachable

    @staticmethod
    def _to_evaluation(raw: RawEvaluation, posting: JobPosting) -> Evaluation:
        # Emit raw scores only — overall/verdict/rank stay None for scoring.py to fill.
        legit = raw.legitimacy
        if legit is None:
            for d in raw.dimensions:
                if d.name == "legitimacy":
                    legit = d.raw
                    break
        return Evaluation(
            posting_id=raw.posting_id or posting.id,
            dimensions=raw.dimensions,
            legitimacy=legit,
        )
