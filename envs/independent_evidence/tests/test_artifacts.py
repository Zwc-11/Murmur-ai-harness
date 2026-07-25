"""Acceptance-artifact tests."""

from __future__ import annotations

import json
from pathlib import Path

from envs.independent_evidence.calibrate import MINIMUM_GAP

PACKAGE = Path(__file__).parents[1]


def test_audit_contains_200_valid_episodes() -> None:
    lines = (PACKAGE / "audit" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()
    episodes = tuple(json.loads(line) for line in lines)

    assert len(episodes) == 200
    assert all(
        (bundle["family"] == "correct") == bundle["hidden_correct"]
        for episode in episodes
        for bundle in episode["bundles"]
    )


def test_calibration_artifact_clears_the_gap() -> None:
    report = json.loads(
        (PACKAGE / "audit" / "calibration.json").read_text(encoding="utf-8")
    )

    assert report["episodes"] == 200
    assert report["accepted"]
    assert report["gap"] >= MINIMUM_GAP


def test_demo_notebook_contains_executed_release_decision() -> None:
    notebook = json.loads((PACKAGE / "demo.ipynb").read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    output = "".join(code_cells[-1]["outputs"][0]["data"]["text/plain"])

    assert [cell["execution_count"] for cell in code_cells] == [1, 2, 3]
    assert "'green_runs': 5" in output
    assert "'effective_witnesses': 1.3" in output
    assert "'decision': 'block'" in output
    assert "'decision_correct': True" in output


def test_deepseek_reference_player_makes_the_correct_release_decision() -> None:
    result = json.loads(
        (PACKAGE / "audit" / "deepseek-reference.json").read_text(encoding="utf-8")
    )

    assert result["requested_model"] == "deepseek-v4-pro"
    assert result["served_models"] == ["deepseek-v4-pro"]
    assert result["score"]["decision"] == "block"
    assert result["score"]["decision_correct"]
