"""Backward-compatible import path for the renamed protocol client."""

from ..openai_completion import OpenAICompletionClient

OpenAICompatibleClient = OpenAICompletionClient

__all__ = ["OpenAICompatibleClient", "OpenAICompletionClient"]
