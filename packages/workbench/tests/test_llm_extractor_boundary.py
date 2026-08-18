from __future__ import annotations

import logging

from nlp.extraction import llm_extractor


def test_llm_backend_fallback_is_explicit_without_credentials(monkeypatch, caplog) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    caplog.set_level(logging.INFO, logger=llm_extractor.__name__)

    assert llm_extractor._try_llm_extract("short text") is None

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "fallback" in messages
    assert "returning no candidate" in messages


def test_llm_base_url_policy_rejects_query_before_network(monkeypatch, caplog) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1?token=secret")
    caplog.set_level(logging.WARNING, logger=llm_extractor.__name__)

    assert llm_extractor._try_openai_compatible("short text", model="test") is None

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "ValueError" in messages
    assert "secret" not in messages


def test_llm_openai_compatible_uses_owned_external_gateway(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 200
        content = b'{"choices":[{"message":{"content":"{\\"event_name\\":\\"x\\"}"}}]}'

    class _Gateway:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, endpoint_id, content, *, headers, timeout_sec):
            captured["endpoint_id"] = endpoint_id
            captured["content"] = content
            captured["headers"] = headers
            captured["timeout_sec"] = timeout_sec
            return _Response()

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(llm_extractor, "OwnedExternalHTTPGateway", lambda *_args, **_kwargs: _Gateway())

    result = llm_extractor._try_openai_compatible("short text", model="test")

    assert result == {"event_name": "x"}
    assert captured["endpoint_id"] == "llm_chat_completions"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer test-key",
    }


def test_llm_custom_host_requires_explicit_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.delenv("LLM_ALLOWED_HOSTS", raising=False)

    assert llm_extractor._try_openai_compatible("short text", model="test") is None
