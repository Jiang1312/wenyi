"""Memory task 的输入、输出契约。

本模块只定义任务层的数据，不读取 State、不调用 LLM，也不执行工具。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import TopicDocument


@dataclass(frozen=True)
class MemoryTaskInput:
    """一次 memory consolidation loop 的初始视野。"""

    current: str
    catalog: list[TopicDocument] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryTaskOutput:
    """Memory agent 提交的 topic document 完整版本。"""

    writes: list[TopicDocument] = field(default_factory=list)

