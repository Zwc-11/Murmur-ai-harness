"""Deterministic judge.

This file implements the cheap Tier 0 judge: compare the agent output against
the task contract before any future LLM-as-judge step is considered.
"""

from __future__ import annotations

from chorus.core.types import Outcome, TaskSpec


class DeterministicJudge:
    """Tier 0 judge: use the task contract before any expensive evaluator."""

    async def judge(self, task: TaskSpec, output: str) -> Outcome:
        return "pass" if task.accepts(output) else "fail"
