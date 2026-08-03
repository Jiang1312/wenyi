"""固定 Pipeline 实验适配中的内存术语合并测试。"""

from models import GlossaryTermInput
from run_pipeline_fixture import merge_terms

from state import TranslationState
from trans_novel.glossary.store import GlossaryTerm


def test_merge_extracted_terms_adds_new_and_records_conflict() -> None:
    state = TranslationState(
        glossary_terms=[GlossaryTermInput(source="performative", target="述行性")]
    )

    added, conflicts = merge_terms(
        state,
        [
            GlossaryTerm(source="hegemony", target="霸权"),
            GlossaryTerm(source="Performative", target="表演性"),
        ],
    )

    assert added == [GlossaryTermInput(source="hegemony", target="霸权")]
    assert conflicts == [
        {
            "source": "Performative",
            "existing_target": "述行性",
            "proposed_target": "表演性",
        }
    ]
    assert [term.source for term in state.glossary_terms] == ["performative", "hegemony"]
