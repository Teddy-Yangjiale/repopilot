from __future__ import annotations

import json
import urllib.error

import pytest

from repopilot.llm.deepseek import DeepSeekConfig, DeepSeekKeywordGenerator
from repopilot.query_expansion import LLMConfigurationError, parse_keyword_json


def make_config(**overrides: object) -> DeepSeekConfig:
    defaults = dict(
        model="deepseek-test",
        api_key="sk-test-123",
        base_url="https://api.deepseek.com",
        timeout=30,
    )
    return DeepSeekConfig(**{**defaults, **overrides})


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def openai_response(content: str, model: str = "deepseek-test") -> bytes:
    return json.dumps(
        {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
        }
    ).encode("utf-8")


def test_generator_sends_chat_completions_request(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            openai_response('{"keywords":["ToolRegistry", "invoke_with_tools"]}')
        )

    import repopilot.llm.deepseek as module

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    result = DeepSeekKeywordGenerator(config=make_config()).generate(
        "How does ReActAgent call tools?"
    )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["method"] == "POST"
    assert captured["headers"]["authorization"] == "Bearer sk-test-123"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["payload"]["model"] == "deepseek-test"
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["max_tokens"] == 300
    assert captured["payload"]["messages"][0]["role"] == "system"
    question = captured["payload"]["messages"][1]["content"]
    assert "<question>How does ReActAgent call tools?</question>" in question
    assert result.keywords == ["ToolRegistry", "invoke_with_tools"]
    assert result.model == "deepseek-test"
    assert result.latency_ms >= 0


def test_generator_parses_fenced_json(monkeypatch) -> None:
    import repopilot.llm.deepseek as module

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(
            openai_response('```json\n{"keywords":["Finish"]}\n```')
        ),
    )

    result = DeepSeekKeywordGenerator(config=make_config()).generate("when to stop?")

    assert result.keywords == ["Finish"]


def test_generator_rejects_non_json_body(monkeypatch) -> None:
    import repopilot.llm.deepseek as module

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(b"<html>gateway error</html>"),
    )

    with pytest.raises(ValueError, match="non-JSON"):
        DeepSeekKeywordGenerator(config=make_config()).generate("question")


def test_generator_maps_401_to_configuration_error(monkeypatch) -> None:
    import repopilot.llm.deepseek as module

    def forbidden(request, timeout):
        raise urllib.error.HTTPError(
            "https://api.deepseek.com/chat/completions", 401, "Unauthorized", {}, None
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", forbidden)

    with pytest.raises(LLMConfigurationError, match="401"):
        DeepSeekKeywordGenerator(config=make_config()).generate("question")


def test_config_from_env_requires_real_key(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        DeepSeekConfig.from_env()

    monkeypatch.setenv("LLM_API_KEY", "your-deepseek-api-key")
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        DeepSeekConfig.from_env()

    monkeypatch.setenv("LLM_API_KEY", "sk-real")
    config = DeepSeekConfig.from_env()
    assert config.model == "deepseek-v4-flash"
    assert config.base_url == "https://api.deepseek.com"


def test_keyword_json_parser_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="string array"):
        parse_keyword_json('{"keywords": "not-a-list"}')
