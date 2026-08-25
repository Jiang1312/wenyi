import json
from pathlib import Path

from wenyi.export import assemble
from wenyi.ingest import load_document
from wenyi.state import StateStore


def test_text_ingest_state_commit_and_export(tmp_path: Path):
    source = tmp_path / "book.txt"
    source.write_text("第一段。\n\n第二段。", encoding="utf-8")

    document = load_document(str(source), "zh", "zh")
    store = StateStore(str(tmp_path / "state"))
    manifest = store.stage_document(document)
    store.save_manifest(manifest)

    store.commit_batch(
        task_id="book-batch-0001",
        chapter_index=0,
        start_index=0,
        targets=["译文一", "译文二"],
        mode="single_call",
    )

    output = tmp_path / "book.out.txt"
    assemble(store, str(source), str(output), "txt", about_page=False)

    assert output.read_text(encoding="utf-8") == "译文一\n\n译文二\n"
    events = (tmp_path / "state" / "logs" / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"event": "batch_committed"' in events
    event = json.loads(events.splitlines()[0])
    assert event["data"]["count"] == 2
    assert not (tmp_path / "state" / "translation").exists()
    assert not (tmp_path / "state" / "traces").exists()
    assert store.pending_chapters() == []


def test_failed_source_digest_does_not_write_targets(tmp_path: Path):
    source = tmp_path / "book.txt"
    source.write_text("第一段。", encoding="utf-8")
    document = load_document(str(source), "zh", "zh")
    store = StateStore(str(tmp_path / "state"))
    manifest = store.stage_document(document)
    store.save_manifest(manifest)

    try:
        store.commit_batch(
            task_id="book-batch-0001",
            chapter_index=0,
            start_index=0,
            targets=["译文"],
            mode="agent_loop",
            expected_source_digest="not-the-current-digest",
        )
    except ValueError as error:
        assert "源文已变化" in str(error)
    else:
        raise AssertionError("expected source digest mismatch")

    assert store.load_chapter(0).text_segments[0].target is None
