"""LLM 公共请求/响应模型，保持与 Mini-Agent 一致。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class LLMProvider(str, Enum):
    """支持的 LLM Provider。"""

    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"


class ReasoningEffort(str, Enum):
    """LLM 客户端要求的思考能力。"""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FunctionCall(BaseModel):
    """Tool 调用的函数信息。"""

    name: str
    arguments: dict[str, Any]


class ToolCall(BaseModel):
    """模型返回的 Tool 调用。"""

    id: str
    type: str
    function: FunctionCall


class Message(BaseModel):
    """Provider 无关的对话消息。"""

    role: str
    content: str | list[dict[str, Any]]
    thinking: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class TokenUsage(BaseModel):
    """一次 LLM 调用的 token 用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """一次 LLM 调用的统一响应。"""

    content: str
    thinking: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str
    usage: TokenUsage | None = None
