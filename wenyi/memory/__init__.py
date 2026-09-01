"""Memory task：CURRENT、topic document 维护和后续检索的任务入口。"""

from .schema import TopicDocument
from .task import MemoryTaskInput, MemoryTaskOutput

__all__ = [
    "MemoryTaskInput",
    "MemoryTaskOutput",
    "MemoryWorkflow",
    "TopicDocument",
]


def __getattr__(name: str):
    """延迟导出 workflow，避免 StateStore 导入 schema 时形成循环依赖。"""

    if name == "MemoryWorkflow":
        from .workflow import MemoryWorkflow

        return MemoryWorkflow
    raise AttributeError(name)
