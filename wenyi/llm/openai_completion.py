"""OpenAI Chat Completions protocol client shared by compatible providers."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from .adapters import get_adapter
from .base import LLMClientBase
from .retry import RetryConfig, retry
from .schema import LLMResponse, Message


class OpenAICompletionClient(LLMClientBase):
    """Shared API client for providers exposing Chat Completions."""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        reasoning_effort: str,
        retry_config: RetryConfig | None = None,
        *,
        provider: str = "openai_compatible",
        options: dict[str, Any] | None = None,
        client: OpenAI | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            model=model,
            reasoning_effort=reasoning_effort,
            retry_config=retry_config or RetryConfig(),
        )
        self.provider = provider
        self.options = options or {}
        self.client = client or OpenAI(api_key=api_key, base_url=api_base)

    def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> LLMResponse:
        adapter = get_adapter(self.provider)
        api_messages = [adapter.encode_message(message) for message in messages]
        api_tools = [adapter.encode_tool(tool) for tool in tools] if tools else None

        params: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
        }
        if api_tools:
            params["tools"] = api_tools
        params.update(
            adapter.request_params(
                self.reasoning_effort,
                self.options,
                model=self.model,
            )
        )

        response = self._call_with_retry(params)
        return adapter.parse_response(response)

    def _call_with_retry(self, params: dict[str, Any]) -> Any:
        api_call = self._make_api_request
        if self.retry_config.enabled:
            api_call = retry(
                config=self.retry_config,
                on_retry=self.retry_callback,
            )(api_call)
        return api_call(params)

    def _make_api_request(self, params: dict[str, Any]) -> Any:
        return self.client.chat.completions.create(**params)

    @staticmethod
    def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
        """Compatibility helper for callers of the previous client."""

        adapter = get_adapter("openai_compatible")
        return [adapter.encode_message(message) for message in messages]

    @staticmethod
    def _convert_tools(tools: list[Any]) -> list[dict[str, Any]]:
        """Compatibility helper for callers of the previous client."""

        adapter = get_adapter("openai_compatible")
        return [adapter.encode_tool(tool) for tool in tools]


# Existing imports can migrate incrementally.
OpenAICompatibleClient = OpenAICompletionClient

__all__ = ["OpenAICompatibleClient", "OpenAICompletionClient"]
