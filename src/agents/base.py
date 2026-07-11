"""Agent protocol — the shared contract for LLM workers (ARCHITECTURE §4.4).

Whatever an agent's internals (single-shot, ReAct loop, reflection), it presents one
callable `run(...)` that returns a typed Pydantic result. The graph neither knows nor
cares how many times a node looped — agency is encapsulated behind this protocol.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class Agent(Protocol):
    name: str

    def run(self, *args, **kwargs) -> BaseModel:
        """Do the agent's one job and return a typed result."""
        ...
