"""Generate the mandatory audit artifact for 200 seeded episodes."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from envs.independent_evidence.generator import generate_episodes
from envs.independent_evidence.schema import AttemptBundle, Episode, Observation, TestResult
from murmur.core.divergence import build_divergence_overlay


def episode_to_dict(episode: Episode) -> dict[str, Any]:
    return {
        "episode_id": episode.episode_id,
        "seed": episode.seed,
        "task": {
            "task_id": episode.task.task_id,
            "prompt": episode.task.prompt,
            "reference_source": episode.task.source,
            "cases": [case.args for case in episode.task.cases],
        },
        "visible_cases": [case.args for case in episode.visible_cases],
        "correlation_matrix": episode.correlation_matrix,
        "base_correct_rate": episode.base_correct_rate,
        "honeypot": episode.honeypot,
        "bundles": [_bundle_to_dict(bundle) for bundle in episode.bundles],
    }


def render_audit(episodes: tuple[Episode, ...]) -> str:
    label_checks = sum(
        _label_matches_behavior(bundle)
        for episode in episodes
        for bundle in episode.bundles
    )
    bundle_count = sum(len(episode.bundles) for episode in episodes)
    lines = [
        "# Independent Evidence Compiler — generator audit",
        "",
        f"Episodes: {len(episodes)}. Bundles: {bundle_count}. "
        f"Labels matching hidden behavior: {label_checks}/{bundle_count}.",
        "",
        "Review each planted family, visible-suite result, and first hidden behavior "
        "difference before approving judge work.",
    ]
    for episode in episodes:
        lines.extend(_episode_section(episode))
    return "\n".join(lines) + "\n"


def main() -> None:
    episodes = generate_episodes(200, seed=7)
    if not all(
        _label_matches_behavior(bundle)
        for episode in episodes
        for bundle in episode.bundles
    ):
        raise RuntimeError("generated family labels do not match hidden behavior")
    directory = Path(__file__).with_name("audit")
    directory.mkdir(exist_ok=True)
    jsonl = "\n".join(
        json.dumps(episode_to_dict(episode), sort_keys=True, ensure_ascii=False)
        for episode in episodes
    )
    (directory / "episodes.jsonl").write_text(jsonl + "\n", encoding="utf-8")
    (directory / "report.md").write_text(render_audit(episodes), encoding="utf-8")
    print(f"wrote {len(episodes)} episodes to {directory}")


def _bundle_to_dict(bundle: AttemptBundle) -> dict[str, Any]:
    return {
        "lane_id": bundle.lane_id,
        "config": bundle.config,
        "surface_cue": bundle.surface_cue,
        "patch": bundle.patch,
        "family": bundle.family,
        "mutation": bundle.mutation,
        "test_transcript": bundle.test_transcript,
        "visible_passed": bundle.visible_passed,
        "hidden_correct": bundle.hidden_correct,
        "visible_results": [_test_result_to_dict(result) for result in bundle.visible_results],
        "hidden_results": [_test_result_to_dict(result) for result in bundle.hidden_results],
        "trace": [event.to_dict() for event in bundle.trace],
    }


def _test_result_to_dict(result: TestResult) -> dict[str, Any]:
    return {
        "args": result.args,
        "expected": _observation_to_dict(result.expected),
        "actual": _observation_to_dict(result.actual),
        "passed": result.passed,
    }


def _observation_to_dict(observation: Observation) -> dict[str, Any]:
    return asdict(observation)


def _label_matches_behavior(bundle: AttemptBundle) -> bool:
    return (bundle.family == "correct") == bundle.hidden_correct


def _episode_section(episode: Episode) -> list[str]:
    events = [event for bundle in episode.bundles for event in bundle.trace]
    divergence = build_divergence_overlay(events).divergence_step
    lines = [
        "",
        f"## {episode.episode_id} — {episode.task.task_id}",
        "",
        f"- Seed: {episode.seed}",
        f"- Honeypot: {str(episode.honeypot).lower()}",
        f"- Base correct rate: {episode.base_correct_rate:.3f}",
        f"- First trace divergence step: {divergence}",
        f"- Visible cases: `{[case.args for case in episode.visible_cases]}`",
        f"- Correlation matrix: `{json.dumps(episode.correlation_matrix, sort_keys=True)}`",
        "",
        "| lane | config | cue | planted family | mutation | visible | hidden | label | "
        "first behavior difference |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_bundle_row(bundle) for bundle in episode.bundles)
    return lines


def _bundle_row(bundle: AttemptBundle) -> str:
    difference = next(
        (result for result in bundle.hidden_results if not result.passed),
        None,
    )
    if difference is None:
        detail = "none"
    else:
        detail = (
            f"args={difference.args!r}; expected={difference.expected!r}; "
            f"actual={difference.actual!r}"
        )
    return (
        f"| {bundle.lane_id.rsplit('_', 1)[-1]} | {bundle.config} | "
        f"{bundle.surface_cue} | {bundle.family} | {bundle.mutation or 'none'} | "
        f"{'pass' if bundle.visible_passed else 'fail'} | "
        f"{'correct' if bundle.hidden_correct else 'wrong'} | "
        f"{'valid' if _label_matches_behavior(bundle) else 'INVALID'} | {detail} |"
    )


if __name__ == "__main__":
    main()
