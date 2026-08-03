"""章节 fixture 调度框架的离线测试。"""

import json
from pathlib import Path

import pytest
from models import GlossaryTermInput, TranslationBatchOutput
from run_fixture import load_fixture, make_batch_input, run_chapter

from state import TranslationState


def test_fixture_uses_all_sample_text_by_subchapter() -> None:
    fixture_path = Path(__file__).parent.parent / "fixtures" / "test_chapter.json"
    source = (fixture_path.parent / "sample_texts.md").read_text(encoding="utf-8")

    data = load_fixture(fixture_path)
    fixture_text = "\n".join(source for batch in data["batches"] for source in batch["sources"])

    assert len(data["batches"]) == 13
    assert "## An Eternal State" in fixture_text
    assert "## Survey of Chapters" in fixture_text
    assert "The conclusion revisits the book’s central set of questions" in fixture_text
    assert len(fixture_text.split()) == len(source.split())
    assert all(
        sum(len(segment.split()) for segment in batch["sources"]) <= 2500
        for batch in data["batches"]
    )


def test_each_batch_reads_current_chapter_digest() -> None:
    data = {
        "book_synopsis": "全书概览",
        "batches": [
            {"sources": ["第一批"]},
            {"sources": ["第二批"]},
        ],
    }
    state = TranslationState(chapter_digest="初始梗概")
    seen_digests = []

    def fake_agent(batch_input, shared_state, **kwargs):
        seen_digests.append(batch_input.chapter_digest)
        if len(seen_digests) == 1:
            shared_state.update_chapter_digest("更新后的梗概")
        return TranslationBatchOutput(targets=["译文"])

    outputs = run_chapter(
        data,
        state,
        model="fake/model",
        run_agent=fake_agent,
    )

    assert seen_digests == ["初始梗概", "更新后的梗概"]
    assert [output.targets for output in outputs] == [["译文"], ["译文"]]


def test_batch_input_reads_matching_terms_from_current_glossary() -> None:
    state = TranslationState(
        glossary_terms=[
            GlossaryTermInput(source="hegemony", target="霸权"),
            GlossaryTermInput(source="performative", target="述行性"),
        ]
    )
    data = {}

    first = make_batch_input(data, ["A hegemonic representation."], state)
    state.add_glossary_terms(
        [GlossaryTermInput(source="authoritative discourse", target="权威话语")]
    )
    second = make_batch_input(data, ["This authoritative discourse persisted."], state)

    assert first.glossary_terms == [GlossaryTermInput(source="hegemony", target="霸权")]
    assert second.glossary_terms == [
        GlossaryTermInput(source="authoritative discourse", target="权威话语")
    ]
    assert len(state.glossary_terms) == 3


def test_chapter_writes_all_batch_traces_to_one_file(tmp_path) -> None:
    data = {
        "batches": [
            {"sources": ["第一批"]},
            {"sources": ["第二批"]},
        ],
    }
    trace_path = tmp_path / "chapter.json"

    def fake_agent(batch_input, state, **kwargs):
        kwargs["trace_sink"].append({"round": 0})
        return TranslationBatchOutput(targets=["译文"])

    state = TranslationState(
        chapter_digest="最终梗概",
        glossary_terms=[GlossaryTermInput(source="term", target="术语")],
    )
    run_chapter(
        data,
        state,
        model="fake/model",
        trace_path=trace_path,
        run_agent=fake_agent,
    )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert [item.get("batch") for item in trace[:2]] == [1, 2]
    assert all(item["status"] == "committed" for item in trace[:2])
    assert all(item["output"] == {"targets": ["译文"]} for item in trace[:2])
    assert trace[2]["run_metrics"]["usage"]["calls"] == 0
    assert trace[3] == {
        "translation_state": {
            "chapter_digest": "最终梗概",
            "glossary_terms": [
                {
                    "source": "term",
                    "target": "术语",
                    "reading": "",
                    "type": "术语",
                    "gender": "",
                    "aliases": [],
                    "note": "",
                }
            ],
        }
    }
    assert list(tmp_path.iterdir()) == [trace_path]


def test_chapter_writes_trace_when_batch_fails(tmp_path) -> None:
    data = {
        "batches": [
            {"sources": ["失败批次"]},
            {"sources": ["不应运行"]},
        ],
    }
    state = TranslationState(chapter_digest="已提交梗概")
    trace_path = tmp_path / "failed.json"

    def failing_agent(batch_input, shared_state, **kwargs):
        kwargs["trace_sink"].append({"round": 0})
        kwargs["trace_sink"].append({"round": 1, "tool_calls": []})
        raise RuntimeError("Agent 轮数超过限制")

    with pytest.raises(RuntimeError, match="Agent 轮数超过限制"):
        run_chapter(
            data,
            state,
            model="fake/model",
            trace_path=trace_path,
            run_agent=failing_agent,
        )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace[0]["batch"] == 1
    assert trace[0]["status"] == "failed"
    assert trace[0]["trace"] == [
        {"round": 0},
        {"round": 1, "tool_calls": []},
    ]
    assert trace[0]["error"] == {
        "type": "RuntimeError",
        "message": "Agent 轮数超过限制",
    }
    assert trace[1]["run_metrics"]["usage"]["calls"] == 0
    assert trace[2] == {
        "translation_state": {
            "chapter_digest": "已提交梗概",
            "glossary_terms": [],
        }
    }
