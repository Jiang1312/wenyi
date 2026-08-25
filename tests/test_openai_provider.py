from types import SimpleNamespace
from unittest.mock import Mock

from wenyi.llm import Message, ReasoningEffort, RetryConfig
from wenyi.llm.providers.openai_compatible import OpenAICompatibleClient


def _response():
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="你好",
                    reasoning_details=[SimpleNamespace(text="先分析")],
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            type="function",
                            function=SimpleNamespace(
                                name="save_draft",
                                arguments='{"target": "你好"}',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )


def test_openai_compatible_client_converts_request_and_response():
    sdk_client = Mock()
    sdk_client.chat.completions.create.return_value = _response()
    provider = OpenAICompatibleClient(
        api_key="test-key",
        api_base="https://example.test/v1",
        model="test-model",
        reasoning_effort=ReasoningEffort.HIGH.value,
        retry_config=RetryConfig(enabled=False),
        client=sdk_client,
    )

    response = provider.generate(
        [Message(role="user", content="请翻译")],
        tools=[
            {
                "name": "save_draft",
                "description": "保存草稿",
                "input_schema": {"type": "object"},
            }
        ],
    )

    request = sdk_client.chat.completions.create.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["reasoning_effort"] == "high"
    assert request["tools"][0]["type"] == "function"
    assert response.content == "你好"
    assert response.thinking == "先分析"
    assert response.tool_calls[0].function.arguments == {"target": "你好"}
    assert response.usage.total_tokens == 15


def test_openai_compatible_client_retries_api_request():
    sdk_client = Mock()
    sdk_client.chat.completions.create.side_effect = [RuntimeError("temporary"), _response()]
    provider = OpenAICompatibleClient(
        api_key="test-key",
        api_base="https://example.test/v1",
        model="test-model",
        reasoning_effort=ReasoningEffort.NONE.value,
        retry_config=RetryConfig(max_retries=1, initial_delay=0, max_delay=0),
        client=sdk_client,
    )

    response = provider.generate([Message(role="user", content="请翻译")])

    assert response.content == "你好"
    assert sdk_client.chat.completions.create.call_count == 2
