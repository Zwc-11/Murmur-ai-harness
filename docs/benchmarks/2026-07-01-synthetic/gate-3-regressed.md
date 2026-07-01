## Murmur reliability gate — REGRESSED ❌

This PR made reliability **reliably worse** than baseline (the delta CI is entirely below zero). Blocking.

```
pass^5: 0.20 -> 0.11   (Δ -0.09, 95% CI [-0.14, -0.05])   <- below 0
cost/run: $0.0556 -> $0.0556 (+0%)
```

New failures by class (candidate vs baseline):
  +32  contract_violation
  +1  nondeterministic_loop

Top regressed tasks: bench.format_table, bench.merge_configs, bench.paginate_api

Baseline: `main@4b9978f` · N=30 · seed-policy=per-lane · suite=synthetic-v1
