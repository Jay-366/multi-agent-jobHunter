"""Central config: loads config.yaml + .env, exposes settings + make_llm().

This is the single loader (there is no src/config/ folder). Values you edit live in
config.yaml at the repo root; the secret lives in .env. Nothing else in the app reads
those files directly — everything goes through `settings`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"

# Load .env from the repo root (no-op if missing).
load_dotenv(ROOT / ".env")


class Settings:
    """Typed-ish view over config.yaml + environment."""

    def __init__(self, data: dict):
        self._data = data or {}
        self.llm: dict = self._data.get("llm", {})
        self.discovery: dict = self._data.get("discovery", {})
        self.scoring: dict = self._data.get("scoring", {})
        self.analyst: dict = self._data.get("analyst", {})

    @property
    def deepseek_api_key(self) -> str:
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        return key

    def model_name(self, tier: str = "pro") -> str:
        return self.llm.get("models", {}).get(tier, tier)

    def max_tokens(self, tier: str = "pro") -> int:
        return int(self.llm.get("max_tokens", {}).get(tier, 1024))

    def make_llm(self, model: str = "pro"):
        """Build an LLMClient for the given tier ('pro' | 'flash')."""
        from src.services.llm_client import LLMClient  # lazy: avoids importing openai at config import

        return LLMClient(
            api_key=self.deepseek_api_key,
            base_url=self.llm.get("base_url", "https://api.deepseek.com"),
            model=self.model_name(model),
            max_tokens=self.max_tokens(model),
            timeout=int(self.llm.get("timeout", 60)),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Settings(data)


# Convenience singleton for `from src.config import settings`.
settings = get_settings()
