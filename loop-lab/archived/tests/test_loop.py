"""使用假 LiteLLM 响应测试 Loop，不访问网络。"""

import json
from types import SimpleNamespace

import loop
from models import TranslationBatchInput

from state import TranslationState


class FakeMessage:
    def __init__(self, tool_call):
        self.content = None
        self.tool_calls = [tool_call]

    def model_dump(self, *, exclude_none=False):
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ],
        }


def fake_response(call_id, name, arguments):
    call = SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    message = FakeMessage(call)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_loop_saves_and_submits(monkeypatch):
    responses = iter(
        [
            fake_response("1", "save_draft", '{"targets":["译文一","译文二"]}'),
            fake_response("2", "submit_translation", "{}"),
        ]
    )
    monkeypatch.setattr(loop, "completion", lambda **kwargs: next(responses))

    output = loop.agent_loop(
        TranslationBatchInput(sources=["source one", "source two"]),
        TranslationState(),
        model="fake/model",
    )

    assert output.targets == ["译文一", "译文二"]


def test_loop_writes_trace(monkeypatch, tmp_path):
    responses = iter(
        [
            fake_response("1", "save_draft", '{"targets":["译文一","译文二"]}'),
            fake_response("2", "submit_translation", "{}"),
        ]
    )
    monkeypatch.setattr(loop, "completion", lambda **kwargs: next(responses))
    trace_path = tmp_path / "trace.json"

    loop.agent_loop(
        TranslationBatchInput(sources=["source one", "source two"]),
        TranslationState(),
        model="fake/model",
        trace_path=trace_path,
    )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace[0]["round"] == 0
    assert trace[0]["model_input"][0]["content"] == loop.SYSTEM_PROMPT
    user_input = json.loads(trace[0]["model_input"][1]["content"])
    assert user_input["sources"] == [
        {"segment_number": 1, "text": "source one"},
        {"segment_number": 2, "text": "source two"},
    ]
    assert [call["name"] for round_trace in trace[1:] for call in round_trace["tool_calls"]] == [
        "save_draft",
        "submit_translation",
    ]
    assert len(trace) == 3
    assert trace[1]["model_output"]["role"] == "assistant"


def test_loop_collects_trace_in_memory(monkeypatch):
    responses = iter(
        [
            fake_response("1", "save_draft", '{"targets":["译文"]}'),
            fake_response("2", "submit_translation", "{}"),
        ]
    )
    monkeypatch.setattr(loop, "completion", lambda **kwargs: next(responses))
    trace = []

    loop.agent_loop(
        TranslationBatchInput(sources=["source"]),
        TranslationState(),
        model="fake/model",
        trace_sink=trace,
    )

    assert [item["round"] for item in trace] == [0, 1, 2]


def test_loop_updates_chapter_digest(monkeypatch):
    responses = iter(
        [
            fake_response(
                "1",
                "update_chapter_digest",
                '{"chapter_digest":"累计章节梗概"}',
            ),
            fake_response("2", "save_draft", '{"targets":["译文"]}'),
            fake_response("3", "submit_translation", "{}"),
        ]
    )
    monkeypatch.setattr(loop, "completion", lambda **kwargs: next(responses))
    state = TranslationState()

    output = loop.agent_loop(
        TranslationBatchInput(sources=["source"]),
        state,
        model="fake/model",
    )

    assert state.chapter_digest == "累计章节梗概"
    assert output.targets == ["译文"]


def test_loop_returns_human_reply_to_agent(monkeypatch):
    responses = iter(
        [
            fake_response(
                "1",
                "raise_question",
                '{"content":"这里应该采用哪个译法？"}',
            ),
            fake_response("2", "save_draft", '{"targets":["人工确认后的译文"]}'),
            fake_response("3", "submit_translation", "{}"),
        ]
    )
    model_inputs = []

    def fake_completion(**kwargs):
        model_inputs.append(json.loads(json.dumps(kwargs["messages"])))
        return next(responses)

    monkeypatch.setattr(loop, "completion", fake_completion)
    monkeypatch.setattr("builtins.input", lambda prompt: "采用第二种译法")

    output = loop.agent_loop(
        TranslationBatchInput(sources=["source"]),
        TranslationState(),
        model="fake/model",
    )

    assert model_inputs[1][-1] == {
        "role": "tool",
        "tool_call_id": "1",
        "content": "人类回复：采用第二种译法",
    }
    assert output.targets == ["人工确认后的译文"]
