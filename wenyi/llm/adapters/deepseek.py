"""DeepSeek dialect for the OpenAI Chat Completions protocol."""

from __future__ import annotations

from typing import Any

from . import openai

encode_message = openai.encode_message
encode_tool = openai.encode_tool
extract_thinking = openai.extract_thinking


def request_params(
    reasoning_effort: str,
    options: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Enable DeepSeek thinking explicitly and map the public effort values."""

    del model
    params: dict[str, Any] = {
        "extra_body": {
            "thinking": {
                "type": "disabled"
                if reasoning_effort in {"none", "minimal"}
                else "enabled",
            }
        }
    }
    if reasoning_effort not in {"none", "minimal"}:
        params["reasoning_effort"] = {
            "low": "low",
            "medium": "high",
            "high": "high",
            # DeepSeek currently maps xhigh to high for compatibility.
            "xhigh": "high",
            "max": "max",
        }.get(reasoning_effort, reasoning_effort)

    return openai.merge_options(params, options)


def parse_response(response: Any) -> Any:
    return openai.parse_response(
        response,
        extract_thinking_fn=extract_thinking,
    )
