"""Transfer-evidence tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from murmur.core.types import TrajectoryResult
from scripts.transfer_deepseek_evidence import (
    EVENT_LOGS,
    render_transfer,
    transfer_evidence,
)


def _trajectory(
    trajectory_id: str,
    outcome: str,
    diagnostics: tuple[str, ...] = (),
) -> TrajectoryResult:
    return TrajectoryResult(
        trajectory_id=trajectory_id,
        outcome=outcome,
        output="",
        failure_class=None if outcome == "pass" else "contract_violation",
        cost_usd=0.0,
        latency_ms=0.0,
        diagnostic_ids=diagnostics,
    )


def test_shared_diagnostic_collapses_failures_to_one_witness() -> None:
    trajectories = tuple(
        _trajectory(
            f"failure_{index}",
            "fail",
            ("missing_metric_pass_hat_k",)
            if index < 9
            else ("missing_metric_pass_hat_k", "missing_accent_red"),
        )
        for index in range(10)
    )
    evidence = transfer_evidence(trajectories, runs=2)

    assert evidence.failures == 10
    assert evidence.shared_diagnostics == ("missing_metric_pass_hat_k",)
    assert evidence.failure_concentration == pytest.approx(0.82)
    assert evidence.effective_failure_witnesses == 1


def test_transfer_requires_a_shared_diagnostic() -> None:
    trajectories = (
        _trajectory("a", "fail", ("first",)),
        _trajectory("b", "fail", ("second",)),
    )

    with pytest.raises(ValueError, match="no shared failure diagnostic"):
        transfer_evidence(trajectories, runs=1)


def test_committed_deepseek_runs_reproduce_the_transfer_exhibit() -> None:
    root = Path(__file__).parents[1]
    output = render_transfer(tuple(root / path for path in EVENT_LOGS))
    note = (root / "docs" / "notes" / "deepseek-transfer.md").read_text(
        encoding="utf-8"
    )

    assert (
        "| 2 | 30 | 20 | 10 | missing_metric_pass_hat_k | 0.820 | 1 |"
        in output
    )
    assert output in note
