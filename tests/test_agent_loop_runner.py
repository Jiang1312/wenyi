from dataclasses import dataclass

import pytest

from wenyi.llm import FunctionCall, LLMResponse, Message, TokenUsage, ToolCall
from wenyi.runner import AgentLoopRunner, TaskInput, ToolResult


def _task_input() -> TaskInput:
    return TaskInput(
        task_id="translation-001",
        task_type="translation",
        source=["原文"],
        metadata={},
    )


def _tool_call(call_id: str = "1") -> ToolCall:
    return ToolCall(
        id=call_id,
        type="function",
        function=FunctionCall(name="submit_translation", arguments={}),
    )


@dataclass
class FakeToolBox:
    responses: list[ToolResult]

    definitions: list[dict] = None

    def __post_init__(self) -> None:
        self.definitions = [
            {
                "type": "function",
                "function": {
                    "name": "submit_translation",
                    "description": "提交最终结果",
                    "parameters": {"type": "object"},
                },
            }
        ]
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, arguments: dict) -> ToolResult:
        self.calls.append((name, arguments))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[Message], list[dict]]] = []

    def generate(self, *, messages: list[Message], tools: list[dict]) -> LLMResponse:
        self.calls.append((list(messages), list(tools)))
        return self.responses.pop(0)


class TraceCollector:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def log_trace(self, record: dict) -> None:
        self.records.append(record)


def test_content_without_tool_call_continues_until_final_tool_result():
    client = FakeClient(
        [
            LLMResponse(content="我先分析一下", finish_reason="stop"),
            LLMResponse(
                content="",
                tool_calls=[_tool_call()],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            ),
        ]
    )
    toolbox = FakeToolBox([ToolResult(message="已提交", output=["译文"])])

    result = AgentLoopRunner(client, max_rounds=2).run(
        _task_input(),
        messages=[Message(role="system", content="翻译")],
        tool_factory=lambda: toolbox,
    )

    assert result.is_success
    assert result.result == ["译文"]
    assert len(client.calls) == 2
    assert client.calls[1][0][-1].content == "任务尚未完成，请继续使用可用工具完成任务。"
    assert result.usage == {
        "calls": 2,
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
    }


def test_tool_failure_is_returned_to_model_and_loop_continues():
    client = FakeClient(
        [
            LLMResponse(
                content="",
                tool_calls=[_tool_call("1")],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="",
                tool_calls=[_tool_call("2")],
                finish_reason="tool_calls",
            ),
        ]
    )
    toolbox = FakeToolBox([RuntimeError("校验失败"), ToolResult("已提交", ["译文"])])

    result = AgentLoopRunner(client, max_rounds=2).run(
        _task_input(),
        messages=[Message(role="system", content="翻译")],
        tool_factory=lambda: toolbox,
    )

    assert result.is_success
    assert len(client.calls) == 2
    assert "Tool 调用失败：校验失败" in client.calls[1][0][-1].content


def test_loop_fails_when_provider_errors_or_round_limit_is_reached():
    class FailingClient:
        def generate(self, **kwargs):
            raise RuntimeError("provider unavailable")

    provider_result = AgentLoopRunner(FailingClient()).run(
        _task_input(),
        messages=[Message(role="system", content="翻译")],
        tool_factory=lambda: FakeToolBox([]),
    )
    assert not provider_result.is_success
    assert provider_result.error_message == "provider unavailable"

    loop_result = AgentLoopRunner(
        FakeClient([LLMResponse(content="继续", finish_reason="stop")]),
        max_rounds=1,
    ).run(
        _task_input(),
        messages=[Message(role="system", content="翻译")],
        tool_factory=lambda: FakeToolBox([]),
    )
    assert not loop_result.is_success
    assert loop_result.error_message == "Agent Loop 轮数超过限制"


def test_agent_loop_requires_tool_factory():
    toolbox = FakeToolBox([])

    with pytest.raises(TypeError, match="tool_factory"):
        AgentLoopRunner(FakeClient([])).run(
            _task_input(),
            messages=[Message(role="system", content="翻译")],
            tool_factory=toolbox,
        )


def test_loop_fails_when_tool_call_limit_is_reached():
    client = FakeClient(
        [
            LLMResponse(
                content="",
                tool_calls=[_tool_call("1"), _tool_call("2")],
                finish_reason="tool_calls",
            )
        ]
    )
    toolbox = FakeToolBox([ToolResult(message="第一次调用完成")])

    result = AgentLoopRunner(client, max_tool_calls=1).run(
        _task_input(),
        messages=[Message(role="system", content="翻译")],
        tool_factory=lambda: toolbox,
    )

    assert not result.is_success
    assert result.error_message == "Tool 调用次数超过限制"
    assert toolbox.calls == [("submit_translation", {})]


def test_agent_loop_retries_round_limit_with_a_fresh_toolbox():
    client = FakeClient(
        [
            LLMResponse(content="继续", finish_reason="stop"),
            LLMResponse(
                content="",
                tool_calls=[_tool_call()],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            ),
        ]
    )
    toolboxes: list[FakeToolBox] = []

    def create_toolbox() -> FakeToolBox:
        toolbox = FakeToolBox([ToolResult(message="已提交", output=["译文"])])
        toolboxes.append(toolbox)
        return toolbox

    result = AgentLoopRunner(
        client,
        max_rounds=1,
        max_retries=1,
    ).run(
        _task_input(),
        messages=[Message(role="system", content="翻译")],
        tool_factory=create_toolbox,
    )

    assert result.is_success
    assert result.result == ["译文"]
    assert len(toolboxes) == 2
    assert toolboxes[0].calls == []
    assert toolboxes[1].calls == [("submit_translation", {})]
    assert result.usage == {
        "calls": 2,
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
    }


def test_agent_loop_writes_ordered_trace_records():
    client = FakeClient(
        [
            LLMResponse(content="我先分析一下", finish_reason="stop"),
            LLMResponse(
                content="",
                tool_calls=[_tool_call()],
                finish_reason="tool_calls",
            ),
        ]
    )
    toolbox = FakeToolBox([ToolResult(message="已提交", output=["译文"])])
    trace_collector = TraceCollector()

    result = AgentLoopRunner(client, max_rounds=2).run(
        _task_input(),
        messages=[Message(role="system", content="翻译")],
        tool_factory=lambda: toolbox,
        trace_writer=trace_collector.log_trace,
        trace_id="trace-test",
    )

    assert result.is_success
    assert [record["kind"] for record in trace_collector.records] == [
        "agent_start",
        "model_response",
        "user_message",
        "model_response",
        "tool_call",
        "tool_result",
        "agent_end",
    ]
    assert {record["trace_id"] for record in trace_collector.records} == {"trace-test"}
    assert [record["seq"] for record in trace_collector.records] == list(range(7))
