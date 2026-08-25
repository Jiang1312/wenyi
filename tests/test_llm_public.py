from wenyi.llm import (
    LLMClient,
    LLMProvider,
    LLMResponse,
    Message,
    ReasoningEffort,
    RetryConfig,
    TokenUsage,
)
from wenyi.llm.providers.openai_compatible import OpenAICompatibleClient


def test_public_llm_models_match_mini_agent_shape():
    message = Message(role="user", content="hello")
    response = LLMResponse(
        content="你好",
        thinking="先判断语言",
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )

    assert message.role == "user"
    assert response.thinking == "先判断语言"
    assert response.usage is not None
    assert response.usage.total_tokens == 3


def test_llm_client_stores_public_configuration():
    client = LLMClient(
        api_key="test-key",
        provider=LLMProvider.OPENAI_COMPATIBLE,
        api_base="https://example.test/",
        model="test-model",
        reasoning_effort=ReasoningEffort.MEDIUM,
        retry_config=RetryConfig(enabled=False),
    )

    assert client.provider is LLMProvider.OPENAI_COMPATIBLE
    assert client.api_base == "https://example.test"
    assert client.reasoning_effort is ReasoningEffort.MEDIUM
    assert not client.retry_config.enabled


def test_llm_client_routes_openai_compatible_provider():
    client = LLMClient(
        api_key="test-key",
        provider=LLMProvider.OPENAI_COMPATIBLE,
        api_base="https://example.test",
        model="test-model",
    )

    assert isinstance(client._client, OpenAICompatibleClient)
