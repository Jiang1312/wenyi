"""Agent Loop 在多个 batch 之间共享的内存状态。"""

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass, field

from models import GlossaryTermInput

_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u02bc": "'",
        "\uff07": "'",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\ufe63": "-",
        "\uff0d": "-",
    }
)


def normalize_text_format(text: str) -> str:
    """统一术语匹配中的 Unicode、标点和空白格式。"""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"(?<=\w)\u00ad\s*(?=\w)", "", normalized)
    normalized = normalized.replace("\u00ad", "")
    normalized = normalized.translate(_PUNCTUATION_TRANSLATION)
    normalized = " ".join(normalized.split())
    return re.sub(r"\s*([()\[\]{}])\s*", r"\1", normalized)


def normalize_term_source(source: str) -> str:
    """返回用于术语 source 比较的格式及大小写无关键。"""

    return normalize_text_format(source).casefold()


@dataclass
class TranslationState:
    """保存可由 Agent 动态更新、供后续 batch 读取的全局信息。"""

    chapter_digest: str = ""
    glossary_terms: list[GlossaryTermInput] = field(default_factory=list)

    def update_chapter_digest(self, chapter_digest: str) -> None:
        self.chapter_digest = chapter_digest

    def add_glossary_terms(self, terms: list[GlossaryTermInput]) -> None:
        """新增术语；已存在的 source 不允许覆盖。"""

        existing = {normalize_term_source(term.source) for term in self.glossary_terms}
        repeated = [term.source for term in terms if normalize_term_source(term.source) in existing]
        if repeated:
            raise ValueError(f"术语已存在，不能覆盖：{repeated[0]}")
        self.glossary_terms.extend(terms)


@dataclass
class BatchWorkingState:
    """当前 batch 尚未提交的草稿和全局状态副本。"""

    translation_state: TranslationState
    current_draft: list[str] | None = None

    @classmethod
    def from_committed(cls, state: TranslationState) -> "BatchWorkingState":
        return cls(translation_state=deepcopy(state))

    def commit_to(self, state: TranslationState) -> None:
        state.chapter_digest = self.translation_state.chapter_digest
        state.glossary_terms = deepcopy(self.translation_state.glossary_terms)
