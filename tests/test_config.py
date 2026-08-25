from pathlib import Path

from wenyi.config import Config
from wenyi.llm import ReasoningEffort
from wenyi.translation import TranslationWorkflow


def test_default_config_file_contains_current_mvp_settings(tmp_path: Path):
    path = tmp_path / "config.yaml"

    assert Config.create_default_file(str(path))
    config = Config.load(str(path))

    assert config.llm.provider == "openai_compatible"
    assert config.llm.request_max_retries == 4
    assert config.paths.state_dir == "state"
    assert config.translation.reasoning_effort == ReasoningEffort.HIGH
    assert config.translation.context_segments == 6
    assert config.runner.agent_loop.max_rounds == 12
    assert config.runner.agent_loop.max_tool_calls == 20
    assert config.runner.agent_loop.max_retries == 1
    assert not hasattr(config.translation, "agent_max_rounds")
    assert not hasattr(config.translation, "agent_max_tool_calls")
    assert not hasattr(config.translation, "agent_max_retries")
    assert not hasattr(config.translation, "mode")


def test_translation_workflow_configures_llm_reasoning_effort(tmp_path: Path):
    path = tmp_path / "config.yaml"
    Config.create_default_file(str(path))
    config = Config.load(str(path))
    config.llm.api_key = "test-key"
    config.llm.model = "test-model"

    workflow = TranslationWorkflow.from_config(config)

    assert workflow.runner.client.reasoning_effort == ReasoningEffort.HIGH
