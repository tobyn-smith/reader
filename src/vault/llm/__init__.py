"""the only module allowed to know a model vendor exists.

if any sdk import shows up outside this package, the isolation is broken. with
no key configured the factory returns the null adapter, which reports that
nothing was generated instead of raising, so every other feature keeps working
untouched.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class Completion:
    text: str | None
    model: str | None
    generated: bool
    reason: str = ""


class Adapter:
    name = "base"

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def complete(self, prompt: str, *, max_tokens: int = 2000) -> Completion:
        raise NotImplementedError


class NullAdapter(Adapter):
    """what runs when no key is set, which is the default and the tested path."""

    name = "null"

    @property
    def available(self) -> bool:
        return False

    def complete(self, prompt: str, *, max_tokens: int = 2000) -> Completion:
        return Completion(
            text=None,
            model=None,
            generated=False,
            reason="no model configured, so nothing was generated",
        )


class AnthropicAdapter(Adapter):
    name = "anthropic"

    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self._api_key = api_key

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def complete(self, prompt: str, *, max_tokens: int = 2000) -> Completion:
        try:
            import anthropic
        except ImportError:
            return Completion(None, None, False, "anthropic sdk is not installed")

        try:
            client = anthropic.Anthropic(api_key=self._api_key)
            message = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in message.content if block.type == "text")
            return Completion(text, self.model, True)
        except Exception as error:
            return Completion(None, None, False, f"model call failed: {error}")


def get_adapter() -> Adapter:
    provider = os.environ.get("VAULT_LLM_PROVIDER", "").strip().lower()
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("VAULT_LLM_MODEL", "claude-sonnet-5")
        if key:
            return AnthropicAdapter(model, key)
    return NullAdapter()


def load_prompt(name: str) -> str:
    path = PROMPTS / f"{name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""
