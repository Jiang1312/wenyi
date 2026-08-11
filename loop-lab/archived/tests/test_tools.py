"""Toolbox 的离线行为测试。"""

import pytest
from models import GlossaryTermInput, TranslationBatchInput
from tools import Toolbox

from state import BatchWorkingState, TranslationState


def build_toolbox(
    sources: list[str] | None = None,
    state: TranslationState | None = None,
) -> tuple[Toolbox, TranslationState, BatchWorkingState]:
    committed = state if state is not None else TranslationState()
    working = BatchWorkingState.from_committed(committed)
    toolbox = Toolbox(
        TranslationBatchInput(sources=sources or ["source one", "source two"]),
        working,
    )
    return toolbox, committed, working


class TestDraft:
    def test_agent_only_supplies_targets(self) -> None:
        toolbox, _, _ = build_toolbox()

        result = toolbox.execute(
            "save_draft",
            {"targets": ["译文一", "译文二"]},
        )

        assert result.message == "草稿已保存，共 2 段"
        assert toolbox.current_draft == ["译文一", "译文二"]

    def test_invalid_draft_keeps_previous_draft(self) -> None:
        toolbox, _, _ = build_toolbox()
        toolbox.save_draft(["有效译文一", "有效译文二"])

        with pytest.raises(ValueError):
            toolbox.save_draft(["数量不正确"])

        assert toolbox.current_draft == ["有效译文一", "有效译文二"]


class TestModifyDraft:
    def test_replaces_uniquely_matching_target(self) -> None:
        toolbox, _, _ = build_toolbox()
        toolbox.save_draft(["旧译文一", "译文二"])

        result = toolbox.execute(
            "modify_draft",
            {"old_target": "旧译文一", "new_target": "新译文一"},
        )

        assert result.message == "草稿第 0 段已更新"
        assert toolbox.current_draft == ["新译文一", "译文二"]

    def test_requires_existing_draft(self) -> None:
        toolbox, _, _ = build_toolbox()

        with pytest.raises(ValueError, match="先调用 save_draft"):
            toolbox.modify_draft("旧译文", "新译文")

    @pytest.mark.parametrize("field", ["old_target", "new_target"])
    def test_rejects_empty_target(self, field: str) -> None:
        toolbox, _, _ = build_toolbox()
        toolbox.save_draft(["译文一", "译文二"])
        arguments = {"old_target": "译文一", "new_target": "新译文"}
        arguments[field] = "  "

        with pytest.raises(ValueError, match=rf"{field} 必须是非空字符串"):
            toolbox.execute("modify_draft", arguments)

        assert toolbox.current_draft == ["译文一", "译文二"]

    def test_rejects_missing_old_target_and_keeps_draft(self) -> None:
        toolbox, _, _ = build_toolbox()
        toolbox.save_draft(["译文一", "译文二"])

        with pytest.raises(ValueError, match="当前草稿中不存在"):
            toolbox.modify_draft("不存在的译文", "新译文")

        assert toolbox.current_draft == ["译文一", "译文二"]

    def test_rejects_ambiguous_old_target_and_keeps_draft(self) -> None:
        toolbox, _, _ = build_toolbox()
        toolbox.save_draft(["相同译文", "相同译文"])

        with pytest.raises(ValueError, match="当前草稿中不唯一"):
            toolbox.modify_draft("相同译文", "新译文")

        assert toolbox.current_draft == ["相同译文", "相同译文"]


class TestDispatch:
    def test_unknown_tool_is_rejected(self) -> None:
        toolbox, _, _ = build_toolbox()

        with pytest.raises(ValueError, match="未知 Tool"):
            toolbox.execute("does_not_exist", {})

    def test_chapter_digest_tool_is_exposed(self) -> None:
        toolbox, _, _ = build_toolbox()

        names = [item["function"]["name"] for item in toolbox.definitions]
        assert "update_chapter_digest" in names
        assert "modify_draft" in names


class TestChapterDigest:
    def test_update_changes_working_state_only(self) -> None:
        toolbox, committed, working = build_toolbox(["source"])

        result = toolbox.execute(
            "update_chapter_digest",
            {"chapter_digest": "  新的完整梗概  "},
        )

        assert working.translation_state.chapter_digest == "新的完整梗概"
        assert committed.chapter_digest == ""
        assert result.message == "章节梗概已更新：\n新的完整梗概"

    def test_empty_value_is_rejected(self) -> None:
        toolbox, committed, _ = build_toolbox(["source"])

        with pytest.raises(ValueError, match="非空字符串"):
            toolbox.execute("update_chapter_digest", {"chapter_digest": "  "})

        assert committed.chapter_digest == ""

    def test_more_than_600_characters_is_rejected(self) -> None:
        toolbox, committed, _ = build_toolbox(["source"])

        with pytest.raises(ValueError, match="不得超过 600 个字符"):
            toolbox.execute(
                "update_chapter_digest",
                {"chapter_digest": "梗" * 601},
            )

        assert committed.chapter_digest == ""


