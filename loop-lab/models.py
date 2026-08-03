"""Translation Agent Loop 的稳定输入输出契约。

这里的数据类型不依赖 Wenyi 的 Segment、Chapter 或 RunStore。
Wenyi 负责通过 Adapter 构造输入，并把输出回填到自己的内部对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GlossaryTermInput:
    """提供给翻译流程并可写入共享状态的术语。"""

    source: str
    target: str
    reading: str = ""
    type: str = "术语"
    gender: str = ""
    aliases: list[str] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class TranslationBatchInput:
    """一个待翻译 batch 的全部业务输入。"""

    sources: list[str]
    glossary_terms: list[GlossaryTermInput] = field(default_factory=list)
    style: str = ""
    context: str = ""
    book_synopsis: str = ""
    chapter_digest: str = ""


@dataclass(frozen=True)
class TranslationBatchOutput:
    """Agent Loop 对外返回的最终译文。"""

    targets: list[str]


def validate_translation_output(
    batch_input: TranslationBatchInput,
    output: TranslationBatchOutput,
) -> None:
    """检查输出是否满足 batch 契约。

    成功时不返回值；契约不满足时抛出 ``ValueError``。下标之间的语义对应
    仍需由翻译流程保证，程序只能校验数量、类型和非空性。
    """

    if len(output.targets) != len(batch_input.sources):
        raise ValueError(
            "targets 数量必须与 sources 相同："
            f"期望 {len(batch_input.sources)}，实际 {len(output.targets)}"
        )

    for index, target in enumerate(output.targets):
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"targets[{index}] 必须是非空字符串")
