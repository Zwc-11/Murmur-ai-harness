"""Project workflow plans and run events into an agent-map graph."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from chorus.domain.agent_map_ops import (
    COMBINE_OPS,
    FANOUT_OPS,
    downstream_scope,
    fan_count,
)
from chorus.domain.workflow import SUPPORTED_OPS, WorkflowNode, WorkflowPlan

MAX_VISIBLE_AGENTS = 16

OPERATOR_COL_W = 280
LANE_COL_W = 220
COL_GAP = 48
AGENT_ROW_H = 96
OPERATOR_ROW_H = 108

OP_HUES: dict[str, int] = {
    "classify": 250,
    "map": 185,
    "generate": 155,
    "exec": 130,
    "loop": 90,
    "filter": 60,
    "rank": 45,
    "tournament": 25,
    "verify": 340,
    "reduce": 290,
    "report": 270,
    "agent": 210,
}


def project_agent_map(
    workflow: WorkflowPlan,
    *,
    events_path: Path | None = None,
    proof_path: Path | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Build nodes/edges JSON for the agent-map visualization."""

    events = _load_events(events_path) if events_path and events_path.is_file() else []
    node_status = _status_from_events(events)
    node_results = _node_results_from_proof(proof_path, run_dir)

    graph = _build_graph(workflow, node_status=node_status, node_results=node_results)
    playback = _playback_steps(events)
    if not playback:
        playback = _gate_playback_steps(workflow, graph)

    return {
        "workflow": workflow.to_dict(),
        "workflow_name": workflow.name,
        "workflow_description": workflow.description,
        "graph": graph,
        "events": events,
        "playback": playback,
        "operators": sorted(SUPPORTED_OPS),
        "op_hues": OP_HUES,
    }


