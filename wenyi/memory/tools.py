"""Memory task 的 Agent 工具。

工具只维护一次 Agent Loop 期间的 staged document，不直接写 State；最终结果由
MemoryWorkflow 返回给 Orchestrator，再由 StateStore 提交。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from ..runner.tools import ToolResult
from .schema import TopicDocument
from .task import MemoryTaskInput


class MemoryToolBox:
    """一次 memory task 的读取工具和 staged document 状态。"""

    definitions: ClassVar[list[dict[str, Any]]] = [
        {
            "type": "function",
            "function": {
                "name": "read_memory_document",
                "description": "读取一个已有 topic document 的完整内容。",
                "parameters": {
                    "type": "object",
                    "properties": {"document_id": {"type": "string"}},
                    "required": ["document_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_source_context",
                "description": "按全局 chapter + segment index 读取原文、译文及其上下文。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "indexes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "chapter": {"type": "integer"},
                                    "segment": {"type": "integer"},
                                },
                                "required": ["chapter", "segment"],
                            },
                        }
                    },
                    "required": ["indexes"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_memory_document",
                "description": "创建或替换一个完整的 topic document；只暂存，不直接写入 State。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "description": "已有 document 的 ID；为 null 时创建新 document。",
                        },
                        "summary": {"type": "string"},
                        "content": {
                            "type": "string",
                            "description": "完整的结构化 Markdown document，不是 patch。",
                        },
                    },
                    "required": ["document_id", "summary", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_memory",
                "description": "提交本次 memory task 中暂存的全部 document 修改。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    def __init__(
        self,
        task_input: MemoryTaskInput,
        *,
        document_reader: Callable[[str], TopicDocument],
        source_reader: Callable[[list[dict[str, int]]], str],
    ) -> None:
        self._task_input = task_input
        self._document_reader = document_reader
        self._source_reader = source_reader
        self._known_ids = {
            item.document_id for item in task_input.catalog if item.document_id is not None
        }
        self._staged: dict[str, TopicDocument] = {}
        self._created: list[TopicDocument] = []
        self._handlers: dict[str, Callable[..., ToolResult]] = {
            "read_memory_document": self.read_memory_document,
            "read_source_context": self.read_source_context,
            "write_memory_document": self.write_memory_document,
            "submit_memory": self.submit_memory,
        }

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"未知 Tool：{name}")
        return handler(**arguments)

    def read_memory_document(self, document_id: str) -> ToolResult:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id 必须是非空字符串")
        if document_id in self._staged:
            document = self._staged[document_id]
        else:
            document = self._document_reader(document_id)
        if document.content is None:
            raise ValueError("读取到的 topic document 缺少 content")
        return ToolResult(
            message=json_message(
                {
                    "document_id": document.document_id,
                    "summary": document.summary,
                    "content": document.content,
                }
            )
        )

    def read_source_context(self, indexes: list[dict[str, int]]) -> ToolResult:
        if not isinstance(indexes, list) or not indexes:
            raise ValueError("indexes 必须是非空 list")
        return ToolResult(message=self._source_reader(indexes))

    def write_memory_document(
        self,
        document_id: str | None,
        summary: str,
        content: str,
    ) -> ToolResult:
        if document_id is not None:
            if not isinstance(document_id, str) or not document_id.strip():
                raise ValueError("document_id 必须是非空字符串或 null")
            if document_id not in self._known_ids and document_id not in self._staged:
                raise ValueError(f"未知 topic document：{document_id}")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary 不能为空")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content 不能为空")
        document = TopicDocument(document_id, summary.strip(), content.strip())
        if document_id is None:
            self._created.append(document)
        else:
            self._staged[document_id] = document
        return ToolResult(message="topic document 修改已暂存")

    def submit_memory(self) -> ToolResult:
        writes = list(self._staged.values()) + list(self._created)
        return ToolResult(
            message=f"memory 已提交，共 {len(writes)} 个 document 修改",
            output={
                "writes": [
                    {
                        "document_id": item.document_id,
                        "summary": item.summary,
                        "content": item.content,
                    }
                    for item in writes
                ]
            },
        )


def json_message(value: dict[str, Any]) -> str:
    """以稳定 JSON 返回 document 内容，便于模型继续处理。"""

    import json

    return json.dumps(value, ensure_ascii=False, indent=2)

