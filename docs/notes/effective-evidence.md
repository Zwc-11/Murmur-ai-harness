# Five green runs, one witness

Projected `pass^k` treats repeated attempts as independent draws: an observed
single-run pass rate `p` becomes `p^k`. That is useful only when repeated runs
provide genuinely new evidence. Shared prompts, models, tools, and misconceptions
can instead produce correlated outcomes.

Murmur now reports two checks on that assumption. Failure concentration is the
Herfindahl index over failure class plus diagnostic IDs; 1.0 means every failure
belongs to one family. Effective failure families is the entropy-equivalent family
count. Effective witnesses counts distinct full action-signature sequences among
passing trajectories.

The committed DeepSeek runs show the concern directly. All 10 failures include
`missing_metric_pass_hat_k`. The n=10 run has one failure family. The n=20 run has
seven failures in that family and one with the same diagnostic plus
`missing_accent_red`, yielding concentration 0.781 and 1.46 effective families.
The passing traces are structurally distinct under exact action signatures: 8 of
8 and 12 of 12 effective witnesses. That pass-side count does not prove
independence; it says only that the recorded action paths are not exact copies.

Fresh output from:

```text
python scripts/effective_evidence.py docs/benchmarks/2026-07-01-deepseek/events.jsonl docs/benchmarks/2026-07-02-deepseek-hard-n20/events.jsonl
```

```text
| run | passes | failure concentration | effective failure families | effective witnesses | failure families |
| --- | ---: | ---: | ---: | ---: | --- |
| 2026-07-01-deepseek | 8 | 1.000 | 1.00 | 8 | contract_violation / missing_metric_pass_hat_k=2 |
| 2026-07-02-deepseek-hard-n20 | 12 | 0.781 | 1.46 | 12 | contract_violation / missing_metric_pass_hat_k=7; contract_violation / missing_accent_red, missing_metric_pass_hat_k=1 |
```

The conclusion is narrower than replacing `pass^k`: Murmur still reports the
standard estimators, but now flags concentrated failures and duplicate passing
paths beside them. Release decisions should treat those warnings as evidence that
the i.i.d. projection is optimistic.

Prior art: [τ-bench](https://arxiv.org/abs/2406.12045) introduced `pass^k` for
agent reliability; [Correlated Errors in Large Language
Models](https://arxiv.org/abs/2506.07962) measures shared model errors; and
[Failure Independence in LLM-Generated
Code](https://arxiv.org/abs/2607.02808) studies the same independence failure in
generated programs.