class TestGlossary:
    def test_existing_source_is_rejected(self) -> None:
        state = TranslationState(
            glossary_terms=[
                GlossaryTermInput(source="performative", target="施为性"),
            ]
        )
        toolbox, _, _ = build_toolbox(["performative"], state)

        with pytest.raises(ValueError, match="术语已存在，不能覆盖"):
            toolbox.execute(
                "add_glossary_terms",
                {
                    "terms": [
                        {
                            "source": "performative",
                            "target": "述行性",
                            "type": "术语",
                        }
                    ]
                },
            )

        assert state.glossary_terms == [
            GlossaryTermInput(source="performative", target="施为性"),
        ]

    def test_existing_source_match_is_case_insensitive(self) -> None:
        state = TranslationState(
            glossary_terms=[
                GlossaryTermInput(source="Performative", target="述行性"),
            ]
        )
        toolbox, _, _ = build_toolbox(["performative"], state)

        with pytest.raises(ValueError, match="术语已存在，不能覆盖"):
            toolbox.execute(
                "add_glossary_terms",
                {
                    "terms": [
                        {"source": "PERFORMATIVE", "target": "施为性"},
                    ]
                },
            )

        assert state.glossary_terms[0].source == "Performative"

    def test_existing_source_normalizes_apostrophe_format(self) -> None:
        state = TranslationState(
            glossary_terms=[
                GlossaryTermInput(source="Lefort's paradox", target="勒福尔悖论"),
            ]
        )
        toolbox, _, _ = build_toolbox(["Lefort’s paradox"], state)

        with pytest.raises(ValueError, match="术语已存在，不能覆盖"):
            toolbox.add_glossary_terms([{"source": "Lefort’s paradox", "target": "勒福尔悖论"}])

    def test_add_does_not_require_draft(self) -> None:
        toolbox, committed, working = build_toolbox(["performative shift"])

        toolbox.execute(
            "add_glossary_terms",
            {
                "terms": [
                    {
                        "source": "performative shift",
                        "target": "述行性转向",
                    }
                ]
            },
        )

        terms = working.translation_state.glossary_terms
        assert terms[0].target == "述行性转向"
        assert committed.glossary_terms == []

    def test_duplicate_source_in_one_call_is_rejected(self) -> None:
        toolbox, committed, _ = build_toolbox(["performative"])

        with pytest.raises(ValueError, match="source 不能重复"):
            toolbox.execute(
                "add_glossary_terms",
                {
                    "terms": [
                        {"source": "performative", "target": "述行性"},
                        {"source": "PERFORMATIVE", "target": "施为性"},
                    ]
                },
            )

        assert committed.glossary_terms == []

    def test_more_than_ten_terms_is_rejected(self) -> None:
        toolbox, committed, _ = build_toolbox(["source"])

        with pytest.raises(ValueError, match="一次最多提交 10 个术语"):
            toolbox.execute(
                "add_glossary_terms",
                {
                    "terms": [
                        {"source": f"source-{index}", "target": f"译文-{index}"}
                        for index in range(11)
                    ]
                },
            )

        assert committed.glossary_terms == []


class TestRaiseQuestion:
    def test_prints_question_and_returns_human_reply(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        toolbox, _, _ = build_toolbox()
        monkeypatch.setattr("builtins.input", lambda prompt: "采用“权威话语”")

        result = toolbox.execute(
            "raise_question",
            {"content": ("原文 authoritative discourse 应译为“权威话语”还是“权威性话语”？")},
        )

        terminal_output = capsys.readouterr().out
        assert "===== Agent 请求人工判断 =====" in terminal_output
        assert "authoritative discourse" in terminal_output
        assert result.message == "人类回复：采用“权威话语”"

    def test_rejects_empty_content(self) -> None:
        toolbox, _, _ = build_toolbox()

        with pytest.raises(ValueError, match="content 必须是非空字符串"):
            toolbox.execute("raise_question", {"content": "  "})


class TestSubmit:
    def test_requires_draft(self) -> None:
        toolbox, _, _ = build_toolbox()

        with pytest.raises(ValueError, match="先调用 save_draft"):
            toolbox.execute("submit_translation", {})

    def test_has_no_agent_arguments(self) -> None:
        toolbox, _, _ = build_toolbox()
        toolbox.save_draft(["译文一", "译文二"])

        result = toolbox.execute("submit_translation", {})

        assert result.output is not None
        assert result.output.targets == ["译文一", "译文二"]
