"""翻译任务 workflow。

职责：执行一个翻译 batch，把 TranslationTaskInput 组装为 prompt 和工具，
交给通用 AgentLoopRunner，并返回经过校验的译文和 consistency candidate。
本模块不读取或写入 State。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from ..config import Config
from ..llm import LLMClient, RetryConfig
from ..runner import AgentLoopRunner, TaskInput, TaskOutput
from .prompt import build_messages
from .task import TranslationTaskInput, validate_translation_output
from .tools import TranslationToolBox


class TranslationWorkflow:
    """执行一次翻译 batch 的任务入口。"""

    def __init__(self, runner: AgentLoopRunner) -> None:
        self.runner = runner

    @classmethod
    def from_config(cls, config: Config, client: object | None = None) -> TranslationWorkflow:
        """根据全局连接配置和翻译任务配置创建 workflow。"""

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
                retry_config=RetryConfig(
                    max_retries=config.llm.request_max_retries
                ),
                options=config.llm.options,
            )

        runner = AgentLoopRunner(
            client,
            max_rounds=config.runner.agent_loop.max_rounds,
            max_tool_calls=config.runner.agent_loop.max_tool_calls,
            max_retries=config.runner.agent_loop.max_retries,
        )
        return cls(runner)

    def run(
        self,
        task_input: TranslationTaskInput,
        *,
        task_id: str = "translation",
        existing_consistency_sources: set[str] | None = None,
        trace_writer: Callable[[dict[str, Any]], None] | None = None,
        trace_id: str | None = None,
    ) -> TaskOutput:
        """执行一次翻译任务，并返回通用任务结果。"""

        runner_input = TaskInput(
            task_id=task_id,
            task_type="translation",
            source=task_input,
            metadata={},
        )
        output = self.runner.run(
            runner_input,
            messages=build_messages(task_input),
            tool_factory=lambda: TranslationToolBox(
                task_input,
                existing_sources=existing_consistency_sources,
                enable_memory=True,
            ),
            trace_writer=trace_writer,
            trace_id=trace_id,
        )
        if not output.is_success:
            return output
        if isinstance(output.result, list):
            # 保持对旧 runner/tool 结果的兼容；新的 TranslationToolBox 返回 dict。
            targets = cast(list[str], output.result)
        elif isinstance(output.result, dict):
            targets = output.result.get("targets")
            if not isinstance(targets, list):
                raise TypeError("翻译任务结果的 targets 必须是 list")
        else:
            raise TypeError("翻译任务结果必须是 list 或 dict")
        validate_translation_output(task_input, targets)
        return output
