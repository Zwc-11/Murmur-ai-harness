## Murmur reliability gate — INCONCLUSIVE ⚠️

The delta CI straddles zero -- run-to-run noise can't be told from a real change at this N. **Not blocking.** Widen N to tighten the interval.

```
pass^5: 0.20 -> 0.18   (Δ -0.01, 95% CI [-0.08, +0.05])   <- straddles 0
cost/run: $0.0556 -> $0.0559 (+1%)
```

New failures by class (candidate vs baseline):
  +6  contract_violation
  +3  nondeterministic_loop
  -6  tool_error

Top regressed tasks: bench.parse_args, bench.merge_configs, bench.async_cancel

Baseline: `main@4b9978f` · N=30 · seed-policy=per-lane · suite=synthetic-v1
