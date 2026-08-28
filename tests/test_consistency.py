import json
from pathlib import Path

import pytest

from wenyi.consistency import (
    ConsistencyRecord,
    find_exact_source_positions,
    match_exact,
    match_vague,
    update,
    write,
)
from wenyi.runner import local_to_global_positions
from wenyi.schema.document import Chapter, Document, Segment
from wenyi.state import StateStore


def test_exact_match_returns_all_segment_occurrences():
    records = [ConsistencyRecord("performative", "述行性", [])]

    matches = match_exact(
        records,
        ["A performative example", "unrelated", "performative dimension"],
    )

    assert matches == [(records[0], [1, 3])]


def test_exact_match_does_not_match_an_english_substring():
    records = [ConsistencyRecord("art", "艺术", [])]

    assert match_exact(records, ["partial result"]) == []


def test_vague_match_returns_each_pair_once():
    records = [
        ConsistencyRecord("performative", "述行性", []),
        ConsistencyRecord("performative", "述行性", []),
    ]

    assert match_vague(records, ["the performative dimension"]) == [records[0]]


def test_write_rejects_existing_source_and_update_deduplicates_positions():
    records: list[ConsistencyRecord] = []
    write(records, "performative", "述行性", [(1, 3)])
    update(records, "PERFORMATIVE", "述行性", [(1, 3), (1, 8)])

    assert records[0].occurrences == [(1, 3), (1, 8)]
    with pytest.raises(ValueError, match="已存在"):
        write(records, "performative", "表演性", [(2, 1)])
    with pytest.raises(ValueError, match="其他译法"):
        update(records, "performative", "表演性", [(2, 1)])


def test_candidate_source_positions_and_coordinate_conversion():
    local = find_exact_source_positions(
        "constative",
        ["first constative", "nothing", "constative again"],
    )
    batch = [
        Segment(index=12, source="first constative"),
        Segment(index=18, source="nothing"),
        Segment(index=24, source="constative again"),
    ]

    assert local == [1, 3]
    assert local_to_global_positions(
        chapter_index=3,
        batch=batch,
        local_positions=local,
    ) == [(3, 12), (3, 24)]


def test_state_store_persists_consistency_changes_with_batch(tmp_path):
    store = StateStore(str(tmp_path / "state"))
    document = Document(
        title="Book",
        source_lang="en",
        target_lang="zh",
        fmt="text",
        chapters=[
            Chapter(
                index=0,
                segments=[Segment(index=7, source="performative appears")],
            )
        ],
    )
    store.save_manifest(store.stage_document(document))

    store.commit_batch(
        task_id="batch-1",
        chapter_index=0,
        start_index=0,
        targets=["译文"],
        mode="agent_loop",
        consistency_writes=[
            {
                "source": "performative",
                "target": "述行性",
                "occurrences": [(0, 7)],
            }
        ],
    )

    assert store.load_consistency() == [
        ConsistencyRecord("performative", "述行性", [(0, 7)])
    ]
    event = json.loads(Path(store.event_log_path).read_text(encoding="utf-8").splitlines()[-1])
    assert event["event"] == "batch_committed"
    assert event["data"]["consistency"] == {
        "writes": [{"source": "performative", "target": "述行性"}],
        "updates": [],
    }
