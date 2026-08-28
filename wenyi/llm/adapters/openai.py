"""Default OpenAI Chat Completions request/response behavior."""

from __future__ import annotations

import json
from typing import Any

from ..schema import FunctionCall, LLMResponse, Message, TokenUsage, ToolCall


def encode_message(message: Message) -> dict[str, Any]:
    """Convert one public Message to the standard Chat Completions shape."""

    if message.role in {"system", "user"}:
        return {"role": message.role, "content": message.content}

    if message.role == "assistant":
        result: dict[str, Any] = {"role": "assistant"}
        if message.content:
            result["content"] = message.content
        if message.thinking:
            result["reasoning_content"] = message.thinking
        if message.tool_calls:
            result["tool_calls"] = [
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
        return result

    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }

    raise ValueError(f"Unsupported message role: {message.role}")


def encode_tool(tool: Any) -> dict[str, Any]:
    """Convert a Wenyi or OpenAI-shaped tool definition."""

    if isinstance(tool, dict):
        if tool.get("type") == "function":
            return tool
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }

    if hasattr(tool, "to_openai_compatible_schema"):
        return tool.to_openai_compatible_schema()

    raise TypeError(f"Unsupported tool type: {type(tool)}")


def request_params(
    reasoning_effort: str,
    options: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Return standard request parameters and explicit user options."""

    del model
    params: dict[str, Any] = {}
    if reasoning_effort not in {"none", "minimal"}:
        params["reasoning_effort"] = reasoning_effort
    params.update(options)
    return params


def merge_options(
    params: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    """Merge SDK options while preserving nested extension defaults."""

    def merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        result = dict(left)
        for key, value in right.items():
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = merge(result[key], value)
            else:
                result[key] = value
        return result

    return merge(params, options)


def extract_thinking(message: Any) -> str | None:
    """Read the standard reasoning content field."""

    value = message.get("reasoning_content") if isinstance(message, dict) else getattr(
        message, "reasoning_content", None
    )
    return value if isinstance(value, str) and value else None


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _parse_tool_call(tool_call: Any) -> ToolCall:
    call_type = _get(tool_call, "type", "function")
    if call_type != "function":
        raise ValueError(f"Unsupported tool call type: {call_type}")

    function = _get(tool_call, "function")
    arguments = _get(function, "arguments", "{}")
    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}")
    if not isinstance(arguments, dict):
        raise TypeError("Tool call arguments must be a JSON object")

    return ToolCall(
        id=_get(tool_call, "id", ""),
        type=call_type,
        function=FunctionCall(
            name=_get(function, "name", ""),
            arguments=arguments,
        ),
    )


def parse_response(
    response: Any,
    *,
    extract_thinking_fn=extract_thinking,
) -> LLMResponse:
    """Parse the common completion envelope into the public response model."""

    choices = _get(response, "choices") or []
    if not choices:
        raise ValueError("Completion response has no choices")

    choice = choices[0]
    message = _get(choice, "message")
    content = _get(message, "content")
    tool_calls = [
        _parse_tool_call(tool_call)
        for tool_call in (_get(message, "tool_calls") or [])
    ]

    usage_object = _get(response, "usage")
    usage = None
    if usage_object is not None:
        usage = TokenUsage(
            prompt_tokens=_get(usage_object, "prompt_tokens", 0) or 0,
            completion_tokens=_get(usage_object, "completion_tokens", 0) or 0,
            total_tokens=_get(usage_object, "total_tokens", 0) or 0,
        )

    return LLMResponse(
        content=content if isinstance(content, str) else "",
        thinking=extract_thinking_fn(message),
        tool_calls=tool_calls or None,
        finish_reason=_get(choice, "finish_reason") or "stop",
        usage=usage,
    )
