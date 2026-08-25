"""Runner 输入协议。

职责：定义 Runner 接收的通用任务输入接口，以及任务输入读取器的协议。
本模块不从 State 读取章节或 batch；State 读取逻辑位于 ``state_reader``。
"""

from __future__ import annotations

from typing import Any, Protocol

from .task import TaskInput


class TaskInputReader(Protocol):
    """根据具体任务的读取要求，从 State 组装一个 TaskInput。"""

    def read(self, request: Any) -> TaskInput:
        """读取任务所需信息。"""
        ...
