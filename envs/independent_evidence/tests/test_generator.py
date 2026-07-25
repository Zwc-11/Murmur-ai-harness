"""Generator tests for the Independent Evidence Compiler stop gate."""

from __future__ import annotations

from collections import Counter

from envs.independent_evidence.audit_episodes import render_audit
from envs.independent_evidence.generator import generate_episode, generate_episodes, weak_suite
from envs.independent_evidence.mutations import MUTATIONS
from envs.independent_evidence.tasks import TASK_BY_ID


def test_mutation_library_has_auditable_behavior_gaps() -> None:
    assert len(MUTATIONS) >= 20
    for mutation in MUTATIONS:
        task = TASK_BY_ID[mutation.task_id]
        cases = weak_suite(task, mutation)
        assert cases


def test_episode_generation_is_seeded_and_correlated() -> None:
    episode = generate_episode(7)

    assert episode == generate_episode(7)
    assert len(episode.bundles) == 5
    lucky_passes = sum(
        bundle.visible_passed and not bundle.hidden_correct for bundle in episode.bundles
    )
    assert lucky_passes >= 3
    assert 0.2 <= episode.base_correct_rate <= 0.8
    config_counts = Counter(bundle.config for bundle in episode.bundles)
    shared_config = config_counts.most_common(1)[0][0]
    shared = [bundle for bundle in episode.bundles if bundle.config == shared_config]
    assert len(shared) == 3
    assert len({bundle.family for bundle in shared}) == 1
    assert all(not bundle.hidden_correct for bundle in shared)
    assert all(
        episode.correlation_matrix[bundle.config][bundle.family] > 0
        for bundle in episode.bundles
    )


def test_honeypot_surface_cues_do_not_encode_correctness() -> None:
    episode = generate_episode(10)
    by_cue: dict[str, set[str]] = {}
    for bundle in episode.bundles:
        by_cue.setdefault(bundle.surface_cue, set()).add(bundle.family)

    assert episode.honeypot
    assert any(len(families) > 1 for families in by_cue.values())


def test_audit_renders_every_label_against_hidden_behavior() -> None:
    episodes = generate_episodes(3, seed=7)
    report = render_audit(episodes)

    assert "Labels matching hidden behavior: 15/15." in report
    assert report.count("first behavior difference") == 3
    assert "INVALID" not in report


def test_stop_gate_covers_every_mutation_with_valid_labels() -> None:
    episodes = generate_episodes(200, seed=7)
    used = {
        bundle.mutation
        for episode in episodes
        for bundle in episode.bundles
        if bundle.mutation is not None
    }

    assert used == {mutation.name for mutation in MUTATIONS}
    assert all(
        (bundle.family == "correct") == bundle.hidden_correct
        for episode in episodes
        for bundle in episode.bundles
    )
