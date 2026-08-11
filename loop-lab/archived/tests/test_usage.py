"""真实运行统计使用的 LiteLLM usage 规整测试。"""

from types import SimpleNamespace

from loop import normalize_response_usage, summarize_usage


def test_normalizes_deepseek_cache_fields() -> None:
    response = SimpleNamespace(
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
        }
    )

    usage = normalize_response_usage(response)

    assert usage["cache_hit_tokens"] == 80
    assert usage["cache_miss_tokens"] == 20
    assert usage["cache_fields_available"] is True
    assert summarize_usage([usage])["cache_hit_rate"] == 0.8


def test_normalizes_openai_style_cached_tokens() -> None:
    response = SimpleNamespace(
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 64},
        }
    )

    usage = normalize_response_usage(response)

    assert usage["cache_hit_tokens"] == 64
    assert usage["cache_miss_tokens"] == 36
