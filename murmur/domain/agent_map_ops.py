"""Operator scope rules for agent-map projection (fan-out lanes vs combine gates)."""

from __future__ import annotations

from murmur.domain.workflow import WorkflowNode

FANOUT_OPS = frozenset({"map", "generate"})

# One module receives outputs from every parallel lane.
COMBINE_OPS = frozenset({"tournament", "rank", "reduce", "report", "filter", "loop"})

# Runs once before any fan-out lanes exist.
SHARED_UPSTREAM_OPS = frozenset({"classify"})


def fan_count(node: WorkflowNode) -> int:
    if node.op not in FANOUT_OPS:
        return 0
    for key in ("n", "fan", "count"):
        if key in node.params:
            try:
                return max(1, int(node.params[key]))
            except (TypeError, ValueError):
                continue
    return 1


def downstream_scope(fan_parent: WorkflowNode, downstream: WorkflowNode) -> str:
    """Classify how a downstream operator relates to fan-out lanes.

    Returns one of: ``lane``, ``combine``, ``flow``.
    """
    if downstream.op in COMBINE_OPS:
        return "combine"
    if downstream.op == "exec":
        # Per-lane verification command, then aggregate at the shared exec hub.
        return "lane"
    if downstream.op == "verify" and fan_parent.op in FANOUT_OPS:
        return "combine"
    return "flow"
