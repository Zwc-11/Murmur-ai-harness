# Real-model benchmark runbook

How to produce a `[real-model]` reliability report for the hard landing-site
task (`tasks/hard.yaml`, acceptance contract `hard_website_v1`) with DeepSeek.
Everything below is also what produced the committed artifacts under
`docs/benchmarks/<date>-deepseek/` when a key was available.

## Prerequisites

- `DEEPSEEK_API_KEY` in `.env` (copy `.env.example`); the CLI loads it
  automatically. Anthropic works too (`MURMUR_MODEL_PROVIDER=anthropic`,
  `ANTHROPIC_API_KEY`) but the cost numbers below are DeepSeek numbers.
- Installed package: `python -m pip install -e ".[dev]"`.

## 1. Preflight — verify the key with one minimal completion

```bash
murmur doctor --ping
```

Expect `API ok — model=deepseek-v4-pro ...` for roughly $0.0002. If this
fails, stop; nothing else will work.

## 2. Smoke run — one attempt end to end

```bash
murmur agents run deepseek-website --n 1 --task hard \
  --event-log .murmur/deepseek-smoke.jsonl --html .murmur/deepseek-smoke.html
```

One trajectory: the agent plans, writes `index.html` + `styles.css`, submits,
and the `hard_website_v1` contract judges the artifact. Check the printed fan
line and cost before committing to the full run.

## 3. Full run — n = 10 attempts, report pass^k at k = 3

```bash
murmur agents run deepseek-website --n 10 --task hard \
  --event-log docs/benchmarks/<date>-deepseek/events.jsonl \
  --html docs/benchmarks/<date>-deepseek/fan.html
```

Recommendation: **n = 10, k = 3** on the hard task. n = 10 keeps cost and wall
time reasonable while making the empirical (unbiased) `pass^k` estimator
meaningful at k = 3 — "would three consecutive attempts all satisfy the
contract?" is the question a reviewer actually cares about. The fan report's
headline `pass^k` uses k = n; read k = 3 off the decay curve, or compute it
from the recorded outcomes (the unbiased estimator is
`C(passes, k) / C(n, k)`, `murmur/core/metrics.py:pass_hat_k_unbiased`).

## Cost and time expectations (estimates, not measurements)

Per attempt the agent makes up to 4 `deepseek-v4-pro` calls with
`reasoning_effort=high` and thinking enabled; hidden reasoning bills as output
tokens. At DeepSeek list prices ($0.80/M input, $3.20/M output — the table in
`murmur/benchmarks/swe/model.py`), an attempt typically lands in the
$0.05–$0.25 range, so **budget roughly $0.50–$2.50 for the full n = 10 run**,
and expect minutes-per-call latency: a full run can take one to a few hours
(calls run sequentially). The measured totals for a committed run live in that
run's `README.md` next to its artifacts.

## 4. Compute real cost/latency from the event log

The conductor's per-lane `cost_usd` uses a generic simulator price table, so
for a real run recompute cost from the recorded per-call token usage at
DeepSeek list prices:

```bash
python scripts/summarize_real_run.py docs/benchmarks/<date>-deepseek/events.jsonl \
  --k 3 --out docs/benchmarks/<date>-deepseek/summary.json
```

This writes pass@1, empirical/projected pass^k at the chosen k, per-attempt
outcomes, token totals, list-price cost, and latency percentiles — all derived
from `events.jsonl`, which stays committed next to it.

## 5. Commit the artifacts

Commit `events.jsonl`, `fan.html`, `summary.json`, and a short `README.md`
stating the exact commands, date, model, and measured totals. Label every
number `[real-model]`. If a number cannot be traced to one of these files, it
does not go in the README.

## What NOT to do

- Do not run the synthetic scaffold and present its numbers as a model result
  (`murmur gate` refuses to do this for real suites by design).
- Do not report the projected i.i.d. `pass^k` alone at large k; report the
  unbiased empirical estimator next to it (both are in the fan report).
- Do not drop failed/errored attempts from the log. The distribution is the
  result.
