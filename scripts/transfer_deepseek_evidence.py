"""Measure shared failure evidence across the two committed DeepSeek runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from murmur.core.metrics import failure_concentration
from murmur.core.results import result_from_events
from murmur.core.types import TrajectoryResult
from scripts.effective_evidence import load_events

EVENT_LOGS = (
    Path("docs/benchmarks/2026-07-01-deepseek/events.jsonl"),
    Path("docs/benchmarks/2026-07-02-deepseek-hard-n20/events.jsonl"),
)


@dataclass(frozen=True, slots=True)
class TransferEvidence:
    runs: int
    attempts: int
    passes: int
    failures: int
    shared_diagnostics: tuple[str, ...]
    failure_concentration: float
    effective_failure_witnesses: int


def transfer_evidence(
    trajectories: tuple[TrajectoryResult, ...],
    runs: int,
) -> TransferEvidence:
    failures = tuple(
        trajectory for trajectory in trajectories if trajectory.outcome != "pass"
    )
    diagnostic_sets = tuple(set(trajectory.diagnostic_ids) for trajectory in failures)
    if not diagnostic_sets or any(not diagnostics for diagnostics in diagnostic_sets):
        raise ValueError("every failed trajectory must carry a diagnostic ID")
    shared = set.intersection(*diagnostic_sets)
    if not shared:
        raise ValueError("the transfer corpus has no shared failure diagnostic")
    return TransferEvidence(
        runs=runs,
        attempts=len(trajectories),
        passes=len(trajectories) - len(failures),
        failures=len(failures),
        shared_diagnostics=tuple(sorted(shared)),
        failure_concentration=failure_concentration(failures),
        effective_failure_witnesses=1,
    )


def render_transfer(paths: tuple[Path, ...]) -> str:
    trajectories = tuple(
        trajectory
        for path in paths
        for trajectory in result_from_events(load_events(path)).trajectories
    )
    evidence = transfer_evidence(trajectories, runs=len(paths))
    shared = ", ".join(evidence.shared_diagnostics)
    return "\n".join(
        (
            "| runs | attempts | passes | failures | shared diagnostic | "
            "failure concentration | effective failure witnesses |",
            "| ---: | ---: | ---: | ---: | --- | ---: | ---: |",
            f"| {evidence.runs} | {evidence.attempts} | {evidence.passes} | "
            f"{evidence.failures} | {shared} | {evidence.failure_concentration:.3f} | "
            f"{evidence.effective_failure_witnesses} |",
        )
    )


def main() -> None:
    print(render_transfer(EVENT_LOGS))


if __name__ == "__main__":
    main()
