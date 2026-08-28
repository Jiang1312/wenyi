"""Tencent Hunyuan dialect for the OpenAI Chat Completions protocol."""

from __future__ import annotations

from typing import Any

from . import openai

encode_message = openai.encode_message
encode_tool = openai.encode_tool
extract_thinking = openai.extract_thinking
parse_response = openai.parse_response


def request_params(
    reasoning_effort: str,
    options: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Pass explicitly configured Hunyuan extensions without guessing semantics."""

    del model, reasoning_effort
    return dict(options)
