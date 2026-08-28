"""应用级流程编排入口。

职责：创建共享基础设施，遍历 State 中的待翻译 batch，调用具体任务 workflow，
并把 workflow 返回的结果提交回 State。本模块不实现翻译 prompt、工具或任务校验。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import Config
from .consistency import (
    find_exact_source_positions,
    match_exact,
    match_vague,
    normalize_source,
)
from .export import assemble
from .ingest import load_document
from .runner import (
    local_to_global_positions,
    read_context,
    read_state_data,
)
from .state import StateStore, slugify, source_sha256
from .state.store import digest_segments
from .translation import TranslationTaskInput, TranslationWorkflow

_OUTPUT_SUFFIXES = {
    "epub": ".epub",
    "txt": ".txt",
    "html": ".html",
    "markdown": ".md",
    "pdf": ".pdf",
}


class Orchestrator:
    """控制当前 MVP 的 ingest → State → 翻译 → export 流程。"""

    def __init__(self, config: Config, client: Any | None = None) -> None:
        self.config = config
        self.translation: TranslationWorkflow | None = None
        self.client = client

    def _translation_workflow(self) -> TranslationWorkflow:
        """延迟创建翻译 workflow，保证 ingest/export 不依赖 LLM 配置。"""

        if self.translation is None:
            self.translation = TranslationWorkflow.from_config(
                self.config,
                client=self.client,
            )
            self.client = self.translation.runner.client
        return self.translation

    def ingest(self, input_path: str | Path) -> StateStore:
        """解析原始文件并在总 State 目录下创建对应书籍目录。"""

        source_path = Path(input_path).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"输入文件不存在：{source_path}")

        source_hash = source_sha256(str(source_path))
        if source_path.suffix.lower() == ".pdf":
            run_dir = self._state_root() / slugify(source_path.stem)
            store = StateStore(str(run_dir))
            with store.lock():
                if store.exists():
                    return store
                document = load_document(
                    str(source_path),
                    self.config.source_lang,
                    self.config.target_lang,
                    self.config.translation.max_chars_per_segment,
                    cache_dir=store.source_dir,
                    source_hash=source_hash,
                )
        else:
            document = load_document(
                str(source_path),
                self.config.source_lang,
                self.config.target_lang,
                self.config.translation.max_chars_per_segment,
            )
            run_dir = self._state_root() / slugify(document.title)
            store = StateStore(str(run_dir))
            with store.lock():
                if store.exists():
                    return store

        with store.lock():
            if store.exists():
                return store
            document.source_path = str(source_path)
            manifest = store.stage_document(document, source_hash=source_hash)
            store.save_manifest(manifest)
        return store

    def translate(self, state_name: str) -> StateStore:
        """翻译 State 中所有尚未完成的 batch，并提交结果。"""

        run_dir = self._state_root() / state_name
        store = StateStore(str(run_dir), create=False)
        if not store.exists():
            raise FileNotFoundError(f"State 不存在：{run_dir}")

        with store.lock():
            self._translate_store(store)
        return store

    def export(
        self,
        state_name: str,
        *,
        out_format: str = "epub",
        out_path: str | Path | None = None,
    ) -> str:
        """读取具体书籍 State，并将结果导出为成品文件。"""

        run_dir = self._state_root() / state_name
        store = StateStore(str(run_dir), create=False)
        if not store.exists():
            raise FileNotFoundError(f"State 不存在：{run_dir}")

        manifest = store.load_manifest()
        source_path = manifest.get("source_path")
        if not isinstance(source_path, str) or not source_path:
            raise ValueError("State manifest 缺少 source_path")

        if out_format not in _OUTPUT_SUFFIXES:
            supported = " / ".join(_OUTPUT_SUFFIXES)
            raise ValueError(f"不支持的输出格式：{out_format}（支持 {supported}）")
        output = Path(out_path) if out_path is not None else self._default_output_path(
            source_path,
            out_format,
        )
        with store.lock():
            return assemble(
                store,
                source_path,
                str(output),
                out_format,
            )

    def _state_root(self) -> Path:
        """返回配置中的书籍 State 总目录。"""

        return Path(self.config.paths.state_dir)

    def _default_output_path(self, source_path: str, out_format: str) -> Path:
        """返回配置输出目录下的默认成品路径。"""

        return Path(self.config.paths.output_dir) / (
            f"{Path(source_path).stem}.zh{_OUTPUT_SUFFIXES[out_format]}"
        )

    def _translate_store(self, store: StateStore) -> None:
        """在已取得 State 锁的情况下依次处理所有章节。"""

        manifest = store.load_manifest()
        for chapter_record in manifest.get("chapters", []):
            chapter_index = chapter_record.get("index")
            if not isinstance(chapter_index, int):
                continue
            self._translate_chapter(store, chapter_index)

    def _translate_chapter(
        self,
        store: StateStore,
        chapter_index: int,
    ) -> None:
        """处理一个章节中的所有未完成 batch。"""

        state_data = read_state_data(
            store,
            chapter_index,
            self.config.translation.max_chars_per_batch,
        )
        manifest = state_data["manifest"]
        source_lang = manifest.get("source_lang") or self.config.source_lang
        target_lang = manifest.get("target_lang") or self.config.target_lang
        start_index = 0

        for batch_number, batch in enumerate(state_data["batches"], start=1):
            completed = [bool(segment.target and segment.target.strip()) for segment in batch]
            if all(completed):
                start_index += len(batch)
                continue
            if any(completed):
                raise ValueError("State 中存在未完整对齐的 batch")

            consistency_records = store.load_consistency()
            exact_updates: list[dict[str, Any]] = []
            for record, local_positions in match_exact(
                consistency_records,
                [segment.source for segment in batch],
            ):
                exact_updates.append(
                    {
                        "source": record.source,
                        "target": record.target,
                        "occurrences": local_to_global_positions(
                            chapter_index=chapter_index,
                            batch=batch,
                            local_positions=local_positions,
                        ),
                    }
                )
            vague_hits = match_vague(
                consistency_records,
                [segment.source for segment in batch],
            )

            task_input = TranslationTaskInput(
                sources=[segment.source for segment in batch],
                source_lang=source_lang,
                target_lang=target_lang,
                context=read_context(
                    store,
                    chapter_index,
                    start_index,
                    self.config.translation.context_segments,
                ),
                consistency=[
                    {"source": record.source, "target": record.target}
                    for record in vague_hits
                ],
            )
            task_id = f"translation-ch{chapter_index}-batch{batch_number}"
            trace_id = f"trace-{uuid4().hex}"
            store.log_event(
                "translation_batch_started",
                stage="translate",
                task_id=task_id,
                trace_id=trace_id,
                chapter_index=chapter_index,
                start_index=start_index,
                count=len(batch),
            )
            task_output = None
            try:
                task_output = self._translation_workflow().run(
                    task_input,
                    task_id=task_id,
                    existing_consistency_sources={
                        normalize_source(record.source)
                        for record in consistency_records
                    },
                    trace_writer=store.log_trace,
                    trace_id=trace_id,
                )
                if not task_output.is_success:
                    raise RuntimeError(task_output.error_message or "翻译任务失败")
                if isinstance(task_output.result, list):
                    targets = task_output.result
                    consistency_candidates: list[dict[str, str]] = []
                elif isinstance(task_output.result, dict):
                    targets = task_output.result.get("targets")
                    consistency_candidates = task_output.result.get(
                        "consistency_candidates", []
                    )
                    if not isinstance(consistency_candidates, list):
                        raise TypeError("consistency_candidates 必须是 list")
                else:
                    raise TypeError("翻译任务结果必须是 list 或 dict")
                if not isinstance(targets, list):
                    raise TypeError("翻译任务结果的 targets 必须是 list")

                consistency_writes: list[dict[str, Any]] = []
                for candidate in consistency_candidates:
                    if not isinstance(candidate, dict):
                        raise TypeError("consistency candidate 必须是 dict")
                    source = candidate.get("source")
                    target = candidate.get("target")
                    if not isinstance(source, str) or not isinstance(target, str):
                        raise TypeError("consistency candidate 缺少 source 或 target")
                    local_positions = find_exact_source_positions(
                        source,
                        [segment.source for segment in batch],
                    )
                    if not local_positions:
                        raise ValueError("consistency candidate source 不存在于当前 batch")
                    consistency_writes.append(
                        {
                            "source": source,
                            "target": target,
                            "occurrences": local_to_global_positions(
                                chapter_index=chapter_index,
                                batch=batch,
                                local_positions=local_positions,
                            ),
                        }
                    )
                store.commit_batch(
                    task_id=task_id,
                    chapter_index=chapter_index,
                    start_index=start_index,
                    targets=targets,
                    mode="agent_loop",
                    expected_source_digest=digest_segments(batch),
                    trace_id=trace_id,
                    consistency_updates=exact_updates,
                    consistency_writes=consistency_writes,
                )
            except Exception as error:
                store.log_event(
                    "translation_batch_failed",
                    stage="translate",
                    task_id=task_id,
                    trace_id=trace_id,
                    chapter_index=chapter_index,
                    start_index=start_index,
                    error=str(error),
                    error_type=type(error).__name__,
                    usage=task_output.usage if task_output is not None else {},
                )
                raise
            store.log_event(
                "translation_batch_completed",
                stage="translate",
                task_id=task_id,
                trace_id=trace_id,
                chapter_index=chapter_index,
                start_index=start_index,
                count=len(targets),
                usage=task_output.usage,
            )
            start_index += len(batch)
