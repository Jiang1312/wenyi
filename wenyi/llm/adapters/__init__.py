"""OpenAI Chat Completions provider dialect adapters."""

from . import deepseek, glm, hunyuan, openai

ADAPTERS = {
    "openai_compatible": openai,
    "deepseek": deepseek,
    "glm": glm,
    "hunyuan": hunyuan,
}


def get_adapter(provider: str):
    """Return the stateless adapter module for a configured provider."""

    try:
        return ADAPTERS[provider]
    except KeyError as error:
        raise ValueError(f"Unsupported provider: {provider}") from error


__all__ = ["ADAPTERS", "get_adapter"]
