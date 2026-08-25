"""文档结构契约：ingest、state 和 export 之间共享的最小模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

KIND_TEXT = "text"
KIND_HEADING = "heading"


class Segment(BaseModel):
    """可对齐、可回填的最小翻译单元。"""

    index: int
    source: str
    kind: str = KIND_TEXT
    target: str | None = None
    anchor: str | None = None
    resource_href: str | None = None
    cont: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        return cls.model_validate(data)


class Chapter(BaseModel):
    """有序 Segment 和 export 所需模板信息。"""

    index: int
    title: str = ""
    segments: list[Segment] = Field(default_factory=list)
    href: str | None = None
    template: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def text_segments(self) -> list[Segment]:
        return [segment for segment in self.segments if segment.source.strip()]

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chapter:
        return cls.model_validate(data)


class Document(BaseModel):
    """ingest 的统一输出。"""

    title: str = ""
    source_lang: str
    target_lang: str
    fmt: str
    source_path: str = ""
    chapters: list[Chapter] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        return cls.model_validate(data)
