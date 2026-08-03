"""基于 LiteLLM Tool Calling 的最小 Agent Loop。"""

import json
from dataclasses import asdict
from pathlib import Path

from litellm import completion
from models import TranslationBatchInput, TranslationBatchOutput
from tools import Toolbox

from state import BatchWorkingState, TranslationState

SYSTEM_PROMPT = """\
你是翻译 Agent。
用户输入是一个翻译 batch，各字段含义如下：
- sources：本批需要翻译的编号原文列表，每项包含 segment_number 和 text；
- glossary_terms：翻译时应遵守的术语及固定译法；
- style：目标译文的风格要求；
- context：当前文本之前的局部上下文；
- book_synopsis：全书主题、背景和主线概览；
- chapter_digest：截至当前 batch 之前已经确认的累计章节梗概。

你的基本任务是翻译 sources 中的全部原文。输出译文是与 sources 等长的列表，按编号顺序对应。
翻译时结合并遵守其他输入字段提供的信息。\
"""


def normalize_response_usage(response) -> dict:
    """把 LiteLLM response usage 整理为实验需要的共同字段。"""

    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        raw = usage.model_dump(exclude_none=True)
    elif isinstance(usage, dict):
        raw = dict(usage)
    else:
        raw = {}

    details = raw.get("prompt_tokens_details") or {}
    hit_value = raw.get("prompt_cache_hit_tokens")
    miss_value = raw.get("prompt_cache_miss_tokens")
    if hit_value is None and isinstance(details, dict):
        hit_value = details.get("cached_tokens")
    if hit_value is None:
        hit_value = raw.get("cache_read_input_tokens")
    if miss_value is None and hit_value is not None:
        miss_value = max(0, int(raw.get("prompt_tokens") or 0) - int(hit_value))

    return {
        "prompt_tokens": int(raw.get("prompt_tokens") or 0),
        "completion_tokens": int(raw.get("completion_tokens") or 0),
        "total_tokens": int(raw.get("total_tokens") or 0),
        "cache_hit_tokens": int(hit_value or 0),
        "cache_miss_tokens": int(miss_value or 0),
        "cache_fields_available": hit_value is not None and miss_value is not None,
        "raw": raw,
    }


def summarize_usage(samples: list[dict]) -> dict:
    """汇总一组已标准化的单次调用 usage。"""

    fields = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_hit_tokens",
        "cache_miss_tokens",
    )
    totals = {"calls": len(samples)}
    totals.update({field: sum(sample.get(field, 0) for sample in samples) for field in fields})
    cache_total = totals["cache_hit_tokens"] + totals["cache_miss_tokens"]
    totals["cache_hit_rate"] = (
        round(totals["cache_hit_tokens"] / cache_total, 4) if cache_total else 0.0
    )
    totals["cache_fields_available"] = bool(samples) and all(
        sample.get("cache_fields_available", False) for sample in samples
    )
    return totals


def agent_loop(
    batch_input: TranslationBatchInput,
    state: TranslationState,
    *,
    model: str,
    api_base: str | None = None,
    max_rounds: int = 20,
    max_tool_calls: int = 20,
    verbose: bool = False,
    trace_path: Path | None = None,
    trace_sink: list[dict] | None = None,
    usage_sink: list[dict] | None = None,
) -> TranslationBatchOutput:
    """调用模型和 Tools，直到 Agent 提交最终译文。"""

    working_state = BatchWorkingState.from_committed(state)
    toolbox = Toolbox(batch_input, working_state)
    model_input = asdict(batch_input)
    model_input["sources"] = [
        {"segment_number": index, "text": source}
        for index, source in enumerate(batch_input.sources, start=1)
    ]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(model_input, ensure_ascii=False, indent=2),
        },
    ]
    tool_call_count = 0
    trace = [{"round": 0, "model_input": messages.copy()}]

    try:
        for round_number in range(1, max_rounds + 1):
            if verbose:
                print(f"\n===== Round {round_number} =====")

            response = completion(
                model=model,
                api_base=api_base,
                messages=messages,
                tools=toolbox.definitions,
                tool_choice="auto",
            )
            choice = response.choices[0]
            message = choice.message
            model_output = message.model_dump(exclude_none=True)
            usage = normalize_response_usage(response)
            if usage_sink is not None and usage:
                usage_sink.append(usage)
            messages.append(model_output)

            reasoning = getattr(message, "reasoning_content", None)
            round_trace = {
                "round": round_number,
                "model_output": model_output,
                "usage": usage,
                "tool_calls": [],
            }
            trace.append(round_trace)

            if verbose:
                print(f"finish_reason: {getattr(choice, 'finish_reason', None)}")
                if reasoning:
                    print(f"reasoning:\n{reasoning}")
                if message.content:
                    print(f"content:\n{message.content}")

            if not message.tool_calls:
                raise RuntimeError("模型没有调用 Tool，翻译未完成")

            for tool_call in message.tool_calls:
                tool_call_count += 1
                if tool_call_count > max_tool_calls:
                    raise RuntimeError("Tool 调用次数超过限制")

                name = tool_call.function.name
                raw_arguments = tool_call.function.arguments or "{}"
                tool_trace = {
                    "name": name,
                    "arguments": raw_arguments,
                }
                round_trace["tool_calls"].append(tool_trace)

                if verbose:
                    print(f"tool: {name}")
                    print(f"arguments:\n{raw_arguments}")

                try:
                    arguments = json.loads(raw_arguments)
                    result = toolbox.execute(name, arguments)
                    content = result.message
                except Exception as error:
                    result = None
                    content = f"Tool 调用失败：{error}"

                tool_trace["result"] = content

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": content,
                    }
                )

                if verbose:
                    print(f"tool result: {content}")

                if result is not None and result.output is not None:
                    working_state.commit_to(state)
                    return result.output

        raise RuntimeError("Agent 轮数超过限制")
    finally:
        if trace_sink is not None:
            trace_sink.extend(trace)
        if trace_path is not None:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(
                json.dumps(trace, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
