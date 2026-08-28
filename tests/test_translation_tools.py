import pytest

from wenyi.translation import TranslationTaskInput, TranslationToolBox


def _task_input() -> TranslationTaskInput:
    return TranslationTaskInput(
        sources=["原文一", "原文二", "原文三"],
        source_lang="ja",
        target_lang="zh",
    )


def test_save_draft_replaces_full_draft_and_submit_returns_a_copy():
    toolbox = TranslationToolBox(_task_input())

    saved = toolbox.execute(
        "save_draft",
        {"targets": ["译文一", "译文二", "译文三"]},
    )
    submitted = toolbox.execute("submit_translation", {})

    assert saved.output is None
    assert saved.message == "草稿已保存，共 3 段"
    assert submitted.output == {
        "targets": ["译文一", "译文二", "译文三"],
        "consistency_candidates": [],
    }
    submitted.output["targets"][0] = "外部修改"
    assert toolbox.submit_translation().output["targets"] == [
        "译文一",
        "译文二",
        "译文三",
    ]


def test_save_draft_can_update_one_item_with_one_based_index():
    toolbox = TranslationToolBox(_task_input())
    toolbox.save_draft(["译文一", "译文二", "译文三"])

    result = toolbox.save_draft(["修改后的译文二"], index=2)
    submitted = toolbox.submit_translation()

    assert result.message == "草稿第 2 项已更新"
    assert submitted.output["targets"] == ["译文一", "修改后的译文二", "译文三"]


def test_draft_and_submit_reject_invalid_states():
    toolbox = TranslationToolBox(_task_input())

    with pytest.raises(ValueError, match="数量"):
        toolbox.save_draft(["只有一项"])
    with pytest.raises(ValueError, match="还没有草稿"):
        toolbox.submit_translation()
    with pytest.raises(ValueError, match="先在不传 index"):
        toolbox.save_draft(["译文"], index=1)

    toolbox.save_draft(["译文一", "译文二", "译文三"])
    with pytest.raises(ValueError, match="只包含一项"):
        toolbox.save_draft(["一", "二"], index=1)
    with pytest.raises(ValueError, match="超出范围"):
        toolbox.save_draft(["译文"], index=4)
    with pytest.raises(ValueError, match="非空"):
        toolbox.save_draft([""], index=1)

    with pytest.raises(ValueError, match="非空"):
        toolbox.save_draft(["译文一", 2, "译文三"])


def test_toolbox_exposes_only_draft_and_submit_tools():
    toolbox = TranslationToolBox(_task_input())

    names = [item["function"]["name"] for item in toolbox.definitions]

    assert names == ["save_draft", "record_consistency", "submit_translation"]


def test_record_consistency_collects_new_pair_and_rejects_existing_source():
    task_input = TranslationTaskInput(
        sources=["A performative example", "Another constative example"],
        source_lang="en",
        target_lang="zh",
        consistency=[{"source": "performative", "target": "述行性"}],
    )
    toolbox = TranslationToolBox(task_input)

    candidate = toolbox.record_consistency(
        candidates=[{"source": "constative", "target": "述谓性"}]
    )
    assert candidate.message == "已暂存 1 条 consistency candidate"
    with pytest.raises(ValueError, match="已存在"):
        toolbox.record_consistency(
            candidates=[{"source": "performative", "target": "表演性"}]
        )
    with pytest.raises(ValueError, match="多个不同译法"):
        toolbox.record_consistency(
            candidates=[{"source": "constative", "target": "断言性"}]
        )


def test_record_consistency_accepts_multiple_candidates_atomically():
    task_input = TranslationTaskInput(
        sources=["A constative", "A performative"],
        source_lang="en",
        target_lang="zh",
    )
    toolbox = TranslationToolBox(task_input)

    result = toolbox.record_consistency(
        candidates=[
            {"source": "constative", "target": "述谓性"},
            {"source": "performative", "target": "述行性"},
        ]
    )
    assert result.message == "已暂存 2 条 consistency candidate"
    toolbox.save_draft(["译文一", "译文二"])
    assert toolbox.submit_translation().output["consistency_candidates"] == [
        {"source": "constative", "target": "述谓性"},
        {"source": "performative", "target": "述行性"},
    ]


def test_record_consistency_rejects_an_invalid_batch_without_partial_candidates():
    task_input = TranslationTaskInput(
        sources=["A constative", "A performative"],
        source_lang="en",
        target_lang="zh",
        consistency=[{"source": "performative", "target": "述行性"}],
    )
    toolbox = TranslationToolBox(task_input)

    with pytest.raises(ValueError, match="已存在"):
        toolbox.record_consistency(
            candidates=[
                {"source": "constative", "target": "述谓性"},
                {"source": "performative", "target": "表演性"},
            ]
        )

    toolbox.save_draft(["译文一", "译文二"])
    assert toolbox.submit_translation().output["consistency_candidates"] == []
