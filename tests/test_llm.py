from prd_to_readout.llm import LLMError, _friendly, extract_json, strip_code_fence


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
