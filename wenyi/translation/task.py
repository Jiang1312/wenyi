"""翻译任务的数据契约和输出校验。

职责：定义模型层需要的原文与语言信息，并校验提交的译文列表是否能够
与输入原文逐项对齐。本模块不读取 State，也不执行 LLM 或工具。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationTaskInput:
    """一次 batch 翻译所需的模型层输入。"""

    sources: list[str]
    source_lang: str
    target_lang: str
    context: str = ""


def validate_translation_output(
    task_input: TranslationTaskInput,
    targets: list[str],
) -> None:
    """校验 submit 的译文列表是否与原文列表对齐且没有空元素。"""

    if not isinstance(targets, list):
        raise TypeError("译文结果必须是 list")
    if len(targets) != len(task_input.sources):
        raise ValueError(
            "译文数量必须与原文数量相同："
            f"期望 {len(task_input.sources)}，实际 {len(targets)}"
        )
    for index, target in enumerate(targets):
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"targets[{index}] 必须是非空字符串")
