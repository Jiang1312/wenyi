"""任务级别的统一输入、输出协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TaskInput:
    """已经准备好的任务输入，不负责自己从 State 读取数据。"""

    task_id: str
    task_type: str
    source: Any
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TaskOutput:
    """一次任务执行的统一结果。"""

    task_id: str
    task_type: str
    is_success: bool
    result: Any | None
    error_message: str | None
    usage: dict[str, Any]


@runtime_checkable
class TaskRunner(Protocol):
    """Single Call 和 Agent Loop 共同遵守的最小执行接口。"""

    def run(self, task_input: TaskInput, **kwargs: Any) -> TaskOutput:
        ...