def _build_graph(
    workflow: WorkflowPlan,
    *,
    node_status: dict[str, str],
    node_results: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    lane_hubs: dict[str, list[str]] = defaultdict(list)

    layers = _topological_layers(workflow)
    positions = _compute_layout(workflow, layers)

    for wf_node in workflow.nodes:
        base_id = wf_node.id
        pos = positions.get(base_id, {"x": 40, "y": 40})
        status = node_status.get(base_id, _status_from_result(node_results.get(base_id)))
        metrics = _metrics_for_node(base_id, node_status, node_results.get(base_id))
        scope = _operator_scope(wf_node, workflow)

        nodes.append(
            _operator_node(
                wf_node,
                position=pos,
                status=status,
                metrics=metrics,
                scope=scope,
            )
        )
        node_ids.add(base_id)

        count = fan_count(wf_node)
        agents = _expand_agents(
            wf_node,
            fan_count=count,
            node_results=node_results,
            positions=positions,
        )
        for agent in agents:
            if agent["id"] not in node_ids:
                nodes.append(agent)
                node_ids.add(agent["id"])
            edges.append(_edge(base_id, agent["id"], kind="fanout", gate=base_id))

        downstream = _downstream_targets(workflow, wf_node)
        if wf_node.op in FANOUT_OPS and agents:
            for downstream_id in downstream:
                downstream_node = _node_by_id(workflow, downstream_id)
                if downstream_node is None:
                    continue
                scope_kind = downstream_scope(wf_node, downstream_node)
                if scope_kind == "lane":
                    for agent in agents:
                        lane_op_id = f"{downstream_id}::agent_{agent['lane_index']}"
                        if lane_op_id not in node_ids:
                            nodes.append(
                                _lane_operator_node(
                                    downstream_node,
                                    lane_id=lane_op_id,
                                    lane_index=agent["lane_index"],
                                    parent_agent_id=agent["id"],
                                    position=positions.get(
                                        lane_op_id,
                                        {
                                            "x": agent["position"]["x"] + LANE_COL_W + COL_GAP,
                                            "y": agent["position"]["y"],
                                        },
                                    ),
                                    status=node_status.get(lane_op_id, "idle"),
                                )
                            )
                            node_ids.add(lane_op_id)
                        edges.append(_edge(agent["id"], lane_op_id, kind="lane", gate=lane_op_id))
                        lane_hubs[downstream_id].append(lane_op_id)
                elif scope_kind == "combine":
                    for agent in agents:
                        edges.append(
                            _edge(agent["id"], downstream_id, kind="combine_in", gate=downstream_id)
                        )
                else:
                    for agent in agents:
                        edges.append(
                            _edge(
                                agent["id"],
                                downstream_id,
                                kind="flow",
                                gate=downstream_id,
                            )
                        )
        else:
            for target_id in downstream:
                edges.append(_edge(base_id, target_id, kind="flow", gate=target_id))

    for hub_id, lane_ops in lane_hubs.items():
        hub = _node_by_id(workflow, hub_id)
        if hub is None:
            continue
        for lane_op_id in lane_ops:
            edges.append(_edge(lane_op_id, hub_id, kind="combine_in", gate=hub_id))

    return {"nodes": nodes, "edges": edges}


def _operator_scope(node: WorkflowNode, workflow: WorkflowPlan) -> str:
    if node.op in COMBINE_OPS:
        return "combine"
    if fan_count(node) > 1:
        return "fanout"
    if not node.dependencies:
        return "shared"
    for dep in node.dependencies:
        parent = _node_by_id(workflow, dep)
        if parent and fan_count(parent) > 1:
            return "combine"
    return "shared"


def _operator_node(
    wf_node: WorkflowNode,
    *,
    position: dict[str, float],
    status: str,
    metrics: dict[str, Any],
    scope: str,
) -> dict[str, Any]:
    thinking, activity = _node_activity(wf_node, scope=scope)
    return {
        "id": wf_node.id,
        "kind": "operator",
        "op": wf_node.op,
        "label": wf_node.id,
        "role": wf_node.role,
        "model": wf_node.model,
        "status": status,
        "quarantined": wf_node.quarantined,
        "metrics": metrics,
        "position": position,
        "hue": OP_HUES.get(wf_node.op, 230),
        "thinking": thinking,
        "activity": activity,
        "scope": scope,
    }


def _lane_operator_node(
    wf_node: WorkflowNode,
    *,
    lane_id: str,
    lane_index: int,
    parent_agent_id: str,
    position: dict[str, float],
    status: str,
) -> dict[str, Any]:
    thinking = f"Lane {lane_index}: running {wf_node.id}."
    command = str(wf_node.params.get("command", "")).strip()
    activity = (
        f"Per-lane gate for agent {lane_index}.\n"
        f"Runs {wf_node.op} on this lane's artifact only."
    )
    if command:
        activity += f"\nCommand: {command[:160]}"
    return {
        "id": lane_id,
        "kind": "operator",
        "op": wf_node.op,
        "label": f"{wf_node.id} - lane {lane_index}",
        "role": wf_node.role,
        "model": wf_node.model,
        "status": status,
        "metrics": {"latency_ms": 0.0},
        "position": position,
        "hue": OP_HUES.get(wf_node.op, 130),
        "thinking": thinking,
        "activity": activity,
        "scope": "lane",
        "lane_index": lane_index,
        "parent_agent": parent_agent_id,
    }


def _expand_agents(
    wf_node: WorkflowNode,
    *,
    fan_count: int,
    node_results: dict[str, dict[str, Any]],
    positions: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    if wf_node.op not in FANOUT_OPS or fan_count <= 1:
        return []

    result = node_results.get(wf_node.id, {})
    items = result.get("result", {}).get("items")
    if not isinstance(items, list):
        items = []

    agents: list[dict[str, Any]] = []
    count = min(fan_count, MAX_VISIBLE_AGENTS)
    for index in range(count):
        agent_id = f"{wf_node.id}::agent_{index + 1}"
        item_text = str(items[index]) if index < len(items) else ""
        passed = bool(result.get("passed", True)) if result else False
        quarantined = bool(result.get("quarantined", False))
        status = "pass" if passed and not quarantined else ("fail" if result else "idle")
        thinking, activity = _agent_lane_activity(wf_node, index + 1, count, item_text)
        agents.append(
            {
                "id": agent_id,
                "kind": "agent",
                "op": "agent",
                "label": f"agent {index + 1}",
                "lane_index": index + 1,
                "role": wf_node.role or f"lane {index + 1}",
                "model": wf_node.model,
                "status": status,
                "quarantined": quarantined,
                "metrics": {
                    "latency_ms": float(result.get("latency_ms", 0)) / max(count, 1),
                    "preview": item_text[:240] if item_text else thinking[:120],
                },
                "position": positions.get(agent_id, {"x": 0, "y": 40 + index * AGENT_ROW_H}),
                "hue": OP_HUES["agent"],
                "parent_op": wf_node.id,
                "thinking": thinking,
                "activity": activity,
                "scope": "lane",
            }
        )
    return agents


def _edge(source: str, target: str, *, kind: str, gate: str) -> dict[str, Any]:
    return {
        "id": f"{source}->{target}",
        "source": source,
        "target": target,
        "kind": kind,
        "gate": gate,
        "active": False,
        "callsPerSecond": 0.0,
    }


def _node_by_id(workflow: WorkflowPlan, node_id: str) -> WorkflowNode | None:
    for node in workflow.nodes:
        if node.id == node_id:
            return node
    return None


def _downstream_targets(workflow: WorkflowPlan, node: WorkflowNode) -> list[str]:
    targets: list[str] = []
    for other in workflow.nodes:
        if node.id in other.dependencies:
            targets.append(other.id)
    return targets


def _topological_layers(workflow: WorkflowPlan) -> list[list[WorkflowNode]]:
    by_id = {node.id: node for node in workflow.nodes}
    indegree: dict[str, int] = {node.id: 0 for node in workflow.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for node in workflow.nodes:
        for dep in node.dependencies:
            if dep in by_id:
                indegree[node.id] += 1
                outgoing[dep].append(node.id)

    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    layers: list[list[WorkflowNode]] = []
    while ready:
        layer = [by_id[node_id] for node_id in sorted(ready)]
        layers.append(layer)
        next_ready: list[str] = []
        for node_id in ready:
            for target in outgoing[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    next_ready.append(target)
        ready = next_ready
    return layers


def _stack_y(count: int, row_h: float, *, start_y: float = 40.0) -> list[float]:
    if count <= 0:
        return []
    return [start_y + index * row_h for index in range(count)]


def _layout_metrics(layers: list[list[WorkflowNode]]) -> tuple[float, float, float]:
    depth = max(1, len(layers))
    has_fan = any(fan_count(node) > 1 for layer in layers for node in layer)
    has_lane_exec = any(
        node.op == "exec" for layer in layers for node in layer if node.op == "exec"
    )
    extra = (2 if has_fan else 0) + (1 if has_lane_exec and has_fan else 0)
    operator_w = max(160, min(OPERATOR_COL_W, int(2000 / (depth + extra))))
    lane_w = max(140, min(LANE_COL_W, operator_w))
    col_gap = max(24, COL_GAP - depth)
    return operator_w, lane_w, col_gap


def _compute_layout(
    workflow: WorkflowPlan,
    layers: list[list[WorkflowNode]],
) -> dict[str, dict[str, float]]:
    positions: dict[str, dict[str, float]] = {}
    x = 40.0
    operator_w, lane_w, col_gap = _layout_metrics(layers)

    for layer in layers:
        fan_nodes = [node for node in layer if fan_count(node) > 1]
        max_visible_fan = 0
        if fan_nodes:
            max_visible_fan = min(max(fan_count(node) for node in fan_nodes), MAX_VISIBLE_AGENTS)

        if max_visible_fan > 1:
            lane_ys = _stack_y(max_visible_fan, AGENT_ROW_H)
            stack_center = (lane_ys[0] + lane_ys[-1]) / 2
            for row_index, wf_node in enumerate(layer):
                positions[wf_node.id] = {
                    "x": x,
                    "y": stack_center - 28 if len(layer) == 1 else 40 + row_index * OPERATOR_ROW_H,
                }
                fan = fan_count(wf_node)
                if fan > 1:
                    count = min(fan, MAX_VISIBLE_AGENTS)
                    agent_x = x + operator_w + col_gap
                    lane_ys = _stack_y(count, AGENT_ROW_H)
                    for index in range(count):
                        agent_id = f"{wf_node.id}::agent_{index + 1}"
                        positions[agent_id] = {"x": agent_x, "y": lane_ys[index]}
                        for other in workflow.nodes:
                            if wf_node.id not in other.dependencies:
                                continue
                            if downstream_scope(wf_node, other) == "lane":
                                lane_op_id = f"{other.id}::agent_{index + 1}"
                                positions[lane_op_id] = {
                                    "x": agent_x + lane_w + col_gap,
                                    "y": lane_ys[index],
                                }
            x += operator_w + col_gap + lane_w + col_gap
            if any(
                downstream_scope(fan_nodes[0], n) == "lane"
                for n in workflow.nodes
                if fan_nodes[0].id in n.dependencies
            ):
                x += lane_w + col_gap
        else:
            for row_index, wf_node in enumerate(layer):
                positions[wf_node.id] = {"x": x, "y": 40 + row_index * OPERATOR_ROW_H}
            x += operator_w + col_gap

    return positions


def _node_activity(wf_node: WorkflowNode, *, scope: str = "shared") -> tuple[str, str]:
    prompt = str(wf_node.params.get("prompt", "") or wf_node.params.get("task", "")).strip()
    command = str(wf_node.params.get("command", "")).strip()
    if scope == "combine":
        thinking = f"Combine gate: merge all lane outputs for {wf_node.id}."
        activity = (
            f"Waits until every upstream lane completes, then aggregates results.\n"
            f"Operator: {wf_node.op}"
        )
    elif scope == "fanout":
        thinking = f"Fan-out gate: spawn {fan_count(wf_node)} isolated lanes."
        activity = _OP_ACTIVITY.get(wf_node.op, ("", ""))[1]
    else:
        thinking = wf_node.role.strip() if wf_node.role else f"Run {wf_node.id}."
        activity = _OP_ACTIVITY.get(wf_node.op, (thinking, thinking))[1]
    if prompt:
        activity += f"\nGoal: {prompt[:220]}"
    if command:
        activity += f"\nCommand: {command[:160]}"
    return thinking, activity


_OP_ACTIVITY: dict[str, tuple[str, str]] = {
    "classify": ("Route the task.", "Estimate risk and pick a workflow template."),
    "map": ("Fan-out drafts.", "Each lane writes independently."),
    "generate": ("Fan-out repairs.", "Each lane patches in an isolated worktree."),
    "exec": ("Run objective command.", "Capture stdout/stderr and parse pass/fail."),
    "loop": ("Repair loop.", "Iterate until pass or budget exhausted."),
    "rank": ("Rank candidates.", "Score every lane and pick the best."),
    "tournament": ("Pairwise judge.", "Compare candidates and advance the winner."),
    "verify": ("Verify winner.", "Re-check the selected artifact."),
    "report": ("Publish proof.", "Package evidence for review."),
    "filter": ("Filter lanes.", "Drop unsafe or off-brief outputs."),
    "reduce": ("Reduce lanes.", "Collapse fan-in into one artifact."),
}


def _agent_lane_activity(
    wf_node: WorkflowNode,
    lane: int,
    lanes: int,
    item_text: str,
) -> tuple[str, str]:
    role = wf_node.role or f"Independent lane {lane} of {lanes}."
    if item_text:
        return f"Lane {lane}: produced output.", f"{role}\n\nOutput:\n{item_text[:500]}"
    if wf_node.op == "map":
        thinking = f"Lane {lane}: drafting."
        activity = f"{role}\n\nDraft angle {lane}/{lanes} without seeing other lanes."
    elif wf_node.op == "generate":
        thinking = f"Lane {lane}: repairing."
        activity = f"{role}\n\nPatch in worktree {lane}/{lanes} from failing test output."
    else:
        thinking = f"Lane {lane}: {wf_node.op}."
        activity = f"{role}\n\nLane {lane}/{lanes}."
    return thinking, activity


def _gate_playback_steps(
    workflow: WorkflowPlan,
    graph: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    """Sequential gate playback: one open gate at a time, lanes before combine hubs."""

    steps: list[dict[str, Any]] = []
    seq = 0
    gate_order = _gate_order(workflow, graph)

    for gate_id in gate_order:
        node = _find_graph_node(graph, gate_id)
        thinking = (node or {}).get("thinking", f"Running {gate_id}")
        seq += 1
        steps.append(
            {
                "seq": seq,
                "type": "gate_opened",
                "node_id": gate_id,
                "gate": gate_id,
                "message": thinking,
            }
        )
        seq += 1
        steps.append(
            {
                "seq": seq,
                "type": "workflow_node_started",
                "node_id": gate_id,
                "gate": gate_id,
                "message": thinking,
            }
        )
        if node and node.get("kind") == "agent":
            seq += 1
            steps.append(
                {
                    "seq": seq,
                    "type": "model_call_finished",
                    "node_id": gate_id,
                    "gate": gate_id,
                    "message": node.get("activity", thinking),
                }
            )
        seq += 1
        steps.append(
            {
                "seq": seq,
                "type": "workflow_node_finished",
                "node_id": gate_id,
                "gate": gate_id,
                "message": f"{gate_id} gate closed.",
            }
        )
        seq += 1
        steps.append(
            {
                "seq": seq,
                "type": "gate_closed",
                "node_id": gate_id,
                "gate": gate_id,
                "message": f"{gate_id} complete.",
            }
        )

    seq += 1
    steps.append(
        {
            "seq": seq,
            "type": "workflow_finished",
            "node_id": "",
            "gate": "",
            "message": "done",
        }
    )
    return steps


def _gate_order(_workflow: WorkflowPlan, graph: dict[str, list[Any]]) -> list[str]:
    """Topological gate order over the projected graph (lanes before combine hubs)."""

    ids = [node["id"] for node in graph["nodes"]]
    indegree = {node_id: 0 for node_id in ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["source"] not in indegree or edge["target"] not in indegree:
            continue
        indegree[edge["target"]] += 1
        outgoing[edge["source"]].append(edge["target"])

    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for target in outgoing.get(current, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return order if order else ids


def _find_graph_node(graph: dict[str, list[Any]], node_id: str) -> dict[str, Any] | None:
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node
    return None


def plan_agent_map_from_task(
    *,
    task: str,
    command: str = "",
    template: str = "auto",
    budget_usd: float = 0.50,
) -> dict[str, Any]:
    """Plan a workflow from natural language and project it for the agent map."""

    from chorus.application.workflow_planner import choose_workflow_size, plan_from_task

    size = choose_workflow_size(task=task, command=command, budget_usd=budget_usd)
    workflow = plan_from_task(
        task=task,
        template=template,
        command=command,
        attempts=size.attempts,
        max_repairs=size.max_repairs,
    )
    payload = project_agent_map(workflow)
    payload["embedded_task"] = task
    payload["workflow_size"] = {
        "attempts": size.attempts,
        "max_repairs": size.max_repairs,
        "reason": size.reason,
    }
    payload["preview_result"] = _build_preview_result(
        workflow,
        payload["graph"],
        task=task,
        playback=payload["playback"],
    )
    return payload


def _build_preview_result(
    workflow: WorkflowPlan,
    graph: dict[str, list[Any]],
    *,
    task: str,
    playback: list[dict[str, Any]],
) -> dict[str, Any]:
    """Synthetic run outcome for preview playback (not a live model execution)."""

    agents = sorted(
        [node for node in graph["nodes"] if node.get("kind") == "agent"],
        key=lambda node: str(node.get("id", "")),
    )
    winner = agents[min(1, len(agents) - 1)] if agents else None
    report_text = _preview_report_text(workflow.name, task, agents, winner)
    lane_previews = [
        {
            "id": agent["id"],
            "label": agent.get("label", agent["id"]),
            "selected": winner is not None and agent["id"] == winner["id"],
            "preview": str(agent.get("metrics", {}).get("preview", "")).strip()
            or f"Lane {index + 1} candidate (preview playback).",
        }
        for index, agent in enumerate(agents)
    ]
    gate_log = [
        {
            "gate": step.get("gate") or step.get("node_id") or "",
            "type": step.get("type", ""),
            "message": step.get("message", ""),
        }
        for step in playback
        if step.get("gate") or step.get("node_id")
    ]
    return {
        "mode": "preview",
        "status": "complete",
        "winner_id": winner["id"] if winner else "report",
        "winner_label": winner.get("label", "report") if winner else "report",
        "summary": report_text.split("\n", 1)[0][:240],
        "report": report_text,
        "lane_previews": lane_previews,
        "gate_log": gate_log,
        "note": (
            "Preview playback simulates gate order and a representative winner. "
            "Attach a run directory with events.jsonl and proof.json for live output."
        ),
    }


def _preview_report_text(
    workflow_name: str,
    task: str,
    agents: list[dict[str, Any]],
    winner: dict[str, Any] | None,
) -> str:
    winner_label = winner.get("label", "report") if winner else "report"
    header = f"Workflow: {workflow_name}\nWinner: {winner_label}\nCandidates: {len(agents) or 1}\n"
    lowered = task.lower()
    if "350 ml" in lowered and "500 ml" in lowered and "300 ml" in lowered:
        body = """\
Solution (preview exemplar):
1. Fill the 500 ml jar from the sink.
2. Pour from the jar into the 300 ml bowl until the bowl is full. The jar now holds 200 ml.
3. Empty the bowl back into the sink.
4. Pour the 200 ml from the jar into the bowl.
5. Fill the jar again from the sink (500 ml).
6. Pour from the jar into the bowl until the bowl is full.
   You poured 100 ml, so the jar holds 350 ml.

Final state: 350 ml in the 500 ml jar; 300 ml in the bowl."""
        return header + "\n" + body
    if workflow_name == "writing_tournament":
        body = (
            f"The judge selected {winner_label} after pairwise comparison.\n"
            "Preview text: independent draft that best matches the brief tone and constraints."
        )
        return header + "\n" + body
    if workflow_name == "coding_fix_test":
        body = (
            f"{winner_label} produced the patch that passed the objective test command.\n"
            "Preview: isolated worktree repair with passing pytest output."
        )
        return header + "\n" + body
    body = (
        f"{winner_label} ranked highest after classify -> fan-out -> rank.\n"
        "Preview: representative candidate output for the task goal."
    )
    return header + "\n" + body


def build_preview_demos() -> dict[str, dict[str, Any]]:
    from chorus.application.workflow_planner import (
        _coding_fix_test,
        _writing_tournament,
        choose_workflow_size,
    )

    demos: dict[str, dict[str, Any]] = {}
    writing_task = "Write a cover letter for a quant trading internship."
    writing_size = choose_workflow_size(task=writing_task, budget_usd=0.25)
    writing = _writing_tournament(writing_task, writing_size.attempts)
    demos["writing_tournament"] = project_agent_map(writing)

    fix_task = "Fix the failing checkout regression test."
    fix_cmd = "python -m pytest tests/test_checkout.py -q"
    fix_size = choose_workflow_size(task=fix_task, command=fix_cmd, budget_usd=0.50)
    fix_test = _coding_fix_test(fix_task, fix_cmd, fix_size.attempts, fix_size.max_repairs)
    demos["coding_fix_test"] = project_agent_map(fix_test)
    return demos


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _playback_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for event in events:
        event_type = event.get("type", "")
        if event_type.startswith("workflow_node_") or event_type in {
            "workflow_started",
            "workflow_finished",
            "model_call_finished",
            "gate_opened",
            "gate_closed",
        }:
            payload = event.get("payload", {})
            steps.append(
                {
                    "seq": event.get("seq", 0),
                    "type": event_type,
                    "node_id": payload.get("node_id", ""),
                    "gate": payload.get("gate", payload.get("node_id", "")),
                    "message": payload.get("message", ""),
                    "timestamp": event.get("timestamp", ""),
                }
            )
    return steps


def _status_from_events(events: list[dict[str, Any]]) -> dict[str, str]:
    status: dict[str, str] = {}
    for event in events:
        event_type = event.get("type", "")
        payload = event.get("payload", {})
        node_id = str(payload.get("node_id", ""))
        if not node_id:
            continue
        if event_type in {"workflow_node_started", "gate_opened"}:
            status[node_id] = "running"
        elif event_type in {"workflow_node_finished", "gate_closed"}:
            status[node_id] = "pass"
        elif event_type in {"workflow_node_failed", "workflow_node_quarantined"}:
            status[node_id] = "fail"
    return status


def _node_results_from_proof(
    proof_path: Path | None,
    run_dir: Path | None,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if proof_path and proof_path.is_file():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        for node in proof.get("nodes", ()):
            if isinstance(node, dict) and node.get("node_id"):
                results[str(node["node_id"])] = node
    if run_dir and run_dir.is_dir():
        nodes_dir = run_dir / "nodes"
        if nodes_dir.is_dir():
            for result_path in nodes_dir.glob("*/result.json"):
                data = json.loads(result_path.read_text(encoding="utf-8"))
                node_result = data.get("result", data)
                if isinstance(node_result, dict) and node_result.get("node_id"):
                    results[str(node_result["node_id"])] = node_result
    return results


def _status_from_result(result: dict[str, Any] | None) -> str:
    if not result:
        return "idle"
    if result.get("status") == "running":
        return "running"
    if result.get("passed"):
        return "pass"
    if result.get("quarantined") or result.get("status") == "failed":
        return "fail"
    return "idle"


def _metrics_for_node(
    node_id: str,
    node_status: dict[str, str],
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"latency_ms": 0.0, "throughput": 0.0, "error_rate": 0.0}
    if result:
        metrics["latency_ms"] = float(result.get("latency_ms", 0.0))
        metrics["throughput"] = 1.0 if result.get("passed") else 0.0
    elif node_status.get(node_id) == "running":
        metrics["throughput"] = 0.5
    return metrics
