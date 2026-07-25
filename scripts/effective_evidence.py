"""Print effective-evidence metrics from recorded Murmur event logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from murmur.core.events import Event
from murmur.core.results import result_from_events


def load_events(path: Path) -> list[Event]:
    return [
        Event.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def evidence_row(path: Path) -> tuple[str, int, float, float, int, str]:
    result = result_from_events(load_events(path))
    passes = sum(trajectory.outcome == "pass" for trajectory in result.trajectories)
    families = "; ".join(
        f"{label}={count}"
        for label, count in sorted(
            result.metrics.failure_families.items(), key=lambda item: (-item[1], item[0])
        )
    )
    return (
        path.parent.name,
        passes,
        result.metrics.failure_concentration,
        result.metrics.effective_failure_families,
        result.metrics.effective_witnesses,
        families,
    )


def render_table(paths: list[Path]) -> str:
    lines = [
        "| run | passes | failure concentration | effective failure families | "
        "effective witnesses | failure families |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for path in paths:
        run, passes, concentration, families, witnesses, labels = evidence_row(path)
        lines.append(
            f"| {run} | {passes} | {concentration:.3f} | {families:.2f} | "
            f"{witnesses} | {labels} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", nargs="+", type=Path)
    args = parser.parse_args()
    print(render_table(args.events))


if __name__ == "__main__":
    main()
