"""Summarize a recorded real-model run from its events.jsonl.

Derives pass@1 / pass^k, token totals, list-price cost, and latency from the
committed event log, so every number in a benchmark README traces to one file:

    python scripts/summarize_real_run.py docs/benchmarks/<date>-deepseek/events.jsonl \
        --k 3 --out docs/benchmarks/<date>-deepseek/summary.json

Cost uses per-Mtok list prices (default: deepseek-v4-pro at $0.80 in / $3.20
out, the table in murmur/benchmarks/swe/model.py). Reasoning tokens are billed
as output tokens by the API, so they are already inside the recorded usage.
"""

from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path
from statistics import median


def load_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def summarize(events: list[dict], *, k: int, price_in: float, price_out: float) -> dict:
    trajectories: dict[str, dict] = {}
    input_tokens = 0
    output_tokens = 0
    model_calls = 0
    models: set[str] = set()

    for event in events:
        trajectory_id = event.get("trajectory_id")
        payload = event.get("payload", {})
        if event["type"] == "model_call":
            model_calls += 1
            input_tokens += int(payload.get("input_tokens", 0))
            output_tokens += int(payload.get("output_tokens", 0))
            models.add(str(payload.get("model", "")))
        elif event["type"] == "trajectory_finished" and trajectory_id:
            trajectories[trajectory_id] = {
                "outcome": payload.get("outcome"),
                "latency_ms": float(payload.get("latency_ms", 0.0)),
            }
        elif event["type"] == "verdict" and trajectory_id:
            entry = trajectories.setdefault(trajectory_id, {})
            if payload.get("failure_class"):
                entry["failure_class"] = payload["failure_class"]

    n = len(trajectories)
    passes = sum(1 for t in trajectories.values() if t.get("outcome") == "pass")
    latencies = sorted(t.get("latency_ms", 0.0) for t in trajectories.values())
    cost_usd = (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    def empirical_pass_k(horizon: int) -> float:
        if horizon > passes or n == 0:
            return 0.0
        return comb(passes, horizon) / comb(n, horizon)

    return {
        "n": n,
        "passes": passes,
        "k": k,
        "models": sorted(models),
        "pass_at_1": passes / n if n else 0.0,
        "pass_hat_k_projected": (passes / n) ** k if n else 0.0,
        "pass_hat_k_empirical": empirical_pass_k(k),
        "model_calls": model_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "price_per_mtok": {"input": price_in, "output": price_out},
        "cost_usd_list_price": round(cost_usd, 4),
        "latency_ms": {
            "median": round(median(latencies), 1) if latencies else 0.0,
            "max": round(latencies[-1], 1) if latencies else 0.0,
        },
        "outcomes": {
            trajectory_id: trajectories[trajectory_id]
            for trajectory_id in sorted(trajectories)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path, help="events.jsonl from the run")
    parser.add_argument("--k", type=int, default=3, help="pass^k horizon (default 3)")
    parser.add_argument("--price-in", type=float, default=0.80, help="USD per Mtok input")
    parser.add_argument("--price-out", type=float, default=3.20, help="USD per Mtok output")
    parser.add_argument("--out", type=Path, default=None, help="write JSON here (else stdout)")
    args = parser.parse_args()

    summary = summarize(
        load_events(args.events), k=args.k, price_in=args.price_in, price_out=args.price_out
    )
    text = json.dumps(summary, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"summary written to {args.out}")
    print(text)


if __name__ == "__main__":
    main()
