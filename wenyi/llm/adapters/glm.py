"""GLM dialect for the OpenAI Chat Completions protocol."""

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
    """Apply GLM's current thinking and reasoning-effort mapping."""

    model_name = (model or "").lower()
    is_glm53 = "glm-5.3" in model_name

    if is_glm53 and reasoning_effort in {"none", "minimal"}:
        raise ValueError("GLM-5.3/GLM-5.3-FLASH 不支持关闭 thinking")

    if reasoning_effort in {"none", "minimal"} and not is_glm53:
        mapped_effort = "none"
        thinking_type = "disabled"
    else:
        mapped_effort = {
            # GLM-5.3/FLASH supports low, high and max directly.
            "low": "low" if is_glm53 else "high",
            "medium": "high",
            "high": "high",
            "xhigh": "max",
            "max": "max",
        }.get(reasoning_effort, reasoning_effort)
        thinking_type = "enabled"

    params: dict[str, Any] = {
        "reasoning_effort": mapped_effort,
        "extra_body": {
            "thinking": {
                "type": thinking_type,
            }
        },
    }
    return openai.merge_options(params, options)


def parse_response(response: Any) -> Any:
    return openai.parse_response(
        response,
        extract_thinking_fn=extract_thinking,
    )
