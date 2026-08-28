from types import SimpleNamespace
from unittest.mock import Mock

from wenyi.llm import Message, RetryConfig
from wenyi.llm.adapters import deepseek, glm
from wenyi.llm.openai_completion import OpenAICompletionClient


def test_deepseek_thinking_parameters_follow_chat_completions_dialect():
    enabled = deepseek.request_params("high", {})
    disabled = deepseek.request_params("none", {})

    assert enabled["reasoning_effort"] == "high"
    assert enabled["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "reasoning_effort" not in disabled
    assert disabled["extra_body"] == {"thinking": {"type": "disabled"}}


def test_deepseek_xhigh_is_mapped_to_high_for_compatibility():
    params = deepseek.request_params("xhigh", {})

    assert params["reasoning_effort"] == "high"


def test_glm_maps_public_reasoning_effort_to_supported_values():
    assert glm.request_params("low", {})["reasoning_effort"] == "high"
    assert glm.request_params("medium", {})["reasoning_effort"] == "high"
    assert glm.request_params("xhigh", {})["reasoning_effort"] == "max"
    assert glm.request_params("none", {}) == {
        "reasoning_effort": "none",
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_glm_options_can_preserve_thinking_configuration():
    params = glm.request_params(
        "high",
        {"extra_body": {"thinking": {"clear_thinking": False}}},
    )

    assert params["extra_body"] == {
        "thinking": {
            "type": "enabled",
            "clear_thinking": False,
        }
    }


def test_glm53_uses_native_low_and_rejects_disabled_thinking():
    assert glm.request_params("low", {}, model="glm-5.3-flash")["reasoning_effort"] == "low"

    try:
        glm.request_params("none", {}, model="glm-5.3-flash")
    except ValueError as error:
        assert "不支持关闭 thinking" in str(error)
    else:
        raise AssertionError("GLM-5.3 should reject disabled thinking")


def test_openai_completion_client_routes_deepseek_adapter():
    sdk_client = Mock()
    sdk_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="答案",
                    reasoning_content="思考",
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    client = OpenAICompletionClient(
        provider="deepseek",
        api_key="test-key",
        api_base="https://example.test/v1",
        model="deepseek-reasoner",
        reasoning_effort="high",
        retry_config=RetryConfig(enabled=False),
        client=sdk_client,
    )

    response = client.generate([Message(role="user", content="问题")])

    request = sdk_client.chat.completions.create.call_args.kwargs
    assert request["reasoning_effort"] == "high"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert response.thinking == "思考"
