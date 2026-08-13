import json

from repopilot.llm.deepseek import DeepSeekConfig
from repopilot.models import Evidence
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
    assert decision.context_trace is not None
    assert decision.context_trace.phase == "decision"
    assert captured["tool_choice"] == "required"
    assert captured["thinking"] == {"type": "disabled"}
    search_schema = next(
        tool for tool in captured["tools"] if tool["function"]["name"] == "search_code"
    )
    assert "reason" in search_schema["function"]["parameters"]["required"]


def test_policy_forces_finish_on_last_step_and_normalizes_missing_reason(
    monkeypatch, sample_repo
) -> None:
    evidence = Evidence(
        path="agent.py",
        line_start=1,
        line_end=5,
        snippet="class ReActAgent",
        keyword="ReActAgent",
    )
    captured = {}

    def fake_post(config, payload):
        captured.update(payload)
        return {
            "model": "deepseek-test",
            "usage": {"prompt_tokens": 80, "completion_tokens": 30},
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "claims": [
                                    {
                                        "statement": (
                                            "ReActAgent exists in the cited source file."
                                        ),
                                        "evidence_ids": [evidence.id],
                                    }
                                ],
                                "limitations": ["Execution was not observed."],
                            }
                        )
                    }
                }
            ],
        }

    monkeypatch.setattr("repopilot.runtime.policy.post_chat_completion", fake_post)
    policy = DeepSeekToolPolicy(
        DeepSeekConfig("deepseek-test", "secret", "https://example.invalid", 5)
    )
    decision = policy.decide(
        AgentRun(
            repo_path=sample_repo,
            question="Where is ReActAgent?",
            max_steps=1,
            evidence=[evidence],
        ),
        ToolRegistry.readonly_default().schemas,
    )

    assert "tools" not in captured
    assert captured["response_format"] == {"type": "json_object"}
    assert decision.tool_name == "finish"
    assert decision.reason == "Finalize the investigation from collected evidence."
    assert decision.arguments["reason"] == decision.reason
    assert decision.prompt_tokens == 80
    assert decision.completion_tokens == 30
    assert decision.context_trace is not None
    assert decision.context_trace.phase == "finalizer"
