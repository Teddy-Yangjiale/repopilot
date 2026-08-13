import json

from repopilot.llm.deepseek import DeepSeekConfig
from repopilot.runtime.models import AgentRun
from repopilot.runtime.policy import DeepSeekToolPolicy
from repopilot.runtime.tooling import ToolRegistry


def test_deepseek_policy_parses_native_tool_call(monkeypatch, sample_repo) -> None:
    captured = {}

    def fake_post(config, payload):
        captured.update(payload)
        return {
            "model": "deepseek-test",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "search_code",
                                    "arguments": json.dumps(
                                        {"keyword": "ReActAgent", "reason": "locate it"}
                                    ),
                                }
                            }
                        ]
                    }
                }
            ],
        }

    monkeypatch.setattr("repopilot.runtime.policy.post_chat_completion", fake_post)
    policy = DeepSeekToolPolicy(
        DeepSeekConfig("deepseek-test", "secret", "https://example.invalid", 5)
    )
    decision = policy.decide(
        AgentRun(repo_path=sample_repo, question="Where is ReActAgent?"),
        ToolRegistry.readonly_default().schemas,
    )

    assert decision.tool_name == "search_code"
    assert decision.arguments["keyword"] == "ReActAgent"
    assert decision.reason == "locate it"
    assert decision.prompt_tokens == 100
    assert decision.completion_tokens == 20
    assert captured["tool_choice"] == "required"
    assert captured["thinking"] == {"type": "disabled"}
    search_schema = next(
        tool for tool in captured["tools"] if tool["function"]["name"] == "search_code"
    )
    assert "reason" in search_schema["function"]["parameters"]["required"]
