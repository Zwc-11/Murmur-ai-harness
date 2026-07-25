"""Scripted policies for measuring the environment's non-triviality."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from envs.independent_evidence.environment import IndependentEvidenceEnv
from envs.independent_evidence.judge import ScoreBreakdown

Policy = Callable[[IndependentEvidenceEnv], ScoreBreakdown]


@dataclass(frozen=True, slots=True)
class BaselineResult:
    name: str
    seed: int
    score: float
    decision_correct: bool | None
    spend: int


def ship_if_all_green(environment: IndependentEvidenceEnv) -> ScoreBreakdown:
    bundles = tuple(
        environment.read_bundle(index) for index in range(1, len(environment.bundles) + 1)
    )
    all_green = all(bundle["test_transcript"].endswith("0 failed") for bundle in bundles)
    decision = "ship 1" if all_green else "block"
    return environment.decide(
        decision,
        probability=0.9,
        witnesses=float(len(bundles)),
        report={},
    )


def majority_vote(environment: IndependentEvidenceEnv) -> ScoreBreakdown:
    bundles = tuple(
        environment.read_bundle(index) for index in range(1, len(environment.bundles) + 1)
    )
    patch, count = Counter(bundle["patch"] for bundle in bundles).most_common(1)[0]
    index = next(
        index
        for index, bundle in enumerate(bundles, start=1)
        if bundle["patch"] == patch
    )
    return environment.decide(
        f"ship {index}",
        probability=count / len(bundles),
        witnesses=float(len(set(bundle["patch"] for bundle in bundles))),
        report={},
    )


def codet_agreement(environment: IndependentEvidenceEnv) -> ScoreBreakdown:
    outcomes = tuple(
        environment.run_tests(index, "visible")
        for index in range(1, len(environment.bundles) + 1)
    )
    signatures = tuple(
        tuple(repr(result["actual"]) for result in results)
        for results in outcomes
    )
    signature, count = Counter(signatures).most_common(1)[0]
    index = signatures.index(signature) + 1
    return environment.decide(
        f"ship {index}",
        probability=count / len(signatures),
        witnesses=float(len(set(signatures))),
        report={},
    )


def uniform_spend(environment: IndependentEvidenceEnv) -> ScoreBreakdown:
    visible = environment.run_tests(1, "visible")
    args = list(visible[0]["args"])
    value = args[0]
    if isinstance(value, bool):
        args[0] = not value
    elif isinstance(value, int | float):
        args[0] = value + 1
    elif isinstance(value, str):
        args[0] = value + " "
    elif isinstance(value, list):
        args[0] = [*value, 0]
    elif value is None:
        args[0] = 0
    else:
        raise TypeError(f"unsupported generated argument: {type(value).__name__}")

    results = tuple(
        environment.fuzz(index, tuple(args))
        for index in range(1, len(environment.bundles) + 1)
    )
    passing = tuple(
        index for index, result in enumerate(results, start=1) if result["passed"]
    )
    decision = "block" if not passing else f"ship {passing[0]}"
    probability = 0.8 if not passing else len(passing) / len(results)
    signatures = {repr(result["actual"]) for result in results}
    return environment.decide(
        decision,
        probability=probability,
        witnesses=float(len(signatures)),
        report={},
    )


POLICIES: dict[str, Policy] = {
    "ship-if-all-green": ship_if_all_green,
    "majority-vote": majority_vote,
    "codet-agreement": codet_agreement,
    "uniform-spend": uniform_spend,
}


def run_baselines(count: int, seed: int) -> tuple[BaselineResult, ...]:
    if count < 1:
        raise ValueError("count must be positive")
    return tuple(
        _run_policy(name, policy, episode_seed)
        for episode_seed in range(seed, seed + count)
        for name, policy in POLICIES.items()
    )


def _run_policy(name: str, policy: Policy, seed: int) -> BaselineResult:
    score = policy(IndependentEvidenceEnv(seed))
    return BaselineResult(
        name=name,
        seed=seed,
        score=score.total,
        decision_correct=score.decision_correct,
        spend=score.spend,
    )
