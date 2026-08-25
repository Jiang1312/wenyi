"""兼容入口：旧 ingest 模块继续从 ``ingest.models`` 导入模型。"""

from ..schema.document import KIND_HEADING, KIND_TEXT, Chapter, Document, Segment

__all__ = ["KIND_HEADING", "KIND_TEXT", "Chapter", "Document", "Segment"]
