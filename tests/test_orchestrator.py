import json
from pathlib import Path

import pytest

from wenyi.config import Config, LLMConfig, PathsConfig, TranslationConfig
from wenyi.llm import FunctionCall, LLMResponse, TokenUsage, ToolCall
from wenyi.orchestrator import Orchestrator
from wenyi.schema.document import Chapter, Document, Segment
from wenyi.state import StateStore


class FakeClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def generate(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _tool_call(name: str, arguments: dict, call_id: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        type="function",
        function=FunctionCall(name=name, arguments=arguments),
    )


def _state(path: Path) -> StateStore:
    store = StateStore(str(path))
    document = Document(
        title="Test Book",
        source_lang="en",
        target_lang="zh",
        fmt="text",
        chapters=[
            Chapter(
                index=0,
                segments=[
                    Segment(index=0, source="one"),
                    Segment(index=1, source="two"),
                ],
            )
        ],
    )
    store.save_manifest(store.stage_document(document))
    return store


def _two_chapter_state(path: Path) -> StateStore:
    store = StateStore(str(path))
    document = Document(
        title="Test Book",
        source_lang="en",
        target_lang="zh",
        fmt="text",
        chapters=[
            Chapter(index=0, segments=[Segment(index=0, source="one")]),
            Chapter(index=1, segments=[Segment(index=0, source="two")]),
        ],
    )
    store.save_manifest(store.stage_document(document))
    return store


def _config(state_path: Path) -> Config:
    return Config(
        source_lang="en",
        target_lang="zh",
        translation=TranslationConfig(max_chars_per_batch=3),
        llm=LLMConfig(api_key="test", model="test-model"),
        paths=PathsConfig(state_dir=str(state_path)),
    )


def test_orchestrator_translates_and_commits_each_pending_batch(tmp_path: Path):
    state_root = tmp_path / "state"
    state_path = state_root / "Barn-burning"
    store = _state(state_path)
    client = FakeClient(
        [
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
                tool_calls=[
                    _tool_call(
                        "save_draft",
                        {"targets": ["一"]},
                        "save-1",
                    )
                ],
            ),
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=20, completion_tokens=3, total_tokens=23),
                tool_calls=[_tool_call("submit_translation", {}, "submit-1")],
            ),
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=30, completion_tokens=4, total_tokens=34),
                tool_calls=[
                    _tool_call(
                        "save_draft",
                        {"targets": ["二"]},
                        "save-2",
                    )
                ],
            ),
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=40, completion_tokens=5, total_tokens=45),
                tool_calls=[_tool_call("submit_translation", {}, "submit-2")],
            ),
        ]
    )

    Orchestrator(_config(state_root), client=client).translate("Barn-burning")

    translated = store.load_chapter(0).text_segments
    assert [segment.target for segment in translated] == ["一", "二"]
    assert store.pending_chapters() == []
    events = Path(store.event_log_path).read_text(encoding="utf-8")
    assert events.count('"event": "batch_committed"') == 2
    event_rows = [json.loads(line) for line in events.splitlines()]
    trace_rows = [
        json.loads(line)
        for line in Path(store.trace_log_path).read_text(encoding="utf-8").splitlines()
    ]
    started_trace_ids = {
        row["data"]["trace_id"]
        for row in event_rows
        if row["event"] == "translation_batch_started"
    }
    committed_trace_ids = {
        row["data"]["trace_id"]
        for row in event_rows
        if row["event"] == "batch_committed"
    }
    assert started_trace_ids == committed_trace_ids
    assert {row["trace_id"] for row in trace_rows} == started_trace_ids
    completed_usage = [
        row["data"]["usage"]
        for row in event_rows
        if row["event"] == "translation_batch_completed"
    ]
    assert completed_usage == [
        {
            "calls": 2,
            "prompt_tokens": 30,
            "completion_tokens": 5,
            "total_tokens": 35,
        },
        {
            "calls": 2,
            "prompt_tokens": 70,
            "completion_tokens": 9,
            "total_tokens": 79,
        },
    ]


def test_orchestrator_records_failed_batch_event_and_trace(tmp_path: Path):
    state_root = tmp_path / "state"
    state_path = state_root / "Barn-burning"
    store = _state(state_path)

    class FailingClient:
        def generate(self, **kwargs) -> LLMResponse:
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        Orchestrator(_config(state_root), client=FailingClient()).translate(
            "Barn-burning"
        )

    event_rows = [
        json.loads(line)
        for line in Path(store.event_log_path).read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in event_rows] == [
        "translation_batch_started",
        "translation_batch_failed",
    ]
    failed_data = event_rows[-1]["data"]
    assert failed_data["task_id"] == "translation-ch0-batch1"
    assert failed_data["trace_id"] == event_rows[0]["data"]["trace_id"]
    assert failed_data["error"] == "provider unavailable"
    assert failed_data["usage"] == {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert store.load_chapter(0).text_segments[0].target is None

    trace_rows = [
        json.loads(line)
        for line in Path(store.trace_log_path).read_text(encoding="utf-8").splitlines()
    ]
    assert [row["kind"] for row in trace_rows] == [
        "agent_start",
        "model_error",
        "agent_error",
    ]


def test_orchestrator_reads_previous_chapter_translation_as_context(tmp_path: Path):
    state_root = tmp_path / "state"
    state_path = state_root / "Barn-burning"
    _two_chapter_state(state_path)
    client = FakeClient(
        [
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[
                    _tool_call("save_draft", {"targets": ["一"]}, "save-1")
                ],
            ),
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[_tool_call("submit_translation", {}, "submit-1")],
            ),
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[
                    _tool_call("save_draft", {"targets": ["二"]}, "save-2")
                ],
            ),
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[_tool_call("submit_translation", {}, "submit-2")],
            ),
        ]
    )

    Orchestrator(_config(state_root), client=client).translate("Barn-burning")

    second_batch_payload = json.loads(client.calls[2]["messages"][1].content)
    assert second_batch_payload["context"] == "一"


def test_orchestrator_ingest_and_export_use_mvp_directories(tmp_path: Path):
    source = tmp_path / "book.txt"
    source.write_text("one\n\ntwo", encoding="utf-8")
    state_root = tmp_path / "state"
    output_root = tmp_path / "output"
    config = Config(
        source_lang="en",
        target_lang="zh",
        paths=PathsConfig(
            state_dir=str(state_root),
            output_dir=str(output_root),
        ),
    )

    orchestrator = Orchestrator(config)
    store = orchestrator.ingest(source)

    assert Path(store.run_dir) == state_root / "book"
    assert store.load_manifest()["source_path"] == str(source.resolve())
    store.commit_batch(
        task_id="ingest-export-test",
        chapter_index=0,
        start_index=0,
        targets=["一", "二"],
        mode="agent_loop",
    )

    output = orchestrator.export("book", out_format="txt")

    assert Path(output) == output_root / "book.zh.txt"
    assert Path(output).read_text(encoding="utf-8") == "一\n\n二\n"
