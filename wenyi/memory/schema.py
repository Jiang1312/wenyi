"""Memory task 与 State 之间传递的最小 topic document 结构。

``content`` 是结构化 Markdown，而不是任意 prose。这里不把 document body
拆成更多领域 class；格式校验和序列化集中在本模块。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TopicDocument:
    """一个 topic document 的传输对象。

    ``document_id`` 为 ``None`` 表示创建新 document；``content`` 为 ``None``
    时表示只携带 catalog metadata。
    """

    document_id: str | None
    summary: str
    content: str | None = None


def render_topic_document(document: TopicDocument) -> str:
    """把 topic document 序列化为带 metadata header 的 Markdown。"""

    if not document.summary.strip():
        raise ValueError("topic document summary 不能为空")
    if document.content is None or not document.content.strip():
        raise ValueError("topic document content 不能为空")
    metadata = json.dumps(
        {"document_id": document.document_id, "summary": document.summary},
        ensure_ascii=False,
    )
    return f"<!-- wenyi-topic-document: {metadata} -->\n{document.content.rstrip()}\n"


def parse_topic_document(raw: str, *, document_id: str | None = None) -> TopicDocument:
    """读取 State 中的结构化 Markdown topic document。"""

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("topic document 不能为空")
    lines = raw.splitlines()
    if not lines or not lines[0].startswith("<!-- wenyi-topic-document: "):
        raise ValueError("topic document 缺少 metadata header")
    prefix = "<!-- wenyi-topic-document: "
    metadata_raw = lines[0][len(prefix) :]
    if not metadata_raw.endswith(" -->"):
        raise ValueError("topic document metadata header 格式错误")
    metadata = json.loads(metadata_raw[:-4])
    summary = metadata.get("summary")
    stored_id = metadata.get("document_id")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("topic document summary 不能为空")
    if stored_id is not None and not isinstance(stored_id, str):
        raise ValueError("topic document document_id 必须是字符串或 null")
    body = "\n".join(lines[1:]).strip()
    if not body:
        raise ValueError("topic document content 不能为空")
    return TopicDocument(
        document_id=document_id if document_id is not None else stored_id,
        summary=summary,
        content=body,
    )

