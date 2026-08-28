"""v2 State：书级锁、原子 JSON、章节状态和结构化生命周期日志。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from ..consistency import ConsistencyRecord, normalize_source
from ..consistency import update as update_consistency
from ..consistency import write as write_consistency
from ..schema.document import Chapter, Document

STATUS_PENDING = "pending"
STATUS_DONE = "done"


def slugify(name: str) -> str:
    value = re.sub(r"[^\w一-鿿぀-ヿ-]+", "_", name).strip("_")
    return value or "book"


def digest_segments(segments: list[Any]) -> str:
    payload = [(segment.index, segment.source) for segment in segments]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_sha256(path: str) -> str:
    """流式计算源文件哈希，用于绑定 State 与输入文件。"""

    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class StateStore:
    """新项目使用的 v2 State Store。"""

    schema_version = 2

    def __init__(self, run_dir: str, *, create: bool = True):
        self.run_dir = run_dir
        self.chapters_dir = os.path.join(run_dir, "chapters")
        self.source_dir = os.path.join(run_dir, "source")
        self.logs_dir = os.path.join(run_dir, "logs")
        if create:
            self.ensure_dirs()

    def ensure_dirs(self) -> None:
        os.makedirs(self.chapters_dir, exist_ok=True)
        os.makedirs(self.source_dir, exist_ok=True)

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.ensure_dirs()
        lock_path = os.path.join(self.run_dir, ".run.lock")
        with open(lock_path, "a+b") as lock_file:
            if os.name == "nt":  # pragma: no cover
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.run_dir, "manifest.json")

    @property
    def event_log_path(self) -> str:
        return os.path.join(self.logs_dir, "events.jsonl")

    @property
    def trace_log_path(self) -> str:
        return os.path.join(self.logs_dir, "traces.jsonl")

    @property
    def consistency_path(self) -> str:
        return os.path.join(self.run_dir, "consistency.json")

    def chapter_path(self, index: int) -> str:
        return os.path.join(self.chapters_dir, f"ch{index}.json")

    @staticmethod
    def _write_json(path: str, data: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    @staticmethod
    def _read_json(path: str) -> Any:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def exists(self) -> bool:
        return os.path.isfile(self.manifest_path)

    def log_event(self, event: str, **data: Any) -> None:
        """写入生命周期事件；可扩展字段统一放入 data。"""

        os.makedirs(self.logs_dir, exist_ok=True)
        row = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            "data": data,
        }
        with open(self.event_log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def log_trace(self, record: dict[str, Any]) -> None:
        """追加一条 Agent 执行 trace；record 由通用 Runner 生成。"""

        os.makedirs(self.logs_dir, exist_ok=True)
        row = {
            **record,
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        with open(self.trace_log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def load_manifest(self) -> dict[str, Any]:
        return self._read_json(self.manifest_path)

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        self._write_json(self.manifest_path, manifest)

    def load_chapter(self, index: int) -> Chapter:
        return Chapter.from_dict(self._read_json(self.chapter_path(index)))

    def save_chapter(self, chapter: Chapter) -> None:
        self._write_json(self.chapter_path(chapter.index), chapter.to_dict())

    def load_consistency(self) -> list[ConsistencyRecord]:
        """读取一致性记录；旧 State 没有文件时返回空列表。"""

        if not os.path.isfile(self.consistency_path):
            return []
        rows = self._read_json(self.consistency_path)
        if not isinstance(rows, list):
            raise TypeError("consistency.json 必须是 list")
        return [
            ConsistencyRecord(
                source=row["source"],
                target=row["target"],
                occurrences=[tuple(item) for item in row.get("occurrences", [])],
            )
            for row in rows
        ]

    def save_consistency(self, records: list[ConsistencyRecord]) -> None:
        """原子保存一致性记录。"""

        self._write_json(
            self.consistency_path,
            [
                {
                    "source": record.source,
                    "target": record.target,
                    "occurrences": [list(item) for item in record.occurrences],
                }
                for record in records
            ],
        )

    def stage_document(
        self,
        document: Document,
        *,
        source_hash: str | None = None,
    ) -> dict[str, Any]:
        manifest = {
            "schema_version": self.schema_version,
            "book_id": slugify(document.title),
            "title": document.title,
            "fmt": document.fmt,
            "format": document.fmt,
            "source_path": document.source_path,
            "source_lang": document.source_lang,
            "target_lang": document.target_lang,
            "meta": document.meta,
            "chapters": [],
        }
        if source_hash is not None:
            manifest["source_sha256"] = source_hash
        for chapter in document.chapters:
            self.save_chapter(chapter)
            segments = chapter.text_segments
            manifest["chapters"].append(
                {
                    "index": chapter.index,
                    "title": chapter.title,
                    "href": chapter.href,
                    "status": STATUS_DONE if segments and all(s.target for s in segments) else STATUS_PENDING,
                    "segment_count": len(segments),
                    "translated_segment_count": sum(bool(s.target and s.target.strip()) for s in segments),
                    "toc_entry_id": chapter.meta.get("toc_entry_id"),
                }
            )
        return manifest

    def stage_legacy_snapshot(self, snapshot: Any) -> dict[str, Any]:
        """把旧 State 的只读快照复制为新的 v2 State。"""

        old = snapshot.manifest
        manifest = {
            "schema_version": self.schema_version,
            "book_id": slugify(str(old.get("title") or "book")),
            "title": old.get("title", ""),
            "fmt": old.get("fmt", old.get("format", "text")),
            "format": old.get("fmt", old.get("format", "text")),
            "source_path": old.get("source_path", ""),
            "source_lang": old.get("source_lang", "auto"),
            "target_lang": old.get("target_lang", "zh"),
            "meta": dict(old.get("meta") or {}),
            "chapters": [],
        }
        for chapter in snapshot.chapters:
            segments = chapter.text_segments
            self.save_chapter(chapter)
            manifest["chapters"].append(
                {
                    "index": chapter.index,
                    "title": chapter.title,
                    "href": chapter.href,
                    "status": STATUS_DONE if segments and all(s.target for s in segments) else STATUS_PENDING,
                    "segment_count": len(segments),
                    "translated_segment_count": sum(bool(s.target and s.target.strip()) for s in segments),
                    "toc_entry_id": chapter.meta.get("toc_entry_id"),
                }
            )
        return manifest

    def pending_chapters(self) -> list[int]:
        return [
            item["index"]
            for item in self.load_manifest().get("chapters", [])
            if item.get("status") != STATUS_DONE
        ]

    def commit_batch(
        self,
        *,
        task_id: str,
        chapter_index: int,
        start_index: int,
        targets: list[str],
        mode: str,
        expected_source_digest: str | None = None,
        trace_id: str | None = None,
        consistency_updates: list[dict[str, Any]] | None = None,
        consistency_writes: list[dict[str, Any]] | None = None,
    ) -> None:
        """校验源文未变化后提交一个 batch，再记录事件和进度。"""

        chapter = self.load_chapter(chapter_index)
        segments = chapter.text_segments
        batch = segments[start_index : start_index + len(targets)]
        if len(batch) != len(targets):
            raise ValueError("提交 batch 超出章节范围")
        if any(segment.target and segment.target.strip() for segment in batch):
            raise ValueError("提交 batch 包含已完成 Segment")
        if any(not isinstance(target, str) or not target.strip() for target in targets):
            raise ValueError("提交译文必须是非空字符串")
        actual_source_digest = digest_segments(batch)
        if expected_source_digest is not None and expected_source_digest != actual_source_digest:
            raise ValueError("提交 batch 的源文已变化")

        consistency_records = self.load_consistency()
        consistency_log: dict[str, list[dict[str, Any]]] = {
            "writes": [],
            "updates": [],
        }
        for change in consistency_updates or []:
            source = change["source"]
            target = change["target"]
            record = next(
                (
                    item
                    for item in consistency_records
                    if normalize_source(item.source) == normalize_source(source)
                ),
                None,
            )
            before = len(record.occurrences) if record is not None else 0
            update_consistency(
                consistency_records,
                source,
                target,
                [tuple(item) for item in change["occurrences"]],
            )
            after = len(record.occurrences) if record is not None else before
            if after > before:
                consistency_log["updates"].append(
                    {
                        "source": source,
                        "target": target,
                        "added_occurrences": after - before,
                    }
                )
        for change in consistency_writes or []:
            source = change["source"]
            target = change["target"]
            write_consistency(
                consistency_records,
                source,
                target,
                [tuple(item) for item in change["occurrences"]],
            )
            consistency_log["writes"].append(
                {"source": source, "target": target}
            )

        for segment, target in zip(batch, targets):
            segment.target = target
        self.save_chapter(chapter)

        manifest = self.load_manifest()
        for record in manifest.get("chapters", []):
            if record.get("index") != chapter_index:
                continue
            completed = sum(bool(segment.target and segment.target.strip()) for segment in segments)
            record["translated_segment_count"] = completed
            record["segment_count"] = len(segments)
            record["status"] = STATUS_DONE if completed == len(segments) else STATUS_PENDING
            break
        self.save_manifest(manifest)
        if consistency_updates or consistency_writes:
            self.save_consistency(consistency_records)
        target_digest = hashlib.sha256("\n".join(targets).encode()).hexdigest()
        event_data: dict[str, Any] = {
            "task_id": task_id,
            "chapter": chapter_index,
            "start_index": start_index,
            "count": len(targets),
            "mode": mode,
            "status": "committed",
            "source_digest": actual_source_digest,
            "target_digest": target_digest,
            "trace_id": trace_id,
        }
        if consistency_log["writes"] or consistency_log["updates"]:
            event_data["consistency"] = consistency_log
        self.log_event("batch_committed", **event_data)


RunStore = StateStore
