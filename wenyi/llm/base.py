"""Provider Client 的最小公共接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .retry import RetryConfig
from .schema import LLMResponse, Message


class LLMClientBase(ABC):
    """具体 ProviderClient 未来需要实现的接口。"""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        reasoning_effort: str,
        retry_config: RetryConfig,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.retry_config = retry_config
        self.retry_callback = None

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> LLMResponse:
        """调用 Provider 并返回统一响应。"""
        raise NotImplementedError
