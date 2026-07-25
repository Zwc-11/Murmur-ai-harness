"""Scripted-baseline and calibration tests."""

from __future__ import annotations

from envs.independent_evidence.baselines import POLICIES, run_baselines
from envs.independent_evidence.calibrate import MINIMUM_GAP, calibrate


def test_baselines_are_seeded_and_run_end_to_end() -> None:
    first = run_baselines(3, seed=7)
    second = run_baselines(3, seed=7)

    assert first == second
    assert {result.name for result in first} == set(POLICIES)
    assert all(result.spend > 0 for result in first)


def test_calibration_clears_the_required_gap() -> None:
    report = calibrate(20, seed=7)

    assert report.accepted
    assert report.gap >= MINIMUM_GAP
