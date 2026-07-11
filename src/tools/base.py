"""Tool protocol — how agents touch the world (ARCHITECTURE §4.3).

A Tool is a thin, LLM-callable wrapper exposing a *selected, read-only* slice of a service
with a name, a JSON schema, and a description the model can reason about. The three rules
that keep an agentic node inside a clean workflow:
  1. a finite tool set,
  2. READ-ONLY — no tool submits an application or writes a canonical file,
  3. a max-steps cap on the loop (enforced by the agent, Stage 5).

Every tool returns a typed Pydantic result so callers get validated data, not loose dicts.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    schema: dict  # JSON schema describing run()'s keyword arguments

    def run(self, **kwargs) -> BaseModel:
        """Execute the read-only lookup and return a typed result. Must not mutate state."""
        ...


def tool_registry(*tools: Tool) -> dict[str, Tool]:
    """Build a {name: tool} map an agent can look tools up in by name."""
    return {t.name: t for t in tools}
