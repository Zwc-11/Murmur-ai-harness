"""Reliability metric calculations.

This file converts many trajectory outcomes into distribution-aware metrics.

Two pass rates are reported, and the difference between them is the whole point
of Murmur:

* ``pass@1`` -- the probability that a *single* run passes, estimated as the
  fraction of trajectories that passed (``c / n``). This is what a one-shot
  evaluation sees.
* ``pass^k`` -- the probability that *all* ``k`` runs pass, projected from the
  observed per-run rate as ``(c / n) ** k``. Reliability compounds, so an agent
  that looks fine at ``pass@1 = 0.7`` is only ``0.7 ** 12 = 1.4%`` reliable
  across 12 attempts. ``pass@1`` cannot tell ``7/10`` apart from ``10/10`` on a
  single noisy run; ``pass^k`` can.
"""

from __future__ import annotations

from collections import Counter
from math import comb, exp, log
from statistics import median

from murmur.core.divergence import cluster_signatures
from murmur.core.types import ReliabilityCurvePoint, ReliabilityMetrics, TrajectoryResult


def pass_at_1(successes: int, total: int) -> float:
    """Per-run pass-rate point estimate."""

    return successes / total if total else 0.0


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial pass rate."""

    if total == 0:
        return (0.0, 0.0)

    p_hat = successes / total
    denominator = 1 + z**2 / total
    center = (p_hat + z**2 / (2 * total)) / denominator
    margin = z * ((p_hat * (1 - p_hat) + z**2 / (4 * total)) / total) ** 0.5 / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


wilson_ci = wilson_interval


def pass_hat_k_parametric(successes: int, total: int, k: int) -> float:
    """Projected i.i.d. probability that all k independent runs pass."""

    return (successes / total) ** k if total else 0.0


def pass_hat_k_unbiased(successes: int, total: int, k: int) -> float:
    """Unbiased empirical estimator for all-k pass probability."""

    if k > successes or k > total or total == 0:
        return 0.0
    return comb(successes, k) / comb(total, k)


def reliability_curve(successes: int, total: int) -> tuple[ReliabilityCurvePoint, ...]:
    """Both pass^k estimators over k=1..N."""

    return tuple(
        ReliabilityCurvePoint(
            k=k,
            projected=pass_hat_k_parametric(successes, total, k),
            empirical=pass_hat_k_unbiased(successes, total, k),
        )
        for k in range(1, total + 1)
    )


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile_value)
    return ordered[index]


def failure_family(trajectory: TrajectoryResult) -> str:
    label = trajectory.failure_class or trajectory.outcome
    if not trajectory.diagnostic_ids:
        return label
    return f"{label} / {', '.join(sorted(trajectory.diagnostic_ids))}"


def failure_families(trajectories: tuple[TrajectoryResult, ...]) -> dict[str, int]:
    return dict(
        Counter(
            failure_family(trajectory)
            for trajectory in trajectories
            if trajectory.outcome != "pass"
        )
    )


def failure_concentration(trajectories: tuple[TrajectoryResult, ...]) -> float:
    """Herfindahl concentration of recorded failure families."""

    counts = failure_families(trajectories).values()
    total = sum(counts)
    return sum((count / total) ** 2 for count in counts) if total else 0.0


def effective_failure_families(trajectories: tuple[TrajectoryResult, ...]) -> float:
    """Entropy-equivalent number of recorded failure families."""

    counts = failure_families(trajectories).values()
    total = sum(counts)
    if not total:
        return 0.0
    entropy = -sum((count / total) * log(count / total) for count in counts)
    return exp(entropy)


def effective_witnesses(trajectories: tuple[TrajectoryResult, ...]) -> int:
    signatures = [
        trajectory.action_signature
        for trajectory in trajectories
        if trajectory.outcome == "pass"
    ]
    return len(cluster_signatures(signatures)) if signatures else 0


def reliability_metrics(
    trajectories: tuple[TrajectoryResult, ...],
    *,
    k: int | None = None,
) -> ReliabilityMetrics:
    """Fold trajectory outcomes into a distribution-aware reliability summary.

    ``k`` is the horizon for ``pass^k`` and defaults to the number of
    trajectories observed.
    """

    total = len(trajectories)
    passes = sum(1 for trajectory in trajectories if trajectory.outcome == "pass")
    pass_rate = pass_at_1(passes, total)
    horizon = k if k is not None else total
    latencies = [trajectory.latency_ms for trajectory in trajectories]
    costs = [trajectory.cost_usd for trajectory in trajectories]
    failures = Counter(
        trajectory.failure_class or trajectory.outcome
        for trajectory in trajectories
        if trajectory.outcome != "pass"
    )
    families = failure_families(trajectories)

    return ReliabilityMetrics(
        pass_at_1=pass_rate,
        pass_at_k=pass_hat_k_parametric(passes, total, horizon),
        k=horizon,
        variance=pass_rate * (1 - pass_rate),
        wilson_ci=wilson_interval(passes, total),
        mean_cost=sum(costs) / total if total else 0.0,
        p50_latency_ms=median(latencies) if latencies else 0.0,
        p95_latency_ms=percentile(latencies, 0.95),
        failure_concentration=failure_concentration(trajectories),
        effective_failure_families=effective_failure_families(trajectories),
        effective_witnesses=effective_witnesses(trajectories),
        failure_families=families,
        pass_at_k_unbiased=pass_hat_k_unbiased(passes, total, horizon),
        curve=reliability_curve(passes, total),
        failure_breakdown=dict(failures),
    )
