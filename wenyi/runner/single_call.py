"""Single Call 工作模式的最小骨架。

未来实现本 Runner 时，应与 AgentLoopRunner 使用同一套 trace 写入约定，接收可选的
trace writer，记录一次模型调用、结果和 usage；本文件不自行定义另一套日志格式。
"""

from __future__ import annotations

from typing import Any

from .task import TaskInput, TaskOutput


class SingleCallRunner:
    """使用一次 LLM 调用完成任务的执行器。"""

    def __init__(self, client: Any | None = None) -> None:
        # 具体的 LLMClient、prompt、解析器和校验器等在 LLM 模块确认后接入。
        self.client = client

    def run(self, task_input: TaskInput) -> TaskOutput:
        """执行一个任务；具体翻译逻辑将在后续阶段实现。"""
        raise NotImplementedError
