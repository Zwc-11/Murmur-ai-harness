"""Budgeted tool environment for correlation-aware release decisions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from envs.independent_evidence.generator import (
    execute,
    generate_episode,
    recruit_bundle,
    test_results,
)
from envs.independent_evidence.judge import (
    AuthoredTest,
    ScoreBreakdown,
    parse_authored_test,
    reference_accepts,
    score_decision,
)
from envs.independent_evidence.schema import AttemptBundle, Case, TestResult
from murmur.core.divergence import build_divergence_overlay

STARTING_BUDGET = 24
PLAYER_INSTRUCTIONS = (
    "Five agent lanes attempted the task. Passing bundles may share a misconception. "
    "Spend the listed budget with read_bundle(index), run_tests(index, 'visible'), "
    "write_test(code), run_test_all(test_id), fuzz(index, args), divergence(), or "
    "recruit(config). Finish with decide('ship <index>'|'block'|'inconclusive', "
    "probability, effective_witnesses, {lane_id: failure_family}); inconclusive receives "
    "25 points before witness, attribution, and spend adjustments."
)
ACTION_PRICES = {
    "read_bundle": 1,
    "run_tests": 2,
    "write_test": 3,
    "run_test_all": 2,
    "fuzz": 4,
    "divergence": 2,
    "recruit": 10,
    "decide": 0,
}


class IndependentEvidenceEnv:
    def __init__(self, seed: int) -> None:
        self._seed = seed
        self.episode = generate_episode(seed)
        self.bundles = list(self.episode.bundles)
        self.budget_remaining = STARTING_BUDGET
        self.authored_tests: dict[int, AuthoredTest] = {}
        self.actions: list[str] = []
        self.terminated = False
        self.score: ScoreBreakdown | None = None
        self._recruits = 0

    @property
    def spend(self) -> int:
        return STARTING_BUDGET - self.budget_remaining

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if options:
            raise ValueError("reset options are not supported")
        if seed is not None:
            self._seed = seed
        self.episode = generate_episode(self._seed)
        self.bundles = list(self.episode.bundles)
        self.budget_remaining = STARTING_BUDGET
        self.authored_tests = {}
        self.actions = []
        self.terminated = False
        self.score = None
        self._recruits = 0
        return self.observation(), {"episode_id": self.episode.episode_id}

    def observation(self) -> dict[str, Any]:
        return {
            "instructions": PLAYER_INSTRUCTIONS,
            "task": self.episode.task.prompt,
            "bundle_count": len(self.bundles),
            "budget_remaining": self.budget_remaining,
            "action_prices": ACTION_PRICES,
            "configs": tuple(self.episode.correlation_matrix),
        }

    def read_bundle(self, index: int) -> dict[str, Any]:
        bundle = self._bundle_at(index)
        self._charge("read_bundle")
        return self._public_bundle(bundle)

    def run_tests(self, index: int, suite: str) -> tuple[dict[str, Any], ...]:
        bundle = self._bundle_at(index)
        if suite != "visible":
            raise ValueError("suite must be `visible`")
        self._charge("run_tests")
        results = test_results(
            self.episode.task.source,
            bundle.patch,
            self.episode.visible_cases,
        )
        return tuple(self._public_result(result) for result in results)

    def write_test(self, code: str) -> dict[str, Any]:
        self._charge("write_test")
        test_id = len(self.authored_tests) + 1
        test = parse_authored_test(code, test_id)
        accepted = reference_accepts(self.episode, test)
        if accepted:
            self.authored_tests[test_id] = test
        return {"accepted": accepted, "test_id": test_id if accepted else None}

    def run_test_all(self, test_id: int) -> tuple[dict[str, Any], ...]:
        test = self.authored_tests[test_id]
        self._charge("run_test_all")
        expected = execute(self.episode.task.source, Case(test.args))
        return tuple(
            {
                "lane_id": bundle.lane_id,
                "passed": execute(bundle.patch, Case(test.args)) == expected,
            }
            for bundle in self.bundles
        )

    def fuzz(self, index: int, args: tuple[object, ...]) -> dict[str, Any]:
        bundle = self._bundle_at(index)
        self._charge("fuzz")
        case = Case(args)
        expected = execute(self.episode.task.source, case)
        actual = execute(bundle.patch, case)
        return {
            "args": args,
            "expected": asdict(expected),
            "actual": asdict(actual),
            "passed": actual == expected,
        }

    def divergence(self) -> dict[str, Any]:
        self._charge("divergence")
        events = [event for bundle in self.bundles for event in bundle.trace]
        overlay = build_divergence_overlay(events)
        return {
            "first_step": overlay.divergence_step,
            "agreement": overlay.agreement,
            "trajectories": overlay.trajectory_ids,
        }

    def recruit(self, config: str) -> dict[str, Any]:
        if config not in self.episode.correlation_matrix:
            raise ValueError(f"unknown config: {config}")
        self._charge("recruit")
        self._recruits += 1
        bundle = recruit_bundle(self.episode, config, self._recruits)
        self.bundles.append(bundle)
        return self._public_bundle(bundle)

    def decide(
        self,
        decision: str,
        probability: float,
        witnesses: float,
        report: dict[str, str],
    ) -> ScoreBreakdown:
        self._charge("decide")
        score = score_decision(
            self.episode,
            tuple(self.bundles),
            decision,
            probability,
            witnesses,
            report,
            self.spend,
        )
        self.terminated = True
        self.score = score
        return score

    def step(
        self,
        action: dict[str, Any],
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        self._ensure_active()
        tool = action["tool"]
        if tool == "read_bundle":
            result: Any = self.read_bundle(int(action["index"]))
        elif tool == "run_tests":
            result = self.run_tests(int(action["index"]), str(action["suite"]))
        elif tool == "write_test":
            result = self.write_test(str(action["code"]))
        elif tool == "run_test_all":
            result = self.run_test_all(int(action["test_id"]))
        elif tool == "fuzz":
            result = self.fuzz(int(action["index"]), tuple(action["args"]))
        elif tool == "divergence":
            result = self.divergence()
        elif tool == "recruit":
            result = self.recruit(str(action["config"]))
        elif tool == "decide":
            result = self.decide(
                str(action["decision"]),
                float(action["probability"]),
                float(action["witnesses"]),
                dict(action["report"]),
            )
        else:
            raise ValueError(f"unknown tool: {tool}")

        if tool == "decide":
            reward = result.total
            info_result = asdict(result)
        else:
            reward = 0.0
            info_result = result
        return (
            self.observation(),
            reward,
            self.terminated,
            False,
            {"result": info_result},
        )

    def _bundle_at(self, index: int) -> AttemptBundle:
        self._ensure_active()
        if not 1 <= index <= len(self.bundles):
            raise ValueError("bundle index is outside the available range")
        return self.bundles[index - 1]

    def _charge(self, action: str) -> None:
        self._ensure_active()
        price = ACTION_PRICES[action]
        if price > self.budget_remaining:
            raise RuntimeError(f"{action} costs {price}; {self.budget_remaining} remains")
        self.budget_remaining -= price
        self.actions.append(action)

    def _ensure_active(self) -> None:
        if self.terminated:
            raise RuntimeError("episode has terminated")

    @staticmethod
    def _public_bundle(bundle: AttemptBundle) -> dict[str, Any]:
        return {
            "lane_id": bundle.lane_id,
            "config": bundle.config,
            "surface_cue": bundle.surface_cue,
            "patch": bundle.patch,
            "test_transcript": bundle.test_transcript,
            "trace": tuple(
                {"seq": event.seq, "type": event.type.value, "payload": event.payload}
                for event in bundle.trace
            ),
        }

    @staticmethod
    def _public_result(result: TestResult) -> dict[str, Any]:
        return {
            "args": result.args,
            "expected": asdict(result.expected),
            "actual": asdict(result.actual),
            "passed": result.passed,
        }


def load_environment(config: dict[str, Any]) -> IndependentEvidenceEnv:
    return IndependentEvidenceEnv(seed=int(config["seed"]))
