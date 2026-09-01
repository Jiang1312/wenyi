import json

from wenyi.memory import MemoryTaskInput, TopicDocument
from wenyi.memory.tools import MemoryToolBox
from wenyi.runner import read_indexed_context
from wenyi.schema.document import Chapter, Document, Segment
from wenyi.state import GlobalSegmentIndex, StateStore


def _store(tmp_path):
    store = StateStore(str(tmp_path / "state"))
    document = Document(
        title="Book",
        source_lang="en",
        target_lang="zh",
        fmt="text",
        chapters=[
            Chapter(
                index=0,
                segments=[
                    Segment(index=4, source="source one", target="译文一"),
                    Segment(index=8, source="source two", target="译文二"),
                ],
            )
        ],
    )
    store.save_manifest(store.stage_document(document))
    return store


def test_memory_documents_and_current_are_persisted(tmp_path):
    store = _store(tmp_path)
    store.append_memory_current(
        [
            {
                "content": "A fact",
                "indexes": [GlobalSegmentIndex(0, 4), GlobalSegmentIndex(0, 8)],
                "evidence": "source one",
            }
        ]
    )
    assert "chapter=0, segment=4" in store.load_memory_current()

    store.commit_memory_task(
        [TopicDocument(None, "topic summary", "## Facts\n\n- A fact")]
    )
    catalog = store.list_memory_documents()
    assert len(catalog) == 1
    assert catalog[0].summary == "topic summary"
    assert store.read_memory_document(catalog[0].document_id).content == "## Facts\n\n- A fact"
    assert store.load_memory_current() == ""


def test_memory_tool_stages_existing_and_new_documents(tmp_path):
    store = _store(tmp_path)
    store.commit_memory_task([TopicDocument("relations", "relations", "## A\n\n- old")])
    catalog = store.list_memory_documents()
    toolbox = MemoryToolBox(
        MemoryTaskInput("current", catalog),
        document_reader=store.read_memory_document,
        source_reader=lambda indexes: json.dumps(indexes),
    )
    toolbox.execute(
        "write_memory_document",
        {"document_id": "relations", "summary": "relations", "content": "## A\n\n- new"},
    )
    toolbox.execute(
        "write_memory_document",
        {"document_id": None, "summary": "new", "content": "## B\n\n- fact"},
    )
    result = toolbox.execute("submit_memory", {})
    assert len(result.output["writes"]) == 2
    assert store.read_memory_document("relations").content == "## A\n\n- old"


def test_read_indexed_context_returns_source_and_translation(tmp_path):
    store = _store(tmp_path)
    context = read_indexed_context(store, [GlobalSegmentIndex(0, 8)])
    assert '"source": "source two"' in context
    assert '"target": "译文二"' in context
