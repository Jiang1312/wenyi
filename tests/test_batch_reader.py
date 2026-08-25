from dataclasses import dataclass

from wenyi.runner import read_batches, read_context
from wenyi.schema.document import Chapter, Segment


@dataclass
class FakeState:
    chapter: Chapter

    def load_chapter(self, chapter_index: int) -> Chapter:
        assert chapter_index == self.chapter.index
        return self.chapter


def test_read_batches_copies_old_wenyi_resume_semantics():
    chapter = Chapter(
        index=2,
        segments=[
            Segment(index=0, source="a"),
            Segment(index=1, source="bb"),
            Segment(index=2, source="ccc", target="已有译文"),
            Segment(index=3, source=""),
            Segment(index=4, source="d"),
        ],
    )

    batches = read_batches(FakeState(chapter), chapter_index=2, max_chars=3)

    assert [[segment.index for segment in batch] for batch in batches] == [
        [0, 1],
        [2],
        [4],
    ]


def test_read_batches_returns_original_segment_objects():
    segment = Segment(index=0, source="source")
    chapter = Chapter(index=0, segments=[segment])

    batches = read_batches(FakeState(chapter), chapter_index=0, max_chars=100)

    assert batches == [[segment]]
    assert batches[0][0] is segment


@dataclass
class FakeBookState:
    chapters: dict[int, Chapter]

    def load_manifest(self) -> dict[str, list[dict[str, int]]]:
        return {"chapters": [{"index": index} for index in self.chapters]}

    def load_chapter(self, chapter_index: int) -> Chapter:
        return self.chapters[chapter_index]


def test_read_context_returns_recent_completed_targets_before_current_batch():
    state = FakeBookState(
        chapters={
            0: Chapter(
                index=0,
                segments=[
                    Segment(index=0, source="old one", target="旧译一"),
                    Segment(index=1, source="old two", target="旧译二"),
                ],
            ),
            1: Chapter(
                index=1,
                segments=[
                    Segment(index=0, source="previous", target="当前前文"),
                    Segment(index=1, source="current"),
                ],
            ),
            2: Chapter(
                index=2,
                segments=[Segment(index=0, source="future", target="未来译文")],
            ),
        }
    )

    context = read_context(state, chapter_index=1, start_index=1, max_segments=2)

    assert context == "旧译二\n当前前文"
