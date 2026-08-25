"""对外的 ingest 入口。"""

from .segmenter import (
    batch_segments,
    chapter_batches,
    load_document,
    split_long_segments,
)

__all__ = ["batch_segments", "chapter_batches", "load_document", "split_long_segments"]
