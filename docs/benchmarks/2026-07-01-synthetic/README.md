# Synthetic suite artifacts — 2026-07-01 [synthetic/deterministic]

Every file in this folder was produced on 2026-07-01 by the commands below,
running on Windows with **no `.env` file and no API keys present** (the file was
renamed away for the session to verify the offline claim). All numbers come
from the deterministic seeded scaffold — no model was called. They demonstrate
the harness machinery, not any model's coding ability.

| Artifact | Producing command |
| --- | --- |
| `fan.html` | `murmur run --n 30 --success-rate 0.7 --error-rate 0.1 --seed 7` |
| `trace.html` | `murmur trace --n 30 --seed 7 --replay` (replay verified 30/30) |
| `gate-1-baseline.md` | `murmur gate --suite synthetic --n 30 --k 5 --seed 7 --branch main` (exit 0) |
| `gate-2-inconclusive.md` | same command re-run with `--seed 8` (exit 0, does not block) |
| `gate-3-regressed.md` | same command with `--scaffold worse --success-delta -0.12` (exit 1, blocks) |

`docs/images/fan-report.png` and `docs/images/trace-viewer.png` are headless-
browser screenshots (Edge `--headless=new --screenshot`) of `fan.html` and
`trace.html` from this folder. `docs/images/workbench-operator-map.png` is the
same kind of screenshot of `murmur agent-map-preview` output (offline preview
mode).

The gate sequence used a fresh baseline directory (`--baseline-dir`), so the
three verdicts show the full lifecycle: first run records a baseline; a
same-scaffold re-run under a different seed is statistically inconclusive and
does **not** block; a deliberately degraded scaffold (−0.12 success delta on
every task) is a statistically real regression and **does** block (exit 1).
