"""Memory task workflow：把 MemoryTaskInput 交给通用 AgentLoopRunner。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import Config
from ..llm import LLMClient, RetryConfig
from ..runner import AgentLoopRunner, TaskInput, TaskOutput
from .prompt import build_messages
from .schema import TopicDocument
from .task import MemoryTaskInput, MemoryTaskOutput
from .tools import MemoryToolBox


class MemoryWorkflow:
    """执行一次 CURRENT consolidation memory task。"""

    def __init__(self, runner: AgentLoopRunner) -> None:
        self.runner = runner

    @classmethod
    def from_config(cls, config: Config, client: object | None = None) -> MemoryWorkflow:
        if client is None:
            if not config.llm.api_key:
                raise ValueError("llm.api_key 不能为空")
            if not config.llm.model:
                raise ValueError("llm.model 不能为空")
            client = LLMClient(
                api_key=config.llm.api_key,
                provider=config.llm.provider,
                api_base=config.llm.base_url,
                model=config.llm.model,
                reasoning_effort=config.translation.reasoning_effort,
                retry_config=RetryConfig(max_retries=config.llm.request_max_retries),
                options=config.llm.options,
            )
        return cls(
            AgentLoopRunner(
                client,
                max_rounds=config.runner.agent_loop.max_rounds,
                max_tool_calls=config.runner.agent_loop.max_tool_calls,
                max_retries=config.runner.agent_loop.max_retries,
            )
        )

    def run(
        self,
        task_input: MemoryTaskInput,
        *,
        task_id: str = "memory",
        document_reader: Callable[[str], TopicDocument],
        source_reader: Callable[[list[dict[str, int]]], str],
        trace_writer: Callable[[dict[str, Any]], None] | None = None,
        trace_id: str | None = None,
    ) -> TaskOutput:
        runner_input = TaskInput(
            task_id=task_id,
            task_type="memory",
            source=task_input,
            metadata={},
        )
        output = self.runner.run(
            runner_input,
            messages=build_messages(task_input),
            tool_factory=lambda: MemoryToolBox(
                task_input,
                document_reader=document_reader,
                source_reader=source_reader,
            ),
            trace_writer=trace_writer,
            trace_id=trace_id,
        )
        if not output.is_success:
            return output
        result = output.result
        if not isinstance(result, dict) or not isinstance(result.get("writes"), list):
            raise TypeError("memory 任务结果必须包含 writes list")
        writes: list[TopicDocument] = []
        for item in result["writes"]:
            if not isinstance(item, dict):
                raise TypeError("memory write 必须是 dict")
            writes.append(
                TopicDocument(
                    document_id=item.get("document_id"),
                    summary=item.get("summary"),
                    content=item.get("content"),
                )
            )
        return TaskOutput(
            task_id=output.task_id,
            task_type=output.task_type,
            is_success=True,
            result=MemoryTaskOutput(writes=writes),
            error_message=None,
            usage=output.usage,
        )

