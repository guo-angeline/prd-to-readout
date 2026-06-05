"""Provider-agnostic LLM access via LiteLLM.

Agents depend only on the small surface here (``complete`` / ``complete_json``),
so tests can swap in a stub client and CI never needs an API key.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json|sql)?\s*(.*?)```", re.DOTALL)


class LLMError(RuntimeError):
    """A user-facing problem talking to the model provider (shown without a traceback)."""


def _friendly(model: str, e: Exception) -> LLMError:
    msg = str(e)
    low = msg.lower()
    name = type(e).__name__.lower()
    if "auth" in name or "api key" in low or "api_key" in low or "no api key" in low:
        return LLMError(
            f"Could not authenticate to the provider for model '{model}'.\n"
            "Set the matching API key (e.g. ANTHROPIC_API_KEY or OPENAI_API_KEY) in your "
            "environment or .env, or point P2R_MODEL at a local model (e.g. ollama/llama3.1)."
        )
    return LLMError(f"LLM request failed for model '{model}': {msg}")


def strip_code_fence(text: str) -> str:
    """Return the inside of the first ``` fenced block, or the text unchanged."""
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def extract_json(text: str) -> str:
    """Best-effort pull of a JSON object/array out of a model response."""
    inner = strip_code_fence(text)
    if inner and inner[0] in "{[":
        return inner
    # Fall back to the first {...} / [...] span in the raw text.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if 0 <= start < end:
            return text[start : end + 1]
    return inner


class LLMClient:
    """Thin LiteLLM wrapper. Defaults to deterministic (temperature 0) output."""

    def __init__(self, model: str, *, temperature: float = 0.0):
        self.model = model
        self.temperature = temperature

    def _is_anthropic(self) -> bool:
        m = self.model.lower()
        return "claude" in m or m.startswith("anthropic/")

    def complete(self, system: str, user: str, *, temperature: float | None = None) -> str:
        import litellm  # imported lazily so the package loads without a key

        system_content: object = system
        if self._is_anthropic():
            # Cache the (large, reused) system prompt to cut cost on repeated calls.
            system_content = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        try:
            resp = litellm.completion(
                model=self.model,
                temperature=self.temperature if temperature is None else temperature,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:  # noqa: BLE001 - surface as a clean, user-facing error
            raise _friendly(self.model, e) from e
        return resp["choices"][0]["message"]["content"]

    def complete_json(
        self, system: str, user: str, schema: type[T], *, max_retries: int = 2
    ) -> T:
        """Complete, parse JSON, and validate against ``schema``.

        On parse/validation failure the error is fed back to the model and the
        call retried, so transient malformed output self-heals.
        """
        prompt = user
        last_err = ""
        for _ in range(max_retries + 1):
            raw = self.complete(system, prompt)
            try:
                data = json.loads(extract_json(raw))
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                last_err = str(e)
                prompt = (
                    f"{user}\n\nYour previous response failed validation:\n{last_err}\n"
                    "Return ONLY valid JSON matching the requested schema."
                )
        raise LLMError(
            f"Model '{self.model}' kept returning output that did not match the expected "
            f"schema after {max_retries + 1} tries. Last error: {last_err}\n"
            "Try a more capable model (e.g. a Claude or GPT model via P2R_MODEL); small "
            "local models often struggle to emit valid structured JSON."
        )
