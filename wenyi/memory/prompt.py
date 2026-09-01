"""Memory task prompt 组装。"""

from __future__ import annotations

import json

from ..llm import Message
from .task import MemoryTaskInput

MEMORY_SYSTEM_PROMPT = """\\
你负责维护一本书的长期翻译记忆。
CURRENT 中是最近翻译阶段产生的 observations；memory catalog 是已有 topic document 的目录。
请先判断 observation 是否值得保存，再通过工具查看相关原文、译文和已有 document。
如果已有 document 相关，请保留未修改内容并提交完整的新 document；如果没有合适的 document，创建新的 topic document。
每条 memory 都必须保留一个或多个 chapter + segment 原文索引，并且不得凭空添加原文、译文或已有 memory 中没有的事实。
write_memory_document 只暂存修改；全部处理完成后必须调用 submit_memory。
"""


def build_messages(task_input: MemoryTaskInput) -> list[Message]:
    """把 memory task 输入组装成初始对话。"""

    catalog = [
        {"document_id": item.document_id, "summary": item.summary}
        for item in task_input.catalog
    ]
    payload = {
        "current": task_input.current,
        "memory_catalog": catalog,
    }
    return [
        Message(role="system", content=MEMORY_SYSTEM_PROMPT),
        Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2)),
    ]

