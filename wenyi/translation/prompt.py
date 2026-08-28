"""翻译任务的 prompt 组装。

职责：把翻译任务输入转换成 LLM 使用的 system message 和 user message。
本模块只处理原文、源语言和目标语言，不处理工具、State 或输出解析。
"""

from __future__ import annotations

import json

from ..llm import Message
from .task import TranslationTaskInput

TRANSLATION_SYSTEM_PROMPT = """\
你是一个专业翻译，尽可能按照原文直译，不要改写。
souce_lan：原文语言，target_lan：译文语言，source：待翻译原文
context：当前文本之前的最近译文，仅作为翻译参考，
consistency：已有的一致性术语译法，在原文表达相似时沿用；
只记录值得在长程翻译中需要统一固定译法且具有长期价值的术语；
请翻译 sources 中的全部原文，并保持原文顺序，用save_draft写入。
新的 source-target 一致性译法，可以一次用record_consistency批量记录。
输出必须与 sources 等长，每一项译文对应同一编号的原文，不要遗漏任何段落。
任务完成调用submit_translation。
"""


def build_messages(task_input: TranslationTaskInput) -> list[Message]:
    """把翻译任务输入组装成初始对话消息。"""

    payload = {
        "source_lang": task_input.source_lang,
        "target_lang": task_input.target_lang,
        "context": task_input.context,
        "sources": [
            {"segment_number": index, "text": source}
            for index, source in enumerate(task_input.sources, start=1)
        ],
    }
    if task_input.consistency:
        payload["consistency"] = task_input.consistency
    return [
        Message(role="system", content=TRANSLATION_SYSTEM_PROMPT),
        Message(
            role="user",
            content=json.dumps(payload, ensure_ascii=False, indent=2),
        ),
    ]
