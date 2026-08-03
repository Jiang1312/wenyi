"""按章节顺序使用真实 LiteLLM API 运行实验 fixture。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Callable

from loop import agent_loop, summarize_usage
from models import GlossaryTermInput, TranslationBatchInput, TranslationBatchOutput
from rapidfuzz import fuzz

from state import TranslationState, normalize_term_source

AgentLoop = Callable[..., TranslationBatchOutput]
GLOSSARY_MATCH_SCORE = 80.0


def write_test_trace(
    trace_path: Path | None,
    batch_records: list[dict],
    state: TranslationState,
    run_metrics: dict | None = None,
) -> None:
    if trace_path is None:
        return
    trace = [*batch_records]
    if run_metrics is not None:
        trace.append({"run_metrics": run_metrics})
    trace.append({"translation_state": asdict(state)})
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_glossary_terms(
    sources: list[str],
    glossary_terms: list[GlossaryTermInput],
) -> list[GlossaryTermInput]:
    """筛出 source 与当前 batch 原文局部相似的已有术语。"""

    batch_text = normalize_term_source("\n".join(sources))
    return [
        term
        for term in glossary_terms
        if fuzz.partial_ratio(
            normalize_term_source(term.source),
            batch_text,
            score_cutoff=GLOSSARY_MATCH_SCORE,
        )
    ]


def make_batch_input(
    data: dict,
    sources: list[str],
    state: TranslationState,
) -> TranslationBatchInput:
    return TranslationBatchInput(
        sources=sources,
        glossary_terms=find_glossary_terms(sources, state.glossary_terms),
        style=data.get("style", ""),
        context=data.get("context", ""),
        book_synopsis=data.get("book_synopsis", ""),
        chapter_digest=state.chapter_digest,
    )


def run_chapter(
    data: dict,
    state: TranslationState,
    *,
    model: str,
    api_base: str | None = None,
    trace_path: Path | None = None,
    run_agent: AgentLoop = agent_loop,
) -> list[TranslationBatchOutput]:
    """顺序运行一章的所有 batch，每批都读取最新的章节状态。"""

    outputs = []
    test_trace = []
    usage_samples = []
    run_started = perf_counter()
    for index, batch in enumerate(data["batches"], start=1):
        batch_input = make_batch_input(data, batch["sources"], state)
        batch_trace = []
        batch_usage = []
        batch_started = perf_counter()
        try:
            output = run_agent(
                batch_input,
                state,
                model=model,
                api_base=api_base,
                trace_sink=batch_trace,
                usage_sink=batch_usage,
            )
        except Exception as error:
            usage_samples.extend(batch_usage)
            test_trace.append(
                {
                    "batch": index,
                    "status": "failed",
                    "elapsed_seconds": round(perf_counter() - batch_started, 3),
                    "usage": summarize_usage(batch_usage),
                    "trace": batch_trace,
                    "error": {
                        "type": type(error).__name__,
                        "message": str(error),
                    },
                }
            )
            write_test_trace(
                trace_path,
                test_trace,
                state,
                {
                    "elapsed_seconds": round(perf_counter() - run_started, 3),
                    "usage": summarize_usage(usage_samples),
                },
            )
            raise
        usage_samples.extend(batch_usage)
        outputs.append(output)
        test_trace.append(
            {
                "batch": index,
                "status": "committed",
                "elapsed_seconds": round(perf_counter() - batch_started, 3),
                "usage": summarize_usage(batch_usage),
                "output": asdict(output),
                "trace": batch_trace,
            }
        )
        write_test_trace(
            trace_path,
            test_trace,
            state,
            {
                "elapsed_seconds": round(perf_counter() - run_started, 3),
                "usage": summarize_usage(usage_samples),
            },
        )
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "test_chapter.json",
    )
    parser.add_argument("--model", default="deepseek/deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument(
        "--trace-path",
        type=Path,
        help="将完整测试的 trace 写入一个 JSON 文件",
    )
    args = parser.parse_args()

    data = load_fixture(args.fixture)
    initial_glossary = [GlossaryTermInput(**term) for term in data.get("initial_glossary", [])]
    state = TranslationState(
        chapter_digest=data.get("initial_chapter_digest", ""),
        glossary_terms=initial_glossary,
    )

    print(f"fixture: {args.fixture}")
    print(f"book: {data.get('book', '')}")
    print(f"chapter: {data.get('chapter', '')}")
    print(f"model: {args.model}")
    print(f"batches: {len(data['batches'])}")

    outputs = run_chapter(
        data,
        state,
        model=args.model,
        api_base=args.api_base,
        trace_path=args.trace_path,
    )
    for index, output in enumerate(outputs, start=1):
        print(f"\n===== Batch {index} Translation =====")
        print(json.dumps(output.targets, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
