"""Agent Loop 工具协议。

职责：定义工具箱和工具结果的最小通用协议。
具体工具的业务含义、草稿状态和最终校验由具体任务实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolResult:
    """一次工具调用返回给模型的结果。

    ``output`` 非空表示该工具已经产生任务的最终结果，Runner 将结束循环。
    """

    message: str
    output: Any | None = None


class ToolBox(Protocol):
    """一次任务可用工具的注册和执行接口。"""

    @property
    def definitions(self) -> list[Any]:
        """返回传给 LLM 的工具定义。"""
        ...

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """执行指定工具并返回工具结果。"""
        ...
