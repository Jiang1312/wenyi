"""用 Wenyi 的 translate → polish → glossary 组件运行同一实验 fixture。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

# 这个脚本位于独立的 loop-lab；只为导入正式组件加入项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import (  # noqa: E402
    GlossaryTermInput,
    TranslationBatchOutput,
    validate_translation_output,
)
from run_fixture import load_fixture, make_batch_input  # noqa: E402

from state import TranslationState, normalize_term_source  # noqa: E402
from trans_novel.agents.polisher import Polisher  # noqa: E402
from trans_novel.assemble.translator import Translator  # noqa: E402
from trans_novel.config import Config  # noqa: E402
from trans_novel.glossary.extractor import GlossaryExtractor  # noqa: E402
from trans_novel.glossary.store import GlossaryTerm  # noqa: E402
from trans_novel.llm.factory import build_client  # noqa: E402
from trans_novel.llm.usage import usage_delta  # noqa: E402


def make_config(model: str, api_base: str) -> Config:
    """构造只包含本实验所需设置的正式 Wenyi 配置。"""

    return Config.from_dict(
        {
            "language": {"source": "en", "target": "zh"},
            "llm": {
                "provider": "deepseek",
                "base_url": api_base,
                "api_key_env": "DEEPSEEK_API_KEY",
                "timeout": 600,
                "max_retries": 4,
                "tiers": {
                    "strong": {
                        "model": model,
                        "options": {"thinking": True, "reasoning_effort": "high"},
                    },
                    "fast": {
                        "model": model,
                        "options": {"thinking": False},
                    },
                },
            },
            "pipeline": {
                "align_retry_limit": 2,
                "polish": True,
                "rolling_context_segments": 6,
                "book_understanding": False,
            },
            "punctuation": {"normalize": False},
        }
    )


def to_formal_term(term: GlossaryTermInput) -> GlossaryTerm:
    return GlossaryTerm(**asdict(term))


def to_input_term(term: GlossaryTerm) -> GlossaryTermInput:
    return GlossaryTermInput(
        source=term.source,
        target=term.target,
        reading=term.reading,
        type=term.type,
        gender=term.gender,
        aliases=list(term.aliases),
        note=term.note,
    )


def merge_terms(
    state: TranslationState,
    candidates: list[GlossaryTerm],
) -> tuple[list[GlossaryTermInput], list[dict]]:
    """把抽取结果写入实验内存；不同译法只记录冲突，不覆盖旧值。"""

    by_source = {normalize_term_source(term.source): term for term in state.glossary_terms}
    added: list[GlossaryTermInput] = []
    conflicts: list[dict] = []
    for candidate in candidates:
        key = normalize_term_source(candidate.source)
        existing = by_source.get(key)
        if existing is not None:
            if existing.target != candidate.target:
                conflicts.append(
                    {
                        "source": candidate.source,
                        "existing_target": existing.target,
                        "proposed_target": candidate.target,
                    }
                )
            continue
        term = to_input_term(candidate)
        state.add_glossary_terms([term])
        by_source[key] = term
        added.append(term)
    return added, conflicts


def write_trace(
    path: Path,
    *,
    fixture: Path,
    model: str,
    batches: list[dict],
    state: TranslationState,
    elapsed_seconds: float,
    usage: dict,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "experiment": "pipeline-baseline",
                "fixture": str(fixture),
                "model": model,
                "metrics": {
                    "elapsed_seconds": round(elapsed_seconds, 3),
                    "usage": usage,
                },
                "batches": batches,
                "translation_state": asdict(state),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run_pipeline(
    data: dict,
    state: TranslationState,
    *,
    config: Config,
    fixture_path: Path,
    trace_path: Path,
) -> list[TranslationBatchOutput]:
    """顺序运行正式翻译、润色和术语抽取组件。"""

    client = build_client(config)
    translator = Translator(client, config)
    polisher = Polisher(client, config)
    extractor = GlossaryExtractor(client, config)
    outputs: list[TranslationBatchOutput] = []
    batch_records: list[dict] = []
    recent_targets: list[str] = []
    run_started = perf_counter()

    for index, batch in enumerate(data["batches"], start=1):
        batch_started = perf_counter()
        usage_before = client.usage_summary()
        batch_input = replace(
            make_batch_input(data, batch["sources"], state),
            context="\n".join(recent_targets[-config.pipeline.rolling_context_segments :]),
        )
        terms = [to_formal_term(term) for term in batch_input.glossary_terms]

        stage_started = perf_counter()
        translated = translator.translate_batch(
            batch_input.sources,
            glossary_terms=terms,
            style=batch_input.style,
            context=batch_input.context,
            book_synopsis=batch_input.book_synopsis,
            chapter_digest=batch_input.chapter_digest,
        )
        translate_seconds = perf_counter() - stage_started

        stage_started = perf_counter()
        polished = polisher.polish(
            translated,
            glossary_terms=terms,
            style=batch_input.style,
        )
        polish_seconds = perf_counter() - stage_started
        output = TranslationBatchOutput(targets=polished)
        validate_translation_output(batch_input, output)

        stage_started = perf_counter()
        existing_terms = [to_formal_term(term) for term in state.glossary_terms]
        extracted = extractor.extract(
            "\n".join(batch_input.sources),
            "\n".join(output.targets),
            existing_terms,
        )
        added, conflicts = merge_terms(state, extracted)
        glossary_seconds = perf_counter() - stage_started

        recent_targets.extend(output.targets)
        recent_targets = recent_targets[-40:]
        outputs.append(output)
        usage_after = client.usage_summary()
        batch_records.append(
            {
                "batch": index,
                "status": "committed",
                "input": asdict(batch_input),
                "translated_targets": translated,
                "output": asdict(output),
                "extracted_terms": [asdict(term) for term in extracted],
                "added_terms": [asdict(term) for term in added],
                "term_conflicts": conflicts,
                "elapsed_seconds": round(perf_counter() - batch_started, 3),
                "stage_seconds": {
                    "translate": round(translate_seconds, 3),
                    "polish": round(polish_seconds, 3),
                    "glossary": round(glossary_seconds, 3),
                },
                "usage": usage_delta(usage_after, usage_before),
            }
        )
        write_trace(
            trace_path,
            fixture=fixture_path,
            model=config.llm.tiers["strong"].model or "",
            batches=batch_records,
            state=state,
            elapsed_seconds=perf_counter() - run_started,
            usage=usage_after,
        )
        print(
            f"batch {index}/{len(data['batches'])}: "
            f"{batch_records[-1]['elapsed_seconds']:.3f}s, "
            f"terms +{len(added)}, conflicts {len(conflicts)}",
            flush=True,
        )

    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "test_chapter.json",
    )
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument(
        "--trace-path",
        type=Path,
        default=Path(__file__).parent / "traces" / "pipeline-baseline.json",
    )
    args = parser.parse_args()

    data = load_fixture(args.fixture)
    state = TranslationState(
        chapter_digest=data.get("initial_chapter_digest", ""),
        glossary_terms=[GlossaryTermInput(**term) for term in data.get("initial_glossary", [])],
    )
    config = make_config(args.model, args.api_base)
    print(f"fixture: {args.fixture}")
    print(f"model: {args.model}")
    print(f"batches: {len(data['batches'])}")
    run_pipeline(
        data,
        state,
        config=config,
        fixture_path=args.fixture,
        trace_path=args.trace_path,
    )
    print(f"trace: {args.trace_path}")


if __name__ == "__main__":
    main()
