"""AgentEvent — a small, dependency-free struct for live agent-activity streaming.

The pipeline and agents emit these through the existing `progress` callback so a UI can
render a Claude/OpenAI-style trace (thoughts, tool calls, reflection passes) as work
happens. It is deliberately layer-neutral (stdlib only), so agents, orchestration, and the
app may all import it without a dependency inversion.

Backward compatible: `str(event)` returns the human line, so any sink that still expects a
plain string (the CLI's print, older tests) keeps working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Union

# What an agent/pipeline may hand to a progress sink: a rich event or a plain string.
ProgressItem = Union["AgentEvent", str]
Emit = Callable[[ProgressItem], None]


@dataclass(frozen=True)
class AgentEvent:
    """One line of agent activity.

    agent : who is speaking — "pipeline" | "discovery" | "analyst" | "tailor" | "coach"
    kind  : what kind of line — "phase" | "job" | "thought" | "tool" | "observation"
            | "result" | "info" | "error"
    text  : the human-readable message
    step  : optional ReAct step / pass number, for display
    """

    agent: str
    kind: str
    text: str
    step: Optional[int] = None

    def __str__(self) -> str:  # plain-string fallback for print()/legacy sinks
        return self.text


def emit_to(sink: Optional[Emit], item: ProgressItem) -> None:
    """Best-effort emit: a sink that raises (e.g. a console that can't encode a glyph) must
    never corrupt a run or be mistaken for a real failure."""
    if sink is None:
        return
    try:
        sink(item)
    except Exception:
        pass
