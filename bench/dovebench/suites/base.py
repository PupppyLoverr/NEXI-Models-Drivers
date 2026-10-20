"""Suite adapter interface.

A suite owns setup and checking; the driver owns every agent action. That is
the cua-bench split: OSWorld, Windows Agent Arena and MacArena each keep their
own controller for resetting the VM and running the checker, and the agent
never touches that controller.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    id: str
    domain: str
    instruction: str
    meta: dict = field(default_factory=dict)


class Suite:
    name = "base"

    def tasks(self, limit: int | None = None) -> list[Task]:
        raise NotImplementedError

    def environment(self) -> dict:
        """OS build, VM image, suite commit: recorded with every run."""
        return {}

    def prompt(self, task: Task) -> str:
        return task.instruction

    def reset(self, task: Task, config) -> None:
        """Bring the machine to the task's start state (a fresh snapshot per attempt)."""
        raise NotImplementedError

    def driver_command(self, config) -> tuple[list[str], dict]:
        """(argv, extra env) that starts the driver where the task runs. Local by default."""
        return config.command, config.env

    def evaluate(self, task: Task, final_answer: str) -> float:
        """Score in [0, 1] from the suite's own checker (1.0 = pass)."""
        raise NotImplementedError

    def cleanup(self, task: Task) -> None:
        pass

    def oracle(self, task: Task) -> dict:
        """Widget centres for the scripted stub model only. Real suites have none."""
        return {}
