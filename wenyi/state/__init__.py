"""State 持久化、章节读写和旧 State 兼容读取入口。"""

from .legacy_reader import LegacySnapshot, LegacyStateReader
from .refs import GlobalSegmentIndex
from .store import (
    STATUS_DONE,
    STATUS_PENDING,
    RunStore,
    StateStore,
    slugify,
    source_sha256,
)

__all__ = [
    "STATUS_DONE",
    "STATUS_PENDING",
    "GlobalSegmentIndex",
    "LegacySnapshot",
    "LegacyStateReader",
    "RunStore",
    "StateStore",
    "slugify",
    "source_sha256",
]
