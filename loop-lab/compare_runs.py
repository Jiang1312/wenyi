"""生成 Agent Loop 与固定 Pipeline 的可读对照报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from state import normalize_term_source


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def agent_section(trace: list[dict], key: str) -> dict:
    return next(item[key] for item in trace if key in item)


def term_map(terms: list[dict]) -> dict[str, dict]:
    return {normalize_term_source(term["source"]): term for term in terms}


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def usage_row(name: str, elapsed: float, usage: dict) -> str:
    return (
        f"| {name} | {elapsed:.3f} | {usage.get('calls', 0)} | "
        f"{usage.get('prompt_tokens', 0)} | {usage.get('completion_tokens', 0)} | "
        f"{usage.get('total_tokens', 0)} | {usage.get('cache_hit_tokens', 0)} | "
        f"{usage.get('cache_miss_tokens', 0)} | {usage.get('cache_hit_rate', 0):.2%} |"
    )


def build_report(fixture: dict, agent: list[dict], pipeline: dict) -> str:
    agent_metrics = agent_section(agent, "run_metrics")
    agent_state = agent_section(agent, "translation_state")
    pipeline_metrics = pipeline["metrics"]
    pipeline_usage = pipeline_metrics["usage"]["totals"]
    agent_usage = agent_metrics["usage"]

    lines = [
        "# Agent Loop 与固定 Pipeline 对照",
        "",
        "## 运行指标",
        "",
        "| 流程 | 秒 | 调用 | 输入 Token | 输出 Token | 总 Token | 缓存命中 | 缓存未命中 | 命中率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        usage_row("Agent Loop", agent_metrics["elapsed_seconds"], agent_usage),
        usage_row(
            "Translate + Polish + Glossary", pipeline_metrics["elapsed_seconds"], pipeline_usage
        ),
        "",
        "> 本次 Pipeline 前三批曾与一个意外重复启动的同配置进程重叠；"
        "Token 与输出来自当前完整 trace，wall time 与缓存命中率只作探索性参考。",
        "",
        "### Pipeline 分阶段",
        "",
        "| 阶段 | 调用 | 输入 Token | 输出 Token | 总 Token | 缓存命中 | 缓存未命中 | 命中率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for stage, usage in pipeline_metrics["usage"]["by_stage"].items():
        lines.append(
            f"| {stage} | {usage['calls']} | {usage['prompt_tokens']} | "
            f"{usage['completion_tokens']} | {usage['total_tokens']} | "
            f"{usage['cache_hit_tokens']} | {usage['cache_miss_tokens']} | "
            f"{usage['cache_hit_rate']:.2%} |"
        )

    agent_terms = term_map(agent_state["glossary_terms"])
    pipeline_terms = term_map(pipeline["translation_state"]["glossary_terms"])
    shared = sorted(agent_terms.keys() & pipeline_terms.keys())
    only_agent = sorted(agent_terms.keys() - pipeline_terms.keys())
    only_pipeline = sorted(pipeline_terms.keys() - agent_terms.keys())
    different = [
        key for key in shared if agent_terms[key]["target"] != pipeline_terms[key]["target"]
    ]
    same = [key for key in shared if key not in different]
    lines.extend(
        [
            "",
            "## 最终术语表",
            "",
            f"- Agent Loop：{len(agent_terms)} 项",
            f"- Pipeline：{len(pipeline_terms)} 项",
            f"- 共有且译法相同：{len(same)} 项",
            f"- 共有但译法不同：{len(different)} 项",
            f"- 仅 Agent Loop：{len(only_agent)} 项",
            f"- 仅 Pipeline：{len(only_pipeline)} 项",
            "",
            "| 原文 | Agent Loop | Pipeline | 分类 |",
            "|---|---|---|---|",
        ]
    )
    for key in sorted(set(agent_terms) | set(pipeline_terms)):
        a = agent_terms.get(key)
        p = pipeline_terms.get(key)
        if a and p:
            category = "相同" if a["target"] == p["target"] else "译法不同"
        else:
            category = "仅 Agent Loop" if a else "仅 Pipeline"
        lines.append(
            f"| {cell((a or p)['source'])} | {cell(a['target'] if a else '')} | "
            f"{cell(p['target'] if p else '')} | {category} |"
        )

    agent_batches = [item for item in agent if "batch" in item]
    pipeline_batches = pipeline["batches"]
    lines.extend(
        [
            "",
            "## 逐 Segment 译文",
            "",
            "Pipeline 栏为润色后的最终译文；润色前结果保存在 Pipeline JSON trace 中。",
            "",
            "| Segment | 原文 | Agent Loop | Pipeline |",
            "|---:|---|---|---|",
        ]
    )
    segment_number = 0
    for fixture_batch, agent_batch, pipeline_batch in zip(
        fixture["batches"], agent_batches, pipeline_batches
    ):
        for source, agent_target, pipeline_target in zip(
            fixture_batch["sources"],
            agent_batch["output"]["targets"],
            pipeline_batch["output"]["targets"],
        ):
            segment_number += 1
            lines.append(
                f"| {segment_number} | {cell(source)} | {cell(agent_target)} | "
                f"{cell(pipeline_target)} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--agent-trace", type=Path, required=True)
    parser.add_argument("--pipeline-trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(
        read_json(args.fixture),
        read_json(args.agent_trace),
        read_json(args.pipeline_trace),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"report: {args.output}")


if __name__ == "__main__":
    main()
