import pytest
from pydantic import BaseModel

from prd_to_readout.llm import LLMClient, LLMError, _friendly, extract_json, strip_code_fence


class _Schema(BaseModel):
    a: int


def test_complete_json_raises_llmerror_on_persistent_bad_output():
    # A weak model that never returns valid JSON should surface a clean LLMError
    # (caught by the CLI), not a bare ValueError traceback.
    class BadClient(LLMClient):
        def complete(self, system, user, *, temperature=None):
            return "sorry, I cannot do that"

    with pytest.raises(LLMError, match="schema"):
        BadClient("test/model").complete_json("sys", "usr", _Schema, max_retries=1)


def test_friendly_auth_error_is_clean_and_actionable():
    err = _friendly("claude-sonnet-4-6", Exception("AuthenticationError: Missing Anthropic API Key"))
    assert isinstance(err, LLMError)
    msg = str(err)
    assert "claude-sonnet-4-6" in msg
    assert "API key" in msg or "api key" in msg.lower()


def test_friendly_generic_error_preserves_cause():
    err = _friendly("gpt-4o", Exception("connection timeout"))
    assert "timeout" in str(err)


def test_extract_json_from_fenced_block():
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('here you go: {"a": 1} thanks') == '{"a": 1}'


def test_strip_code_fence_passthrough():
    assert strip_code_fence("SELECT 1") == "SELECT 1"
    assert strip_code_fence("```sql\nSELECT 1\n```") == "SELECT 1"
