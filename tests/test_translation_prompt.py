import json

from wenyi.llm import Message
from wenyi.translation import TranslationTaskInput, build_messages


def test_build_messages_matches_loop_lab_minimal_input_shape():
    messages = build_messages(
        TranslationTaskInput(
            sources=["原文一", "原文二"],
            source_lang="ja",
            target_lang="zh",
            context="前文译文一\n前文译文二",
        )
    )

    assert [message.role for message in messages] == ["system", "user"]
    assert isinstance(messages[0], Message)
    payload = json.loads(messages[1].content)
    assert payload == {
        "source_lang": "ja",
        "target_lang": "zh",
        "context": "前文译文一\n前文译文二",
        "sources": [
            {"segment_number": 1, "text": "原文一"},
            {"segment_number": 2, "text": "原文二"},
        ],
    }
