"""Provider 无关的公开 LLMClient 包装器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import LLMClientBase
from .providers.openai_compatible import OpenAICompatibleClient
from .retry import RetryConfig
from .schema import LLMProvider, LLMResponse, Message, ReasoningEffort


class LLMClient:
    """Runner 使用的统一 LLM 入口。"""

    def __init__(
        self,
        api_key: str,
        provider: LLMProvider,
        api_base: str,
        model: str,
        reasoning_effort: ReasoningEffort = ReasoningEffort.NONE,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.retry_config = retry_config or RetryConfig()

        if provider == LLMProvider.OPENAI_COMPATIBLE:
            self._client: LLMClientBase | None = OpenAICompatibleClient(
                api_key=api_key,
                api_base=self.api_base,
                model=model,
                reasoning_effort=reasoning_effort.value,
                retry_config=self.retry_config,
            )
        elif provider == LLMProvider.ANTHROPIC:
            raise NotImplementedError("AnthropicClient 尚未接入")
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    @property
    def retry_callback(self) -> Callable[..., Any] | None:
        """读取内部 ProviderClient 的重试回调。"""
        return self._client.retry_callback if self._client is not None else None

    @retry_callback.setter
    def retry_callback(self, value: Callable[..., Any] | None) -> None:
        """设置内部 ProviderClient 的重试回调。"""
        if self._client is not None:
            self._client.retry_callback = value

    def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> LLMResponse:
        """向内部 ProviderClient 转发一次生成请求。"""
        if self._client is None:
            raise RuntimeError("LLMClient 没有可用的 ProviderClient")
        return self._client.generate(messages, tools)
