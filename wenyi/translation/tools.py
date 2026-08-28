"""翻译任务的 Agent 工具。

职责：持有一次翻译任务的临时 draft 和 consistency candidate，并提供 draft、candidate
和最终提交工具。本模块不写入 State；提交结果由外部流程负责持久化。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from ..consistency import find_exact_source_positions, normalize_source
from ..runner.tools import ToolResult
from .task import TranslationTaskInput, validate_translation_output


class TranslationToolBox:
    """一次翻译任务的工具集合和临时草稿状态。"""

    definitions: ClassVar[list[dict[str, Any]]] = [
        {
            "type": "function",
            "function": {
                "name": "save_draft",
                "description": (
                    "写入译文草稿。index 为空时必须提供完整译文列表并替换整个草稿；"
                    "index 有值时只更新对应的一项，index 从 1 开始。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "targets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "完整译文列表，或 index 模式下只包含一项译文。",
                        },
                        "index": {
                            "anyOf": [
                                {"type": "integer", "minimum": 1},
                                {"type": "null"},
                            ],
                            "description": "1-based 原文编号；为空时写入完整译文列表。",
                        },
                    },
                    "required": ["targets"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "record_consistency",
                "description": (
                    "批量记录当前 batch 中发现的、值得在长程翻译中保持固定译法的术语"
                    "禁止提交已有 consistency source；"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "candidates": {
                            "type": "array",
                            "description": "当前 batch 中值得长期保持一致的新译法列表。",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source": {
                                        "type": "string",
                                        "description": "当前 batch 中的新原文表达。",
                                    },
                                    "target": {
                                        "type": "string",
                                        "description": "该原文表达采用的译法。",
                                    },
                                },
                                "required": ["source", "target"],
                            },
                        },
                    },
                    "required": ["candidates"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_translation",
                "description": "提交当前完整译文草稿。只有提交成功后翻译任务才算完成。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    ]

    def __init__(
        self,
        task_input: TranslationTaskInput,
        *,
        existing_sources: set[str] | None = None,
    ) -> None:
        self._task_input = task_input
        self._existing_sources = (
            existing_sources
            if existing_sources is not None
            else {
                normalize_source(item["source"])
                for item in task_input.consistency
            }
        )
        self._draft: list[str] | None = None
        self._candidates: dict[str, dict[str, str]] = {}
        self._handlers: dict[str, Callable[..., ToolResult]] = {
            "save_draft": self.save_draft,
            "record_consistency": self.record_consistency,
            "submit_translation": self.submit_translation,
        }

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """按模型给出的工具名称分发调用。"""

        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"未知 Tool：{name}")
        return handler(**arguments)

    def save_draft(
        self,
        targets: list[str],
        index: int | None = None,
    ) -> ToolResult:
        """完整替换草稿，或按 1-based index 更新草稿中的一项。"""

        if not isinstance(targets, list):
            raise TypeError("targets 必须是 list")

        if index is None:
            validate_translation_output(self._task_input, targets)
            self._draft = list(targets)
            return ToolResult(message=f"草稿已保存，共 {len(targets)} 段")

        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("index 必须是整数或 null")
        if self._draft is None:
            raise ValueError("还没有完整草稿，请先在不传 index 的情况下保存草稿")
        if len(targets) != 1:
            raise ValueError("index 模式下 targets 必须只包含一项")
        if index < 1 or index > len(self._draft):
            raise ValueError(f"index 超出范围：必须在 1 到 {len(self._draft)} 之间")

        candidate = list(self._draft)
        candidate[index - 1] = targets[0]
        validate_translation_output(self._task_input, candidate)
        self._draft = candidate
        return ToolResult(message=f"草稿第 {index} 项已更新")

    def submit_translation(self) -> ToolResult:
        """重新校验并提交当前草稿及本次任务暂存的 candidate。"""

        if self._draft is None:
            raise ValueError("还没有草稿，请先保存草稿")
        targets = list(self._draft)
        validate_translation_output(self._task_input, targets)
        return ToolResult(
            message="翻译已提交",
            output={
                "targets": targets,
                "consistency_candidates": list(self._candidates.values()),
            },
        )

    def record_consistency(
        self,
        candidates: list[dict[str, str]],
    ) -> ToolResult:
        """批量暂存新 source-target candidates，不写入 State。"""

        if not isinstance(candidates, list) or not candidates:
            raise ValueError("candidates 必须是非空 list")

        validated: list[tuple[str, str, str]] = []
        batch_candidates: dict[str, str] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise TypeError("每个 consistency candidate 必须是 dict")
            source = candidate.get("source")
            target = candidate.get("target")
            if not isinstance(source, str) or not source.strip():
                raise ValueError("consistency source 必须是非空字符串")
            if not isinstance(target, str) or not target.strip():
                raise ValueError("consistency target 必须是非空字符串")
            source_key = normalize_source(source)
            if source_key in self._existing_sources:
                raise ValueError(
                    f"该 source 已存在于 consistency records，不能重复提交：{source}"
                )
            if not find_exact_source_positions(source, self._task_input.sources):
                raise ValueError(f"consistency source 不存在于当前 batch：{source}")
            previous = self._candidates.get(source_key)
            pending = batch_candidates.get(source_key)
            previous_target = previous["target"] if previous is not None else pending
            if previous_target is not None and previous_target != target:
                raise ValueError("同一 source 不能提交多个不同译法")
            if previous_target is None:
                batch_candidates[source_key] = target
                validated.append((source_key, source, target))

        for source_key, source, target in validated:
            self._candidates[source_key] = {"source": source, "target": target}
        return ToolResult(message=f"已暂存 {len(validated)} 条 consistency candidate")
