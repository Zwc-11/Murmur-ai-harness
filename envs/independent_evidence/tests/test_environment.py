"""Judge and tool-environment tests."""

from __future__ import annotations

import pytest

from envs.independent_evidence.environment import (
    ACTION_PRICES,
    STARTING_BUDGET,
    IndependentEvidenceEnv,
    load_environment,
)
from envs.independent_evidence.generator import generate_episode
from envs.independent_evidence.judge import (
    FALSE_ACCUSATION,
    brier_score,
    effective_witnesses,
    score_decision,
)


def test_brier_score_rewards_calibrated_correct_confidence() -> None:
    assert brier_score(0.8, True) > brier_score(0.6, True)
    assert brier_score(0.2, False) > brier_score(0.4, False)


def test_invalid_authored_test_is_rejected_and_charged() -> None:
    environment = IndependentEvidenceEnv(seed=7)

    result = environment.write_test("assert solve(100, 25) == 74")

    assert result == {"accepted": False, "test_id": None}
    assert environment.budget_remaining == STARTING_BUDGET - ACTION_PRICES["write_test"]
    assert environment.authored_tests == {}


def test_reference_execution_error_is_rejected_and_charged() -> None:
    environment = IndependentEvidenceEnv(seed=7)

    result = environment.write_test('assert solve("wrong type", 25) == 0')

    assert result == {"accepted": False, "test_id": None}
    assert environment.budget_remaining == STARTING_BUDGET - ACTION_PRICES["write_test"]


def test_all_tools_run_within_the_budget() -> None:
    environment = IndependentEvidenceEnv(seed=7)
    first = environment.read_bundle(1)
    visible = environment.run_tests(1, "visible")
    authored = environment.write_test("assert solve(100, 25) == 75.0")
    comparison = environment.run_test_all(authored["test_id"])
    fuzzed = environment.fuzz(1, (19.99, 15))
    overlay = environment.divergence()
    recruited = environment.recruit(environment.observation()["configs"][0])
    score = environment.decide("inconclusive", 0.5, 1.0, {})

    assert first["lane_id"] == environment.bundles[0].lane_id
    assert all(result["passed"] for result in visible)
    assert authored["accepted"]
    assert len(comparison) == 5
    assert fuzzed["args"] == (19.99, 15)
    assert overlay["first_step"] == 1
    assert recruited["lane_id"].endswith("recruit_1")
    assert score.decision == "inconclusive"
    assert environment.budget_remaining == 0


def test_budget_is_enforced_before_an_action_runs() -> None:
    environment = IndependentEvidenceEnv(seed=7)
    environment.recruit(environment.observation()["configs"][0])
    environment.recruit(environment.observation()["configs"][0])

    with pytest.raises(RuntimeError, match="costs 10; 4 remains"):
        environment.recruit(environment.observation()["configs"][0])

    assert len(environment.bundles) == 7


def test_false_accusation_has_a_strict_penalty() -> None:
    episode = generate_episode(13)
    wrong = episode.bundles[0]
    truth = effective_witnesses(episode, episode.bundles)
    correct_report = score_decision(
        episode,
        episode.bundles,
        "block",
        1.0,
        truth,
        {wrong.lane_id: wrong.family},
        spend=0,
    )
    false_report = score_decision(
        episode,
        episode.bundles,
        "block",
        1.0,
        truth,
        {wrong.lane_id: "invented"},
        spend=0,
    )

    assert correct_report.total - false_report.total == 2.0 + FALSE_ACCUSATION


def test_known_wrong_action_scores_below_inconclusive() -> None:
    episode = generate_episode(13)
    truth = effective_witnesses(episode, episode.bundles)
    wrong = score_decision(
        episode,
        episode.bundles,
        "ship 1",
        0.0,
        truth,
        {},
        spend=0,
    )
    inconclusive = score_decision(
        episode,
        episode.bundles,
        "inconclusive",
        0.5,
        truth,
        {},
        spend=0,
    )

    assert wrong.total < inconclusive.total


def test_gym_style_step_terminates_on_decision() -> None:
    environment = load_environment({"seed": 13})
    observation, info = environment.reset()
    observation, reward, terminated, truncated, info = environment.step(
        {
            "tool": "decide",
            "decision": "block",
            "probability": 1.0,
            "witnesses": effective_witnesses(
                environment.episode,
                tuple(environment.bundles),
            ),
            "report": {},
        }
    )

    assert info["result"]["decision_correct"]
    assert reward == 100.0
    assert terminated
    assert not truncated
    assert "write_test" in observation["instructions"]
    assert observation["bundle_count"] == 5


def test_inconclusive_probability_is_validated() -> None:
    environment = IndependentEvidenceEnv(seed=7)

    with pytest.raises(ValueError, match="probability"):
        environment.decide("inconclusive", 1.1, 1.0, {})
