import pytest

from wenyi.runner import (
    AgentLoopRunner,
    SingleCallRunner,
    TaskInput,
    TaskOutput,
    TaskRunner,
)


def _task_input() -> TaskInput:
    return TaskInput(
        task_id="translation-001",
        task_type="translation",
        source=["source"],
        metadata={},
    )


def test_task_input_and_output_are_unified_task_contracts():
    task_input = _task_input()
    task_output = TaskOutput(
        task_id=task_input.task_id,
        task_type=task_input.task_type,
        is_success=True,
        result=["target"],
        error_message=None,
        usage={},
    )

    assert task_input.task_type == "translation"
    assert task_output.is_success
    assert task_output.result == ["target"]


@pytest.mark.parametrize("runner_type", [SingleCallRunner, AgentLoopRunner])
def test_runners_expose_the_same_run_interface(runner_type: type[TaskRunner]):
    runner = runner_type(client=object())

    assert isinstance(runner, TaskRunner)
    assert callable(runner.run)


def test_single_call_runner_is_still_pending_implementation():
    runner = SingleCallRunner(client=object())

    with pytest.raises(NotImplementedError):
        runner.run(_task_input())
