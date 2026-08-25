"""Agent Loop 工作模式。

职责：循环调用 LLM 和任务工具，直到工具返回最终结果，
或达到循环限制、Provider 调用失败。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import perf_counter
from typing import Any
from uuid import uuid4

from ..llm import LLMResponse, Message
from .task import TaskInput, TaskOutput
from .tools import ToolBox, ToolResult

_NO_TOOL_CALL_FEEDBACK = "任务尚未完成，请继续使用可用工具完成任务。"


class AgentLoopRunner:
    """通过多轮 LLM 调用和任务工具完成任务的执行器。"""

    def __init__(
        self,
        client: Any,
        *,
        max_rounds: int = 12,
        max_tool_calls: int = 20,
        max_retries: int = 0,
    ) -> None:
        self.client = client
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.max_retries = max_retries

    def run(
        self,
        task_input: TaskInput,
        *,
        messages: Sequence[Message],
        tool_factory: Callable[[], ToolBox],
        trace_writer: Callable[[dict[str, Any]], None] | None = None,
        trace_id: str | None = None,
    ) -> TaskOutput:
        """执行一个已经准备好消息和工具工厂的任务。"""

        usage = _UsageAccumulator()
        current_trace_id = trace_id or f"trace-{uuid4().hex}"
        next_trace_seq = 0

        def record_trace(kind: str, round_number: int, **data: Any) -> None:
            """组装并发送一条带有固定上下文的 trace 记录。"""

            nonlocal next_trace_seq
            if trace_writer is None:
                return
            trace_writer(
                {
                    "trace_id": current_trace_id,
                    "seq": next_trace_seq,
                    "task_type": task_input.task_type,
                    "task_id": task_input.task_id,
                    "round": round_number,
                    "kind": kind,
                    "data": data,
                }
            )
            next_trace_seq += 1

        if not callable(tool_factory):
            raise TypeError("Agent Loop 的 tool_factory 必须是可调用对象")

        for retry_number in range(max(0, self.max_retries) + 1):
            result, retryable = self._run_attempt(
                task_input,
                messages=list(messages),
                tools=tool_factory(),
                usage=usage,
                record_trace=record_trace,
            )
            if result.is_success or not retryable:
                return result
            if retry_number >= self.max_retries:
                return result

        raise RuntimeError("Agent Loop retry loop exited unexpectedly")

    def _run_attempt(
        self,
        task_input: TaskInput,
        *,
        messages: list[Message],
        tools: ToolBox,
        usage: _UsageAccumulator,
        record_trace: Callable[..., None],
    ) -> tuple[TaskOutput, bool]:
        """执行一次独立 Agent Loop，并返回是否值得重新尝试。"""

        conversation = list(messages)
        tool_calls_total = 0
        record_trace(
            "agent_start",
            0,
            messages=[message.model_dump(mode="json") for message in conversation],
            tools=tools.definitions,
        )

        for round_number in range(1, max(1, self.max_rounds) + 1):
            started_at = perf_counter()
            try:
                response = self.client.generate(
                    messages=conversation,
                    tools=tools.definitions,
                )
            except Exception as error:  # noqa: BLE001 - Provider 边界统一转为任务失败
                record_trace(
                    "model_error",
                    round_number,
                    error=str(error),
                    error_type=type(error).__name__,
                )
                record_trace(
                    "agent_error",
                    round_number,
                    reason="provider_error",
                    error=str(error),
                )
                return self._failure(task_input, str(error), usage.as_dict()), False

            usage.add(response)
            record_trace(
                "model_response",
                round_number,
                response=response.model_dump(mode="json"),
                message_count=len(conversation),
                duration_ms=round((perf_counter() - started_at) * 1000),
                usage=usage.as_dict(),
            )
            conversation.append(
                Message(
                    role="assistant",
                    content=response.content,
                    thinking=response.thinking,
                    tool_calls=response.tool_calls,
                )
            )

            if not response.tool_calls:
                conversation.append(
                    Message(role="user", content=_NO_TOOL_CALL_FEEDBACK)
                )
                record_trace(
                    "user_message",
                    round_number,
                    source="runtime",
                    content=_NO_TOOL_CALL_FEEDBACK,
                )
                continue

            for tool_call in response.tool_calls:
                tool_calls_total += 1
                if tool_calls_total > max(0, self.max_tool_calls):
                    record_trace(
                        "agent_error",
                        round_number,
                        reason="tool_call_limit",
                        tool_calls_total=tool_calls_total,
                    )
                    return self._failure(
                        task_input,
                        "Tool 调用次数超过限制",
                        usage.as_dict(),
                    ), True

                record_trace(
                    "tool_call",
                    round_number,
                    call_id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments,
                )
                result = self._execute_tool(
                    tools,
                    tool_call.function.name,
                    tool_call.function.arguments,
                )
                record_trace(
                    "tool_result",
                    round_number,
                    call_id=tool_call.id,
                    name=tool_call.function.name,
                    message=result.message,
                    output=result.output,
                )
                conversation.append(
                    Message(
                        role="tool",
                        content=result.message,
                        tool_call_id=tool_call.id,
                        name=tool_call.function.name,
                    )
                )

                if result.output is not None:
                    record_trace(
                        "agent_end",
                        round_number,
                        result=result.output,
                        usage=usage.as_dict(),
                    )
                    return TaskOutput(
                        task_id=task_input.task_id,
                        task_type=task_input.task_type,
                        is_success=True,
                        result=result.output,
                        error_message=None,
                        usage=usage.as_dict(),
                    ), False

        record_trace(
            "agent_error",
            max(1, self.max_rounds),
            reason="round_limit",
        )
        return self._failure(task_input, "Agent Loop 轮数超过限制", usage.as_dict()), True

    @staticmethod
    def _execute_tool(
        tools: ToolBox,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            return tools.execute(name, arguments)
        except Exception as error:  # noqa: BLE001 - Tool 错误反馈给模型继续处理
            return ToolResult(message=f"Tool 调用失败：{error}")

    @staticmethod
    def _failure(task_input: TaskInput, message: str, usage: dict[str, int]) -> TaskOutput:
        return TaskOutput(
            task_id=task_input.task_id,
            task_type=task_input.task_type,
            is_success=False,
            result=None,
            error_message=message,
            usage=usage,
        )


class _UsageAccumulator:
    """累计一次 Agent Loop 中每轮 LLM 调用的 token usage。"""

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def add(self, response: LLMResponse) -> None:
        self.calls += 1
        if response.usage is None:
            return
        self.prompt_tokens += response.usage.prompt_tokens
        self.completion_tokens += response.usage.completion_tokens
        self.total_tokens += response.usage.total_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
