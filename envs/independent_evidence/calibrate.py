"""Measure scripted baselines against the planted-information upper bound."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from envs.independent_evidence.baselines import POLICIES, run_baselines
from envs.independent_evidence.generator import generate_episodes
from envs.independent_evidence.judge import planted_upper_bound

MINIMUM_GAP = 15.0


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    episodes: int
    seed: int
    mean_scores: dict[str, float]
    mean_upper_bound: float
    best_baseline: str
    gap: float
    accepted: bool


def calibrate(count: int, seed: int) -> CalibrationReport:
    results = run_baselines(count, seed)
    means = {
        name: sum(result.score for result in results if result.name == name) / count
        for name in POLICIES
    }
    upper = (
        sum(planted_upper_bound(episode).total for episode in generate_episodes(count, seed))
        / count
    )
    best = max(means, key=means.__getitem__)
    gap = upper - means[best]
    return CalibrationReport(
        episodes=count,
        seed=seed,
        mean_scores=means,
        mean_upper_bound=upper,
        best_baseline=best,
        gap=gap,
        accepted=gap >= MINIMUM_GAP,
    )


def render_report(report: CalibrationReport) -> str:
    lines = [
        "# Independent Evidence Compiler — calibration",
        "",
        f"Episodes: {report.episodes}. Seed: {report.seed}.",
        "",
        "| policy | mean score |",
        "| --- | ---: |",
        *(
            f"| {name} | {score:.3f} |"
            for name, score in report.mean_scores.items()
        ),
        f"| planted-information upper bound | {report.mean_upper_bound:.3f} |",
        "",
        f"Best scripted baseline: {report.best_baseline}.",
        f"Gap to upper bound: {report.gap:.3f} points.",
        f"Acceptance threshold: {MINIMUM_GAP:.1f} points.",
        f"Environment accepted: {'yes' if report.accepted else 'no'}.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    report = calibrate(200, seed=7)
    directory = Path(__file__).with_name("audit")
    directory.mkdir(exist_ok=True)
    (directory / "calibration.json").write_text(
        json.dumps(asdict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / "calibration.md").write_text(render_report(report), encoding="utf-8")
    print(render_report(report))
    if not report.accepted:
        raise RuntimeError("scripted-baseline gap is below the acceptance threshold")


if __name__ == "__main__":
    main()
