import pytest

from wenyi.runner import TaskOutput, read_state_data
from wenyi.schema.document import Chapter, Segment
from wenyi.translation import (
    TranslationTaskInput,
    TranslationWorkflow,
    validate_translation_output,
)


class FakeState:
    def __init__(self) -> None:
        self.chapter = Chapter(
            index=1,
            segments=[
                Segment(index=0, source="第一段"),
                Segment(index=1, source="第二段"),
            ],
        )

    def load_chapter(self, chapter_index: int) -> Chapter:
        assert chapter_index == 1
        return self.chapter

    def load_manifest(self) -> dict[str, str]:
        return {"source_lang": "ja", "target_lang": "zh"}


def test_read_state_data_reads_manifest_and_batches_together():
    data = read_state_data(FakeState(), chapter_index=1, max_chars=100)

    assert data["manifest"]["source_lang"] == "ja"
    assert data["manifest"]["target_lang"] == "zh"
    assert [[segment.source for segment in batch] for batch in data["batches"]] == [
        ["第一段", "第二段"]
    ]


def test_translation_output_must_match_sources_and_contain_no_empty_items():
    task_input = TranslationTaskInput(
        sources=["第一段", "第二段"],
        source_lang="ja",
        target_lang="zh",
    )

    validate_translation_output(task_input, ["第一段译文", "第二段译文"])

    with pytest.raises(ValueError, match="数量"):
        validate_translation_output(task_input, ["只有一段"])

    with pytest.raises(ValueError, match="非空"):
        validate_translation_output(task_input, ["第一段译文", "  "])

    with pytest.raises(TypeError, match="list"):
        validate_translation_output(task_input, ("第一段译文", "第二段译文"))


def test_translation_workflow_returns_task_output_with_result_and_usage():
    task_input = TranslationTaskInput(
        sources=["第一段"],
        source_lang="ja",
        target_lang="zh",
    )

    class FakeRunner:
        def run(
            self,
            task_input,
            *,
            messages,
            tool_factory,
            trace_writer=None,
            trace_id=None,
        ):
            assert callable(tool_factory)
            return TaskOutput(
                task_id=task_input.task_id,
                task_type=task_input.task_type,
                is_success=True,
                result=["第一段译文"],
                error_message=None,
                usage={
                    "calls": 2,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            )

    output = TranslationWorkflow(FakeRunner()).run(task_input)

    assert output.is_success
    assert output.result == ["第一段译文"]
    assert output.usage == {
        "calls": 2,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
