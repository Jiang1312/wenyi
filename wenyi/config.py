"""第一版配置：只包含核心骨架需要的选项。"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .llm import ReasoningEffort


class TranslationConfig(BaseModel):
    reasoning_effort: ReasoningEffort = ReasoningEffort.HIGH
    max_chars_per_batch: int = Field(default=1800, gt=0)
    max_chars_per_segment: int = Field(default=1200, gt=0)
    context_segments: int = Field(default=6, ge=0)


class AgentLoopConfig(BaseModel):
    max_rounds: int = Field(default=12, ge=1, le=100)
    max_tool_calls: int = Field(default=20, ge=1, le=200)
    max_retries: int = Field(default=1, ge=0, le=10)


class RunnerConfig(BaseModel):
    agent_loop: AgentLoopConfig = Field(default_factory=AgentLoopConfig)


class LLMConfig(BaseModel):
    provider: str = "openai_compatible"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    timeout: int = Field(default=600, gt=0)
    request_max_retries: int = Field(default=4, ge=0, le=10)
    tiers: dict[str, dict] = Field(default_factory=dict)


class PathsConfig(BaseModel):
    state_dir: str = "state"
    output_dir: str = "output"


class Config(BaseModel):
    source_lang: str = "auto"
    target_lang: str = "zh"
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @classmethod
    def load(cls, path: str = "config.yaml") -> Config:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        language = raw.get("language") or {}
        return cls(
            source_lang=language.get("source", "auto"),
            target_lang=language.get("target", "zh"),
            translation=raw.get("translation") or {},
            runner=raw.get("runner") or {},
            llm=raw.get("llm") or {},
            paths=raw.get("paths") or {},
        )

    @staticmethod
    def create_default_file(path: str = "config.yaml") -> bool:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return False
        target.write_text(
            "language:\n  source: auto\n  target: zh\n"
            "translation:\n  max_chars_per_batch: 1800\n"
            "  reasoning_effort: high\n"
            "  max_chars_per_segment: 1200\n"
            "  context_segments: 6\n"
            "llm:\n  provider: openai_compatible\n  api_key: \"\"\n"
            "  base_url: https://api.openai.com/v1\n  model: \"\"\n"
            "  request_max_retries: 4\n"
            "runner:\n  agent_loop:\n    max_rounds: 12\n"
            "    max_tool_calls: 20\n    max_retries: 1\n"
            "paths:\n  state_dir: state\n  output_dir: output\n",
            encoding="utf-8",
        )
        return True
