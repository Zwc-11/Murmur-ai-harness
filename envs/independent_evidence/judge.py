"""Mechanical terminal judge for Independent Evidence Compiler episodes."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from envs.independent_evidence.generator import execute
from envs.independent_evidence.schema import AttemptBundle, Case, Episode, Observation

ACTION_CORRECT_POINTS = 80.0
BRIER_POINTS = 20.0
INCONCLUSIVE_SCORE = 25.0
CORRECT_ATTRIBUTION = 2.0
FALSE_ACCUSATION = 5.0
WITNESS_ERROR_PRICE = 5.0


@dataclass(frozen=True, slots=True)
class AuthoredTest:
    test_id: int
    args: tuple[object, ...]
    expected: object


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    decision: str
    decision_correct: bool | None
    brier: float | None
    decision_points: float
    effective_witnesses: float
    witness_error: float
    attribution_points: float
    spend: int
    total: float


def parse_authored_test(code: str, test_id: int) -> AuthoredTest:
    tree = ast.parse(code, mode="exec")
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
        raise ValueError("test must contain one assert statement")
    comparison = tree.body[0].test
    if (
        not isinstance(comparison, ast.Compare)
        or len(comparison.ops) != 1
        or not isinstance(comparison.ops[0], ast.Eq)
        or len(comparison.comparators) != 1
        or not isinstance(comparison.left, ast.Call)
        or not isinstance(comparison.left.func, ast.Name)
        or comparison.left.func.id != "solve"
        or comparison.left.keywords
    ):
        raise ValueError("test must be `assert solve(<literal args>) == <literal>`")
    args = tuple(ast.literal_eval(argument) for argument in comparison.left.args)
    expected = ast.literal_eval(comparison.comparators[0])
    return AuthoredTest(test_id=test_id, args=args, expected=expected)


def reference_accepts(episode: Episode, test: AuthoredTest) -> bool:
    expected = execute(episode.task.source, Case(test.args))
    return expected == Observation(value=test.expected)


def brier_score(probability: float, outcome: bool) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    return 1.0 - (probability - float(outcome)) ** 2


def effective_witnesses(
    episode: Episode,
    bundles: tuple[AttemptBundle, ...],
) -> float:
    configs = {bundle.config for bundle in bundles if bundle.visible_passed}
    return sum(
        episode.correlation_matrix[config].get("correct", 0.0) for config in configs
    )


def score_decision(
    episode: Episode,
    bundles: tuple[AttemptBundle, ...],
    decision: str,
    probability: float,
    witnesses: float,
    report: dict[str, str],
    spend: int,
) -> ScoreBreakdown:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    if witnesses < 0.0:
        raise ValueError("witness estimate must be non-negative")
    indexed = {bundle.lane_id: bundle for bundle in bundles}
    unknown = set(report) - indexed.keys()
    if unknown:
        raise ValueError(f"unknown report lane: {min(unknown)}")

    decision_correct = _decision_correct(decision, bundles)
    if decision_correct is None:
        points = INCONCLUSIVE_SCORE
        brier = None
    else:
        brier = brier_score(probability, decision_correct)
        points = ACTION_CORRECT_POINTS * float(decision_correct) + BRIER_POINTS * brier

    truth = effective_witnesses(episode, bundles)
    witness_error = abs(witnesses - truth)
    attribution_points = sum(
        CORRECT_ATTRIBUTION
        if not indexed[lane_id].hidden_correct and family == indexed[lane_id].family
        else -FALSE_ACCUSATION
        for lane_id, family in report.items()
    )
    total = points - WITNESS_ERROR_PRICE * witness_error + attribution_points - spend
    return ScoreBreakdown(
        decision=decision,
        decision_correct=decision_correct,
        brier=brier,
        decision_points=points,
        effective_witnesses=truth,
        witness_error=witness_error,
        attribution_points=attribution_points,
        spend=spend,
        total=total,
    )


def planted_upper_bound(episode: Episode) -> ScoreBreakdown:
    correct = next(
        (index for index, bundle in enumerate(episode.bundles, start=1) if bundle.hidden_correct),
        None,
    )
    decision = "block" if correct is None else f"ship {correct}"
    report = {
        bundle.lane_id: bundle.family
        for bundle in episode.bundles
        if not bundle.hidden_correct
    }
    witnesses = effective_witnesses(episode, episode.bundles)
    return score_decision(
        episode,
        episode.bundles,
        decision,
        probability=1.0,
        witnesses=witnesses,
        report=report,
        spend=0,
    )


def _decision_correct(
    decision: str,
    bundles: tuple[AttemptBundle, ...],
) -> bool | None:
    if decision == "block":
        return not any(bundle.hidden_correct for bundle in bundles)
    if decision == "inconclusive":
        return None
    parts = decision.split()
    if len(parts) != 2 or parts[0] != "ship":
        raise ValueError("decision must be `ship <index>`, `block`, or `inconclusive`")
    index = int(parts[1])
    if not 1 <= index <= len(bundles):
        raise ValueError("ship index is outside the bundle range")
    return bundles[index - 1].hidden_correct
