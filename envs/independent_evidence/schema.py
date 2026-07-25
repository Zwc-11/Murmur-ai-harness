"""Generator schema for Independent Evidence Compiler episodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from murmur.core.events import Event


@dataclass(frozen=True, slots=True)
class Case:
    args: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    task_id: str
    prompt: str
    source: str
    cases: tuple[Case, ...]
    mutations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Observation:
    value: Any = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TestResult:
    args: tuple[Any, ...]
    expected: Observation
    actual: Observation

    @property
    def passed(self) -> bool:
        return self.expected == self.actual


@dataclass(frozen=True, slots=True)
class AttemptBundle:
    lane_id: str
    config: str
    surface_cue: str
    patch: str
    family: str
    mutation: str | None
    test_transcript: str
    visible_results: tuple[TestResult, ...]
    hidden_results: tuple[TestResult, ...]
    trace: tuple[Event, ...]

    @property
    def visible_passed(self) -> bool:
        return all(result.passed for result in self.visible_results)

    @property
    def hidden_correct(self) -> bool:
        return all(result.passed for result in self.hidden_results)


@dataclass(frozen=True, slots=True)
class Episode:
    episode_id: str
    seed: int
    task: TaskDefinition
    visible_cases: tuple[Case, ...]
    bundles: tuple[AttemptBundle, ...]
    correlation_matrix: dict[str, dict[str, float]]
    base_correct_rate: float
    honeypot: bool
