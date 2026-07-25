# Real-model run - 2026-07-02 [real-model]

One real-model reliability run of the hard landing-site task
(`tasks/hard.yaml`, acceptance contract `hard_website_v1`), following
[the runbook](../RUNBOOK.md). This extends the 2026-07-01 sample with the
same task at `n = 20`.

- **Model**: `deepseek-v4-pro` (`reasoning_effort=high`, thinking enabled,
  `DEEPSEEK_MAX_TOKENS=8192`, escalation cap 16384)
- **Pre-registered task / N / k**: `hard.landing_site`, `n = 20`, summary
  horizon `k = 3`
- **Command**:
  `murmur agents run deepseek-website --n 20 --task hard --event-log docs/benchmarks/2026-07-02-deepseek-hard-n20/events.jsonl --html docs/benchmarks/2026-07-02-deepseek-hard-n20/fan.html`
- **Date**: 2026-07-02, 20:25:43-21:22:53 UTC (57.2 minutes wall time,
  attempts run sequentially)
- **Preflight**: `murmur doctor --ping` -> `API ok - model=deepseek-v4-pro`,
  15 input / 20 output tokens, cost about $0.0001

## Results (n = 20, k = 3)

All numbers below are computed from [`events.jsonl`](events.jsonl) by
[`scripts/summarize_real_run.py`](../../../scripts/summarize_real_run.py)
(output committed as [`summary.json`](summary.json)); the rendered report is
[`fan.html`](fan.html). Wall time is derived from the first and last event
timestamps in `events.jsonl`.

| Metric | Value |
| --- | --- |
| pass@1 | 0.60 (12/20 pass, Wilson 95% [0.39, 0.78]) |
| pass^3 empirical (unbiased) | 0.193 |
| pass^3 projected (i.i.d.) | 0.216 |
| Model calls / tokens | 72 calls, 373,600 in / 351,708 out |
| Cost (recorded tokens x DeepSeek list price $0.80/$3.20 per Mtok) | **$1.42** |
| Wall time | 57.2 minutes |
| Failures | 8 x `contract_violation` |

Failure details:

- 7 x `missing_metric_pass_hat_k`
- 1 x `missing_metric_pass_hat_k, missing_accent_red`

## Known data flaw

Model-call `latency_ms` was recorded as `0.0` for all 72 calls due to a bug
in the run path; the fix in `593c53f` covered only the n=10 path. The
`summary.json` latency block is therefore invalid. Timestamps, token counts,
outcomes, and wall time remain valid: the event log spans 2026-07-02
20:25:43-21:22:53 UTC, or 57.2 minutes.

Notes on provenance:

- The per-lane `$` amounts inside `fan.html` use the conductor's generic
  simulator price table, not DeepSeek billing; the honest cost number is the
  $1.42 above, recomputed from recorded token usage at DeepSeek list prices.
- Sample size is n = 20 on one task and one model. This is real-model evidence
  for the harness path, not a leaderboard claim.
