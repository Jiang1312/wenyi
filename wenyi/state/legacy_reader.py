"""旧 Wenyi State 的只读适配器。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from ..schema.document import Chapter


@dataclass(frozen=True)
class LegacySnapshot:
    manifest: dict
    chapters: tuple[Chapter, ...]
    source_dir: str


class LegacyStateReader:
    """读取旧 state，不提供任何写入方法。"""

    def __init__(self, state_dir: str):
        self.state_dir = state_dir

    def read(self) -> LegacySnapshot:
        manifest_path = os.path.join(self.state_dir, "manifest.json")
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        chapters = []
        for item in manifest.get("chapters", []):
            index = int(item["index"])
            chapter_path = os.path.join(self.state_dir, "chapters", f"ch{index}.json")
            with open(chapter_path, encoding="utf-8") as handle:
                chapters.append(Chapter.from_dict(json.load(handle)))
        return LegacySnapshot(
            manifest=manifest,
            chapters=tuple(chapters),
            source_dir=os.path.join(self.state_dir, "source"),
        )
