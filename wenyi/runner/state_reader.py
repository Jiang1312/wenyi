"""State 信息读取。

职责：从 State 读取章节、已完成译文和可翻译 batch，并按照原版 Wenyi 的规则组织输入。
本模块只负责读取和组织输入，不负责构造翻译任务或执行 Runner。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from ..schema.document import Segment
from ..state.refs import GlobalSegmentIndex
from ..state.store import StateStore


def _chapter_segments(state: StateStore, chapter_index: int) -> list[Segment]:
    """读取指定章节的 Segment；batch 和 context 共用此读取入口。"""

    return state.load_chapter(chapter_index).text_segments


def _iter_state_segments(state: StateStore) -> Iterator[tuple[int, int, Segment]]:
    """按 manifest 中的章节顺序遍历 State 中的 Segment。"""

    manifest = state.load_manifest()
    for chapter_record in manifest.get("chapters", []):
        chapter_index = chapter_record.get("index")
        if isinstance(chapter_index, int):
            for segment_position, segment in enumerate(
                _chapter_segments(state, chapter_index)
            ):
                yield chapter_index, segment_position, segment


def _batch_segments(segments: Sequence[Segment], max_chars: int) -> list[list[Segment]]:
    """按源文字符预算保序分批。"""

    batches: list[list[Segment]] = []
    current: list[Segment] = []
    current_chars = 0
    for segment in segments:
        segment_chars = len(segment.source)
        if current and current_chars + segment_chars > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += segment_chars
    if current:
        batches.append(current)
    return batches


def _resume_batches(segments: Sequence[Segment], max_chars: int) -> list[list[Segment]]:
    """按字符预算分批，再沿已翻译/未翻译边界切开。"""

    batches: list[list[Segment]] = []
    for raw_batch in _batch_segments(segments, max_chars):
        current: list[Segment] = []
        current_done: bool | None = None
        for segment in raw_batch:
            done = bool(segment.target and segment.target.strip())
            if current and done != current_done:
                batches.append(current)
                current = []
            current.append(segment)
            current_done = done
        if current:
            batches.append(current)
    return batches


def read_batches(
    state: StateStore,
    chapter_index: int,
    max_chars: int,
) -> list[list[Segment]]:
    """从 State 读取章节，并返回可用于翻译的 batch 列表。"""

    segments = _chapter_segments(state, chapter_index)
    return _resume_batches(segments, max_chars)


def read_context(
    state: StateStore,
    chapter_index: int,
    start_index: int,
    max_segments: int,
) -> str:
    """读取当前 batch 之前最近的已完成译文。"""

    if max_segments <= 0:
        return ""

    manifest = state.load_manifest()
    chapter_indices = [
        record.get("index")
        for record in manifest.get("chapters", [])
        if isinstance(record.get("index"), int)
    ]
    if chapter_index not in chapter_indices:
        raise ValueError(f"State 中不存在章节：{chapter_index}")
    target_chapter_position = chapter_indices.index(chapter_index)

    targets: list[str] = []
    for current_chapter_index, segment_position, segment in _iter_state_segments(state):
        current_chapter_position = chapter_indices.index(current_chapter_index)
        if current_chapter_position > target_chapter_position:
            break
        if (
            current_chapter_index == chapter_index
            and segment_position >= start_index
        ):
            break

        target = segment.target
        if isinstance(target, str) and target.strip():
            targets.append(target)

    return "\n".join(targets[-max_segments:])


def read_state_data(
    state: StateStore,
    chapter_index: int,
    max_chars: int,
) -> dict[str, Any]:
    """一次读取 State 中指定章节的 manifest 和 batch 数据。"""

    manifest = state.load_manifest()
    return {
        "manifest": manifest,
        "batches": read_batches(state, chapter_index, max_chars),
    }


def local_to_global_positions(
    *,
    chapter_index: int,
    batch: Sequence[Segment],
    local_positions: Iterable[int],
) -> list[tuple[int, int]]:
    """把 batch 内 1-based 位置转换为全局章节和 Segment 索引。"""

    positions: list[tuple[int, int]] = []
    for local_position in local_positions:
        if isinstance(local_position, bool) or not isinstance(local_position, int):
            raise TypeError("batch 内位置必须是整数")
        if local_position < 1 or local_position > len(batch):
            raise ValueError(
                f"batch 内位置超出范围：必须在 1 到 {len(batch)} 之间"
            )
        position = GlobalSegmentIndex(chapter_index, batch[local_position - 1].index)
        if position not in positions:
            positions.append(position)
    return positions


def read_indexed_context(
    state: StateStore,
    indexes: Sequence[GlobalSegmentIndex],
) -> str:
    """按全局 chapter + segment index 读取原文、译文和相邻上下文。"""

    blocks: list[str] = []
    for index in indexes:
        if not isinstance(index, GlobalSegmentIndex):
            if isinstance(index, (list, tuple)) and len(index) == 2:
                index = GlobalSegmentIndex(int(index[0]), int(index[1]))
            else:
                raise TypeError("全局 index 必须是 GlobalSegmentIndex")
        chapter = state.load_chapter(index.chapter)
        segments = chapter.text_segments
        position = next(
            (position for position, item in enumerate(segments) if item.index == index.segment),
            None,
        )
        if position is None:
            raise ValueError(
                f"State 中不存在 Segment：chapter={index.chapter}, segment={index.segment}"
            )
        start = max(0, position - 1)
        end = min(len(segments), position + 2)
        context = []
        for item in segments[start:end]:
            context.append(
                {
                    "chapter": index.chapter,
                    "segment": item.index,
                    "source": item.source,
                    "target": item.target or "",
                }
            )
        blocks.append(json.dumps(context, ensure_ascii=False, indent=2))
    return "\n\n".join(blocks)
