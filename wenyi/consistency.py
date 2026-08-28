"""翻译一致性记录及其匹配、写入和更新操作。"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

try:  # RapidFuzz is preferred when available; the fallback keeps the core usable offline.
    from rapidfuzz import fuzz
except ModuleNotFoundError:  # pragma: no cover - exercised only without optional package
    fuzz = None


VAGUE_MATCH_THRESHOLD = 80


@dataclass
class ConsistencyRecord:
    """一条长期保存的 source-target 一致性记录。"""

    source: str
    target: str
    occurrences: list[tuple[int, int]]


def normalize_source(value: str) -> str:
    """使用稳定的文本标准化规则进行匹配。"""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _partial_ratio(left: str, right: str) -> float:
    """Return RapidFuzz-like partial ratio, with a stdlib fallback."""

    if fuzz is not None:
        return float(fuzz.partial_ratio(left, right))
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    if left in right:
        return 100.0
    matcher = SequenceMatcher(None, left, right)
    best = 0.0
    for block in matcher.get_matching_blocks():
        start = max(0, block[1] - block[0])
        window = right[start : start + len(left)]
        best = max(best, SequenceMatcher(None, left, window).ratio() * 100)
    return best


def _contains_source(source_key: str, text: str) -> bool:
    """检查 source 是否作为完整表达出现，避免英文子串误命中。"""

    def is_word_char(value: str) -> bool:
        return bool(value) and value.isascii() and value.isalnum()

    start = 0
    while (index := text.find(source_key, start)) != -1:
        before = text[index - 1] if index else ""
        end = index + len(source_key)
        after = text[end] if end < len(text) else ""
        if not (
            is_word_char(source_key[0])
            and is_word_char(before)
            or is_word_char(source_key[-1])
            and is_word_char(after)
        ):
            return True
        start = index + 1
    return False


def find_exact_source_positions(
    source: str,
    batch_sources: Sequence[str],
) -> list[int]:
    """返回 source 在 batch 中出现的 1-based segment 编号。"""

    key = normalize_source(source)
    if not key:
        return []
    return [
        index
        for index, text in enumerate(batch_sources, start=1)
        if _contains_source(key, normalize_source(text))
    ]


def match_exact(
    records: Sequence[ConsistencyRecord],
    batch_sources: Sequence[str],
) -> list[tuple[ConsistencyRecord, list[int]]]:
    """找出 batch 中精确出现的记录及其所有局部位置。"""

    matches: list[tuple[ConsistencyRecord, list[int]]] = []
    for record in records:
        positions = find_exact_source_positions(record.source, batch_sources)
        if positions:
            matches.append((record, positions))
    return matches


def match_vague(
    records: Sequence[ConsistencyRecord],
    batch_sources: Sequence[str],
    *,
    threshold: int = VAGUE_MATCH_THRESHOLD,
) -> list[ConsistencyRecord]:
    """返回与 batch 模糊相关的记录，并按 source-target 去重。"""

    normalized_batch = [normalize_source(source) for source in batch_sources]
    matched: list[ConsistencyRecord] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (normalize_source(record.source), record.target)
        if key in seen:
            continue
        normalized_source = normalize_source(record.source)
        if normalized_source and any(
            _partial_ratio(normalized_source, source) >= threshold
            for source in normalized_batch
            if source
        ):
            matched.append(record)
            seen.add(key)
    return matched


def write(
    records: list[ConsistencyRecord],
    source: str,
    target: str,
    occurrences: Sequence[tuple[int, int]],
) -> ConsistencyRecord:
    """写入一个新 source；已有 source 时拒绝覆盖。"""

    source_key = normalize_source(source)
    if not source_key:
        raise ValueError("consistency source 不能为空")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("consistency target 不能为空")
    if any(normalize_source(record.source) == source_key for record in records):
        raise ValueError(f"consistency source 已存在：{source}")
    record = ConsistencyRecord(source, target, list(dict.fromkeys(occurrences)))
    records.append(record)
    return record


def update(
    records: Sequence[ConsistencyRecord],
    source: str,
    target: str,
    occurrences: Sequence[tuple[int, int]],
) -> ConsistencyRecord:
    """给完全一致的 source-target 记录追加 occurrence。"""

    source_key = normalize_source(source)
    if not source_key:
        raise ValueError("consistency source 不能为空")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("consistency target 不能为空")
    for record in records:
        if normalize_source(record.source) != source_key:
            continue
        if record.target != target:
            raise ValueError(
                f"consistency source 已有其他译法：{source} -> {record.target}"
            )
        existing = set(record.occurrences)
        for occurrence in occurrences:
            if occurrence not in existing:
                record.occurrences.append(occurrence)
                existing.add(occurrence)
        return record
    raise ValueError(f"consistency record 不存在：{source} -> {target}")


def match(
    records: Sequence[ConsistencyRecord],
    batch_sources: Sequence[str],
    *,
    mode: Literal["exact", "vague"],
) -> list[ConsistencyRecord] | list[tuple[ConsistencyRecord, list[int]]]:
    """按模式执行匹配；exact 返回位置，vague 返回去重后的记录。"""

    if mode == "exact":
        return match_exact(records, batch_sources)
    if mode == "vague":
        return match_vague(records, batch_sources)
    raise ValueError(f"未知 consistency match 模式：{mode}")
