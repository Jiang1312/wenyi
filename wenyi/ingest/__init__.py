"""摄取与切分：把 EPUB / 纯文本解析为 Document → Chapter → Segment。"""
from .loader import batch_segments, chapter_batches, load_document, split_long_segments
from .models import KIND_HEADING, KIND_TEXT, Chapter, Document, Segment

__all__ = [
    "KIND_HEADING",
    "KIND_TEXT",
    "Chapter",
    "Document",
    "Segment",
    "batch_segments",
    "chapter_batches",
    "load_document",
    "split_long_segments",
]
