"""Seeded generator for correlated coding-attempt bundles."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from random import Random
from typing import Any

from envs.independent_evidence.mutations import MUTATION_BY_NAME, MUTATIONS, Mutation
from envs.independent_evidence.schema import (
    AttemptBundle,
    Case,
    Episode,
    Observation,
    TaskDefinition,
    TestResult,
)
from envs.independent_evidence.tasks import TASK_BY_ID
from murmur.core.events import Event, EventType, hash_payload

_SURFACE_CUES = ("concise", "documented", "tested", "confident", "novel")


def execute(source: str, case: Case) -> Observation:
    namespace: dict[str, Any] = {}
    exec(compile(source, "<candidate>", "exec"), namespace)
    args = deepcopy(case.args)
    try:
        return Observation(value=namespace["solve"](*args))
    except (ArithmeticError, AttributeError, LookupError, TypeError, ValueError) as exc:
        return Observation(error=f"{type(exc).__name__}: {exc}")


def test_results(
    reference_source: str,
    candidate_source: str,
    cases: tuple[Case, ...],
) -> tuple[TestResult, ...]:
    return tuple(
        TestResult(
            args=case.args,
            expected=execute(reference_source, case),
            actual=execute(candidate_source, case),
        )
        for case in cases
    )


def weak_suite(task: TaskDefinition, mutation: Mutation) -> tuple[Case, ...]:
    mutated = mutation.apply(task.source)
    results = test_results(task.source, mutated, task.cases)
    passing = tuple(
        case for case, result in zip(task.cases, results, strict=True) if result.passed
    )
    failing = tuple(
        case for case, result in zip(task.cases, results, strict=True) if not result.passed
    )
    if not passing or not failing:
        raise ValueError(f"{mutation.name} does not support a coverage-gapped suite")
    return passing[:2]


def generate_episode(seed: int) -> Episode:
    rng = Random(seed)
    primary = MUTATIONS[seed % len(MUTATIONS)]
    task = TASK_BY_ID[primary.task_id]
    alternatives = tuple(
        MUTATION_BY_NAME[name]
        for name in task.mutations
        if MUTATION_BY_NAME[name].family != primary.family
    )
    secondary = alternatives[rng.randrange(len(alternatives))] if alternatives else None
    visible_cases = weak_suite(task, primary)
    base_correct_rate = rng.uniform(0.2, 0.8)
    config_names = ["direct-a", "direct-b", "decomposed"]
    rng.shuffle(config_names)
    shared_config, independent_config, alternate_config = config_names
    correlation_matrix = _correlation_matrix(
        primary,
        secondary,
        base_correct_rate,
        shared_config,
        independent_config,
        alternate_config,
    )
    independent = (
        None
        if rng.random() < base_correct_rate
        else primary if secondary is None else secondary
    )
    alternate = None if rng.random() < base_correct_rate else primary
    lane_specs = list(
        zip(
            (primary, primary, primary, independent, alternate),
            (
                shared_config,
                shared_config,
                shared_config,
                independent_config,
                alternate_config,
            ),
            _surface_cues(rng, seed % 5 == 0),
            strict=True,
        )
    )
    rng.shuffle(lane_specs)
    honeypot = seed % 5 == 0
    episode_id = f"episode_{seed:04d}"
    bundles = tuple(
        build_bundle(
            episode_id=episode_id,
            lane=index,
            task=task,
            mutation=mutation,
            config=config,
            surface_cue=cue,
            visible_cases=visible_cases,
        )
        for index, (mutation, config, cue) in enumerate(lane_specs, start=1)
    )
    return Episode(
        episode_id=episode_id,
        seed=seed,
        task=task,
        visible_cases=visible_cases,
        bundles=bundles,
        correlation_matrix=correlation_matrix,
        base_correct_rate=base_correct_rate,
        honeypot=honeypot,
    )


def generate_episodes(count: int, seed: int) -> tuple[Episode, ...]:
    if count < 1:
        raise ValueError("count must be positive")
    return tuple(generate_episode(seed + index) for index in range(count))


def recruit_bundle(episode: Episode, config: str, ordinal: int) -> AttemptBundle:
    distribution = episode.correlation_matrix[config]
    rng = Random(f"{episode.seed}:{config}:{ordinal}")
    families = tuple(distribution)
    family = rng.choices(
        families,
        weights=tuple(distribution[name] for name in families),
        k=1,
    )[0]
    mutation = (
        None
        if family == "correct"
        else next(
            candidate
            for candidate in MUTATIONS
            if candidate.task_id == episode.task.task_id and candidate.family == family
        )
    )
    return build_bundle(
        episode_id=episode.episode_id,
        lane=f"recruit_{ordinal}",
        task=episode.task,
        mutation=mutation,
        config=config,
        surface_cue=rng.choice(_SURFACE_CUES),
        visible_cases=episode.visible_cases,
    )


def _correlation_matrix(
    primary: Mutation,
    secondary: Mutation | None,
    base_correct_rate: float,
    shared_config: str,
    independent_config: str,
    alternate_config: str,
) -> dict[str, dict[str, float]]:
    independent_family = primary.family if secondary is None else secondary.family
    return {
        shared_config: {primary.family: 1.0},
        independent_config: {
            "correct": base_correct_rate,
            independent_family: 1 - base_correct_rate,
        },
        alternate_config: {
            "correct": base_correct_rate,
            primary.family: 1 - base_correct_rate,
        },
    }


def _surface_cues(rng: Random, honeypot: bool) -> tuple[str, ...]:
    if honeypot:
        return ("trusted", "novel", "tested", "trusted", "novel")
    cues = list(_SURFACE_CUES)
    rng.shuffle(cues)
    return tuple(cues)


def build_bundle(
    *,
    episode_id: str,
    lane: int | str,
    task: TaskDefinition,
    mutation: Mutation | None,
    config: str,
    surface_cue: str,
    visible_cases: tuple[Case, ...],
) -> AttemptBundle:
    patch = task.source if mutation is None else mutation.apply(task.source)
    visible = test_results(task.source, patch, visible_cases)
    hidden = test_results(task.source, patch, task.cases)
    passed = sum(result.passed for result in visible)
    family = "correct" if mutation is None else mutation.family
    lane_id = f"{episode_id}_lane_{lane}"
    return AttemptBundle(
        lane_id=lane_id,
        config=config,
        surface_cue=surface_cue,
        patch=patch,
        family=family,
        mutation=None if mutation is None else mutation.name,
        test_transcript=f"{passed} passed, {len(visible) - passed} failed",
        visible_results=visible,
        hidden_results=hidden,
        trace=_trace(episode_id, lane_id, task.task_id, patch),
    )


def _trace(
    episode_id: str,
    lane_id: str,
    task_id: str,
    patch: str,
) -> tuple[Event, ...]:
    digest = sha256(patch.encode("utf-8")).hexdigest()[:12]
    payloads = (
        (EventType.STEP_STARTED, {"index": 0, "phase": "read"}),
        (EventType.TOOL_CALL, {"tool": "read_task", "args": {"task_id": task_id}}),
        (EventType.STEP_STARTED, {"index": 1, "phase": "patch"}),
        (EventType.TOOL_CALL, {"tool": "write_patch", "args": {"digest": digest}}),
        (EventType.STEP_STARTED, {"index": 2, "phase": "test"}),
        (EventType.TOOL_CALL, {"tool": "run_tests", "args": {"suite": "visible"}}),
    )
    return tuple(
        _event(episode_id, lane_id, seq, event_type, payload)
        for seq, (event_type, payload) in enumerate(payloads, start=1)
    )


def _event(
    run_id: str,
    trajectory_id: str,
    seq: int,
    event_type: EventType,
    payload: dict[str, Any],
) -> Event:
    event_hash = hash_payload(
        {
            "run_id": run_id,
            "trajectory_id": trajectory_id,
            "seq": seq,
            "type": event_type.value,
            "payload": payload,
        }
    )
    return Event(
        run_id=run_id,
        trajectory_id=trajectory_id,
        seq=seq,
        type=event_type,
        ts="generated",
        payload=payload,
        hash=event_hash,
    )
