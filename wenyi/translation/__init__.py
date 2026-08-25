"""翻译任务。

职责：定义一个翻译 batch 的任务输入、prompt、工具和 workflow。
State 的读取、遍历和提交由外部 Orchestrator 负责。
"""

from .prompt import TRANSLATION_SYSTEM_PROMPT, build_messages
from .task import TranslationTaskInput, validate_translation_output
from .tools import TranslationToolBox
from .workflow import TranslationWorkflow

__all__ = [
    "TRANSLATION_SYSTEM_PROMPT",
    "TranslationTaskInput",
    "TranslationToolBox",
    "TranslationWorkflow",
    "build_messages",
    "validate_translation_output",
]
