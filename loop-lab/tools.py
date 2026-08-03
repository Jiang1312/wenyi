"""Agent 可调用的 Tool 集合及其内部状态。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from models import (
    GlossaryTermInput,
    TranslationBatchInput,
    TranslationBatchOutput,
    validate_translation_output,
)

from state import BatchWorkingState, normalize_term_source

MAX_CHAPTER_DIGEST_CHARS = 600
MAX_GLOSSARY_TERMS_PER_CALL = 10


@dataclass(frozen=True)
class ToolResult:
    """一次 Tool 调用的结果。

    普通 Tool 只返回 ``message``；终止 Tool 还会提供最终 ``output``。
    """

    message: str
    output: TranslationBatchOutput | None = None


class Toolbox:
    """持有一次翻译任务的状态，并向 Agent 暴露简单的 Tool 参数。"""

    definitions = [
        {
            "type": "function",
            "function": {
                "name": "save_draft",
                "description": "保存完整译文草稿。可重复调用，后一次草稿会替换前一次。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "targets": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["targets"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_chapter_digest",
                "description": (
                    "更新供后续翻译使用的章节记忆。用完整、精炼的新版替换旧内容，"
                    "不要追加流水账。只保留会影响后文理解或翻译的关键信息，如人物"
                    "或对象关系、情节或论证进展、重要设定和未解歧义；删除次要细节"
                    "与重复背景。不要推测未出现的内容；没有重要变化时不要调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chapter_digest": {
                            "type": "string",
                            "maxLength": MAX_CHAPTER_DIGEST_CHARS,
                            "description": ("替换现有章节梗概的完整新版工作记忆，最多600个字符"),
                        }
                    },
                    "required": ["chapter_digest"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "modify_draft",
                "description": (
                    "修改当前草稿中的单段译文，避免为局部修改重新保存完整草稿。"
                    "用 old_target 精确定位当前译文；仅在它唯一匹配时替换为 "
                    "new_target。修改后仍需调用 submit_translation 完成最终校验。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "old_target": {
                            "type": "string",
                            "minLength": 1,
                            "description": "当前草稿中需要替换的完整译文",
                        },
                        "new_target": {
                            "type": "string",
                            "minLength": 1,
                            "description": "替换后的完整译文",
                        },
                    },
                    "required": ["old_target", "new_target"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_glossary_terms",
                "description": (
                    "添加当前片段中的关键新术语以维护翻译一致性。仅收录需要统一译法且具有长期价值的术语，极度保守的添加。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "terms": {
                            "type": "array",
                            "maxItems": MAX_GLOSSARY_TERMS_PER_CALL,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source": {"type": "string"},
                                    "target": {"type": "string"},
                                    "type": {"type": "string"},
                                    "note": {"type": "string"},
                                },
                                "required": ["source", "target"],
                            },
                        }
                    },
                    "required": ["terms"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "raise_question",
                "description": (
                    "当翻译中的术语、语义或具体译法确实需要人类判断时调用。"
                    "在 content 中完整说明相关原文、疑点和候选方案。调用后会"
                    "暂停，直到人类在终端回复。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "minLength": 1,
                            "description": "展示给人类的完整问题说明",
                        }
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_translation",
                "description": ("提交最终译文并结束循环。仅使用该工具后才会结束循环。"),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    ]

    def __init__(
        self,
        batch_input: TranslationBatchInput,
        working_state: BatchWorkingState,
    ):
        self._batch_input = batch_input
        self._working_state = working_state
        self._handlers: dict[str, Callable[..., ToolResult]] = {
            "save_draft": self.save_draft,
            "modify_draft": self.modify_draft,
            "update_chapter_digest": self.update_chapter_digest,
            "add_glossary_terms": self.add_glossary_terms,
            "raise_question": self.raise_question,
            "submit_translation": self.submit_translation,
        }

    @property
    def current_draft(self) -> list[str] | None:
        """返回当前草稿的副本，避免调用方意外修改内部状态。"""

        draft = self._working_state.current_draft
        return None if draft is None else list(draft)

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """按 Agent 给出的名称分发 Tool 调用。"""

        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"未知 Tool：{name}")
        return handler(**arguments)

    def save_draft(self, targets: list[str]) -> ToolResult:
        """校验并保存草稿；Agent 只需要提供译文列表。"""

        candidate = TranslationBatchOutput(targets=list(targets))
        validate_translation_output(self._batch_input, candidate)
        self._working_state.current_draft = list(candidate.targets)
        return ToolResult(message=f"草稿已保存，共 {len(candidate.targets)} 段")

    def modify_draft(self, old_target: str, new_target: str) -> ToolResult:
        """用唯一匹配的旧译文定位并替换一段当前草稿。"""

        draft = self._working_state.current_draft
        if draft is None:
            raise ValueError("还没有草稿，请先调用 save_draft")
        if not isinstance(old_target, str) or not old_target.strip():
            raise ValueError("old_target 必须是非空字符串")
        if not isinstance(new_target, str) or not new_target.strip():
            raise ValueError("new_target 必须是非空字符串")

        matches = [index for index, target in enumerate(draft) if target == old_target]
        if not matches:
            raise ValueError("old_target 在当前草稿中不存在，请提供完整且精确的旧译文")
        if len(matches) > 1:
            raise ValueError("old_target 在当前草稿中不唯一，无法确定要修改的段落")

        index = matches[0]
        candidate = list(draft)
        candidate[index] = new_target
        validate_translation_output(
            self._batch_input,
            TranslationBatchOutput(targets=candidate),
        )
        self._working_state.current_draft = candidate
        return ToolResult(message=f"草稿第 {index} 段已更新")

    def submit_translation(self) -> ToolResult:
        """提交当前草稿；Agent 调用此 Tool 时不需要提供参数。"""

        if self._working_state.current_draft is None:
            raise ValueError("还没有草稿，请先调用 save_draft")

        output = TranslationBatchOutput(targets=list(self._working_state.current_draft))
        validate_translation_output(self._batch_input, output)
        return ToolResult(message="翻译已提交", output=output)

    def update_chapter_digest(self, chapter_digest: str) -> ToolResult:
        """完整替换跨 batch 共享的章节梗概。"""

        if not isinstance(chapter_digest, str) or not chapter_digest.strip():
            raise ValueError("chapter_digest 必须是非空字符串")

        digest = chapter_digest.strip()
        if len(digest) > MAX_CHAPTER_DIGEST_CHARS:
            raise ValueError(
                f"chapter_digest 不得超过 {MAX_CHAPTER_DIGEST_CHARS} 个字符，"
                f"当前为 {len(digest)} 个字符；请重新筛选和压缩"
            )
        self._working_state.translation_state.update_chapter_digest(digest)
        return ToolResult(message=f"章节梗概已更新：\n{digest}")

    def add_glossary_terms(self, terms: list[dict[str, Any]]) -> ToolResult:
        """校验并把术语写入跨 batch 共享状态。"""

        if len(terms) > MAX_GLOSSARY_TERMS_PER_CALL:
            raise ValueError(
                f"一次最多提交 {MAX_GLOSSARY_TERMS_PER_CALL} 个术语，当前为 {len(terms)} 个"
            )

        candidates = []
        sources = set()
        for item in terms:
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            if not source or not target:
                raise ValueError("术语的 source 和 target 必须是非空字符串")
            source_key = normalize_term_source(source)
            if source_key in sources:
                raise ValueError(f"同一次提交中 source 不能重复：{source}")
            sources.add(source_key)
            candidates.append(
                GlossaryTermInput(
                    source=source,
                    target=target,
                    type=str(item.get("type", "术语")).strip() or "术语",
                    note=str(item.get("note", "")).strip(),
                )
            )

        self._working_state.translation_state.add_glossary_terms(candidates)
        return ToolResult(message=f"术语已写入，共 {len(candidates)} 项")

    def raise_question(self, content: str) -> ToolResult:
        """在终端向人类提问，并把回复作为 Tool 结果返回给 Agent。"""

        if not isinstance(content, str) or not content.strip():
            raise ValueError("content 必须是非空字符串")

        print("\n===== Agent 请求人工判断 =====")
        print(content.strip())
        answer = input("\n人类回复> ").strip()
        if not answer:
            answer = "人类没有提供具体建议，请自行判断。"
        return ToolResult(message=f"人类回复：{answer}")
