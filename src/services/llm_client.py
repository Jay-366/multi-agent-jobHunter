"""DeepSeek chat wrapper (OpenAI-compatible) — Stage 3 complete.

Two modes through one `complete()`:
  - text:   complete(system, user)              -> str
  - schema: complete(system, user, schema=Model) -> dict validated against a Pydantic model

Schema mode uses JSON-mode + robust extraction; on invalid output it does ONE repair
retry (feeding the error back), then raises a clear LLMError. Kept independent of
src.config (no circular import). The OpenAI client is injectable (`client=`) so tests
can run fully mocked with no network.

Note: `deepseek-v4-pro` is a reasoning model — it spends tokens on hidden reasoning
before the visible answer, so callers must budget max_tokens generously (config.yaml).
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional, Type

from pydantic import BaseModel, ValidationError

_JSON_INSTRUCTION = (
    "\n\nRespond with a single valid JSON object and nothing else — "
    "no prose, no markdown code fences."
)
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class LLMError(RuntimeError):
    """Raised when the model cannot produce output that validates, even after repair."""


def _extract_json(text: str) -> dict:
    """Parse a JSON object out of model text, tolerating code fences / surrounding prose."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise
        return json.loads(m.group(0))


class LLMClient:
    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-pro",
        max_tokens: int = 1024,
        timeout: int = 60,
        client=None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:
            self._client = client
        else:
            from openai import OpenAI  # lazy: only needed for real calls

            self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    # --- single call seam (mock this in tests) ----------------------------- #
    def _chat(self, messages: list[dict], max_tokens: int, temperature: float,
              json_mode: bool = False) -> str:
        kwargs: dict = dict(
            model=self.model, messages=messages,
            max_tokens=max_tokens, temperature=temperature, stream=False,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def _chat_stream(self, messages: list[dict], max_tokens: int, temperature: float,
                     on_reasoning: Callable[[str], None], json_mode: bool = False) -> str:
        """Streaming call in THINKING mode: reasoning tokens go to `on_reasoning` as they
        arrive; the visible answer is accumulated and returned. Validated live against the
        DeepSeek API — reasoning_content and a json_object body coexist (see thinking docs)."""
        kwargs: dict = dict(
            model=self.model, messages=messages,
            max_tokens=max_tokens, temperature=temperature, stream=True,
            reasoning_effort="high", extra_body={"thinking": {"type": "enabled"}},
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        content = ""
        for chunk in self._client.chat.completions.create(**kwargs):
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                try:
                    on_reasoning(rc)
                except Exception:  # a display sink must never break the model call
                    pass
                continue
            piece = getattr(delta, "content", None)
            if piece:
                content += piece
        return content

    # --- public API -------------------------------------------------------- #
    def complete(
        self,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ):
        """Text reply (schema=None) or a schema-validated dict (schema=Model).

        Pass `on_reasoning` to stream the model's chain-of-thought (thinking mode): each
        reasoning token chunk is handed to the callback as it arrives, while the final
        answer is still returned/validated exactly as in the non-streaming path.
        """
        mt = max_tokens or self.max_tokens
        base = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if schema is None:
            if on_reasoning is not None:
                return self._chat_stream(base, mt, temperature, on_reasoning, json_mode=False)
            return self._chat(base, mt, temperature)

        messages = [
            {"role": "system", "content": system + _JSON_INSTRUCTION},
            {"role": "user", "content": user},
        ]
        if on_reasoning is not None:
            text = self._chat_stream(messages, mt, temperature, on_reasoning, json_mode=True)
        else:
            text = self._chat(messages, mt, temperature, json_mode=True)
        return self._validate_or_repair(messages, text, schema, mt, temperature)

    def _validate_or_repair(self, messages: list[dict], text: str, schema: Type[BaseModel],
                            max_tokens: int, temperature: float) -> dict:
        try:
            return schema.model_validate(_extract_json(text)).model_dump()
        except (json.JSONDecodeError, ValidationError) as first_err:
            # ONE repair attempt: show the model exactly what was wrong (non-streaming —
            # the reasoning, if any, has already been shown).
            repair = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": (
                    f"Your previous response was not valid for the required schema:\n{first_err}\n"
                    "Reply again with ONLY the corrected JSON object."
                )},
            ]
            text2 = self._chat(repair, max_tokens, temperature, json_mode=True)
            try:
                return schema.model_validate(_extract_json(text2)).model_dump()
            except (json.JSONDecodeError, ValidationError) as second_err:
                raise LLMError(
                    f"LLM output failed schema {schema.__name__} validation after one "
                    f"repair retry: {second_err}. Last raw output: {text2[:400]!r}"
                ) from second_err
