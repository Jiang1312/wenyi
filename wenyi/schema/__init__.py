"""跨 ingest、State 和 export 共享的文档结构模型。"""

from .document import KIND_HEADING, KIND_TEXT, Chapter, Document, Segment

__all__ = [
    "KIND_HEADING",
    "KIND_TEXT",
    "Chapter",
    "Document",
    "Segment",
]
