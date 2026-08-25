"""OpenAI-compatible Chat Completions format ProviderClient。"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from ..base import LLMClientBase
from ..retry import RetryConfig, retry
from ..schema import FunctionCall, LLMResponse, Message, TokenUsage, ToolCall


class OpenAICompatibleClient(LLMClientBase):
    """使用 OpenAI-compatible Chat Completions 接口的同步客户端。"""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        reasoning_effort: str,
        retry_config: RetryConfig,
        *,
        client: OpenAI | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            model=model,
            reasoning_effort=reasoning_effort,
            retry_config=retry_config,
        )
        self.client = client or OpenAI(api_key=api_key, base_url=api_base)

    def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools) if tools else None

        api_call = self._make_api_request
        if self.retry_config.enabled:
            api_call = retry(
                config=self.retry_config,
                on_retry=self.retry_callback,
            )(api_call)

        response = api_call(api_messages, api_tools)
        return self._parse_response(response)

    def _make_api_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Any:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "extra_body": {"reasoning_split": True},
        }

        if tools:
            params["tools"] = tools
        if self.reasoning_effort != "none":
            params["reasoning_effort"] = self.reasoning_effort

        return self.client.chat.completions.create(**params)

    @staticmethod
    def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []

        for message in messages:
            if message.role == "system":
                api_messages.append(
                    {"role": "system", "content": message.content}
                )
                continue

            if message.role == "user":
                api_messages.append({"role": "user", "content": message.content})
                continue

            if message.role == "assistant":
                assistant_message: dict[str, Any] = {"role": "assistant"}
                if message.content:
                    assistant_message["content"] = message.content

                if message.tool_calls:
                    assistant_message["tool_calls"] = [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": json.dumps(
                                    tool_call.function.arguments,
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for tool_call in message.tool_calls
                    ]

                if message.thinking:
                    assistant_message["reasoning_details"] = [
                        {"text": message.thinking}
                    ]

                api_messages.append(assistant_message)
                continue

            if message.role == "tool":
                api_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )

        return api_messages

    @staticmethod
    def _convert_tools(tools: list[Any]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools:
            if isinstance(tool, dict):
                if tool.get("type") == "function":
                    converted.append(tool)
                else:
                    converted.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool["description"],
                                "parameters": tool["input_schema"],
                            },
                        }
                    )
                continue

            if hasattr(tool, "to_openai_compatible_schema"):
                converted.append(tool.to_openai_compatible_schema())
                continue

            raise TypeError(f"Unsupported tool type: {type(tool)}")

        return converted

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message

        thinking = ""
        for detail in getattr(message, "reasoning_details", None) or []:
            if isinstance(detail, dict):
                thinking += detail.get("text", "")
            else:
                thinking += getattr(detail, "text", "") or ""

        tool_calls: list[ToolCall] = []
        for tool_call in getattr(message, "tool_calls", None) or []:
            tool_calls.append(
                ToolCall(
                    id=tool_call.id,
                    type=tool_call.type,
                    function=FunctionCall(
                        name=tool_call.function.name,
                        arguments=json.loads(tool_call.function.arguments or "{}"),
                    ),
                )
            )

        usage = None
        if response.usage is not None:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        return LLMResponse(
            content=message.content or "",
            thinking=thinking or None,
            tool_calls=tool_calls or None,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )
