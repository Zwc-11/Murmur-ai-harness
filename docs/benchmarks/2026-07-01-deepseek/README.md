# Real-model run — 2026-07-01 [real-model]

One real-model reliability run of the hard landing-site task
(`tasks/hard.yaml`, acceptance contract `hard_website_v1`), following
[the runbook](../RUNBOOK.md).

- **Model**: `deepseek-v4-pro` (`reasoning_effort=high`, thinking enabled,
  `DEEPSEEK_MAX_TOKENS=8192`, escalation cap 16384)
- **Command**:
  `murmur agents run deepseek-website --n 10 --task hard --event-log docs/benchmarks/2026-07-01-deepseek/events.jsonl --html docs/benchmarks/2026-07-01-deepseek/fan.html`
- **Date**: 2026-07-01, 21:00–21:35 UTC (34.4 minutes wall time, attempts run
  sequentially)
- **Preflight**: `murmur doctor --ping` → `API ok — model=deepseek-v4-pro`
- **Smoke run**: one n=1 attempt beforehand (~$0.11, contract-rejected on
  `missing_metric_pass_hat_k`), not part of this dataset

## Results (n = 10, k = 3)

All numbers below are computed from [`events.jsonl`](events.jsonl) by
[`scripts/summarize_real_run.py`](../../../scripts/summarize_real_run.py)
(output committed as [`summary.json`](summary.json)); the rendered report is
[`fan.html`](fan.html).

| Metric | Value |
| --- | --- |
| pass@1 | 0.80 (8/10 pass, Wilson 95% [0.49, 0.94]) |
| pass^3 empirical (unbiased) | 0.467 |
| pass^3 projected (i.i.d.) | 0.512 |
| Model calls / tokens | 38 calls, 266,097 in / 206,891 out |
| Cost (recorded tokens × DeepSeek list price $0.80/$3.20 per Mtok) | **$0.87** |
| Latency per attempt | median 214 s, max 291 s |
| Failures | 2 × `contract_violation`, both `missing_metric_pass_hat_k` |

Both failed attempts produced full HTML/CSS artifacts but omitted the literal
`pass^k` notation the contract requires in the metrics strip — exactly the
kind of near-miss the contract check exists to catch.

Notes on provenance:

- The per-lane `$` amounts inside `fan.html` use the conductor's generic
  simulator price table, not DeepSeek prices; the honest cost number is the
  $0.87 above, recomputed from recorded token usage at DeepSeek list prices.
- Token counts come from the API's usage fields recorded per call in
  `events.jsonl`; DeepSeek bills hidden reasoning as output tokens, so they
  are included.
- Sample size is n = 10: the Wilson interval is wide. This is a single-day,
  single-task, single-model sample — a demonstration of the harness's
  real-model path, not a leaderboard claim.
