"""Project workflow-run events into reliability and trace report inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from murmur.core.events import Event, EventType
from murmur.core.metrics import reliability_metrics
from murmur.core.types import RunResult, TrajectoryResult
from murmur.report.fan_html import write_fan_html
from murmur.report.trace_html import write_traces_html
from murmur.trace.spans import Span, Trace

NODE_TERMINAL_EVENTS = frozenset(
    {
        "workflow_node_finished",
        "workflow_node_failed",
        "workflow_node_quarantined",
        "workflow_node_skipped",
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowObservability:
    result: RunResult
    traces: list[Trace]
    overlay_events: list[Event]
    progress: dict[str, Any]


def write_workflow_observability_reports(
    run_dir: Path,
    *,
    mirror_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write per-run reliability and trace reports from a workflow event log."""

    observed = workflow_observability_from_run(run_dir)
    fan_path = write_fan_html(
        observed.result,
        run_dir / "fan.html",
        events=observed.overlay_events,
        trace_href="trace.html",
        workflow_progress=observed.progress,
    )
    trace_path = write_traces_html(
        observed.traces,
        run_dir / "trace.html",
        run_id=observed.result.run_id,
    )
    if mirror_dir is not None:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        write_fan_html(
            observed.result,
            mirror_dir / "fan.html",
            events=observed.overlay_events,
            trace_href="trace.html",
            workflow_progress=observed.progress,
        )
        write_traces_html(observed.traces, mirror_dir / "trace.html", run_id=observed.result.run_id)
    return fan_path, trace_path


def workflow_observability_from_run(run_dir: Path) -> WorkflowObservability:
    rows = _read_rows(run_dir / "events.jsonl")
    proof = _read_json(run_dir / "proof.json")
    lanes = _lanes(rows, proof)
    result = _run_result(rows, proof, lanes)
    overlay_events = _overlay_events(rows, proof, lanes, result)
    traces = _traces(rows, proof, lanes, result)
    progress = _progress_payload(rows, proof, lanes, result)
    return WorkflowObservability(
        result=result,
        traces=traces,
        overlay_events=overlay_events,
        progress=progress,
    )


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _lanes(rows: list[dict[str, Any]], proof: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = _proof_nodes(proof)
    map_nodes = [
        node
        for node in nodes
        if str(node.get("op", "")) == "map"
        and isinstance(dict(node.get("result", {})).get("items"), list)
    ]
    if map_nodes:
        node = map_nodes[0]
        items = list(dict(node.get("result", {})).get("items", []))
        return [
            _lane_from_item(str(node.get("node_id", "agent")), index, item)
            for index, item in enumerate(items, start=1)
        ]

    for node in _workflow_nodes(rows, proof):
        if str(node.get("op", "")) != "map":
            continue
        count = _as_int(dict(node.get("params", {})).get("n"), 1)
        return [
            {
                "id": f"{node.get('id', 'agent')}_{index}",
                "label": f"agent {index}",
                "index": index,
                "node_id": str(node.get("id", "agent")),
                "status": "ok",
                "preview": "",
                "text": "",
                "latency_ms": 0.0,
                "tokens": 0,
                "cost_usd": 0.0,
            }
            for index in range(1, max(1, count) + 1)
        ]

    return [
        {
            "id": "workflow_1",
            "label": "workflow",
            "index": 1,
            "node_id": "workflow",
            "status": "ok",
            "preview": "",
            "text": "",
            "latency_ms": _workflow_latency_ms(rows, proof),
            "tokens": 0,
            "cost_usd": float(dict(proof.get("budget", {})).get("cost_usd", 0.0)),
        }
    ]


def _lane_from_item(node_id: str, index: int, item: Any) -> dict[str, Any]:
    status = "ok"
    text = str(item)
    latency = 0.0
    tokens = 0
    cost = 0.0
    if isinstance(item, dict):
        status = str(item.get("status", "ok"))
        text = str(item.get("text", item.get("error", "")))
        latency = float(item.get("latency_ms", 0.0) or 0.0)
        tokens = int(item.get("input_tokens", 0) or 0) + int(item.get("output_tokens", 0) or 0)
        cost = float(item.get("cost_usd", 0.0) or 0.0)
    encoded = text.encode("utf-8", errors="replace")
    return {
        "id": f"{node_id}_{index}",
        "label": f"agent {index}",
        "index": index,
        "candidate_index": index - 1,
        "node_id": node_id,
        "status": status,
        "preview": _preview(text),
        "detail": _preview(text, limit=1200),
        "fingerprint": sha256(encoded).hexdigest()[:12],
        "bytes": len(encoded),
        "text": text,
        "latency_ms": latency,
        "tokens": tokens,
        "cost_usd": cost,
    }


def _run_result(
    rows: list[dict[str, Any]],
    proof: dict[str, Any],
    lanes: list[dict[str, Any]],
) -> RunResult:
    run_id = _run_id(rows, proof)
    task_id = _task_id(rows, proof)
    final_status = _final_status(proof)
    budget = dict(proof.get("budget", {}))
    per_lane_cost = _divide(float(budget.get("cost_usd", 0.0) or 0.0), len(lanes))
    total_latency = _workflow_latency_ms(rows, proof)
    failure = _failure_class(proof)
    failure_step = _failure_step(rows, proof)

    trajectories: list[TrajectoryResult] = []
    for lane in lanes:
        if lane["status"] == "error":
            outcome = "error"
            lane_failure = "agent_error"
        else:
            outcome = "pass" if final_status == "pass" else "fail"
            lane_failure = None if outcome == "pass" else failure
        trajectories.append(
            TrajectoryResult(
                trajectory_id=str(lane["id"]),
                outcome=outcome,  # type: ignore[arg-type]
                output=str(lane.get("preview", "")),
                failure_class=lane_failure,
                cost_usd=float(lane.get("cost_usd", 0.0) or per_lane_cost),
                latency_ms=float(lane.get("latency_ms", 0.0) or total_latency),
                failure_step=failure_step if lane_failure else None,
                failure_detail=_failure_detail(proof) if lane_failure else None,
                failure_confidence=1.0 if lane_failure else None,
            )
        )

    trajectory_tuple = tuple(trajectories)
    return RunResult(
        run_id=run_id,
        task_id=task_id,
        trajectories=trajectory_tuple,
        metrics=reliability_metrics(trajectory_tuple),
        escalations=int(proof.get("repair_count", 0) or 0),
        verdict="pass" if final_status == "pass" else "fail",
        judge_summary=_workflow_judge_summary(proof, lanes),
    )


def _overlay_events(
    rows: list[dict[str, Any]],
    proof: dict[str, Any],
    lanes: list[dict[str, Any]],
    result: RunResult,
) -> list[Event]:
    workflow_nodes = _workflow_nodes(rows, proof)
    failure_step = _failure_step(rows, proof)
    events: list[Event] = []
    seq = 0

    def add(trajectory_id: str, event_type: EventType, payload: dict[str, Any]) -> None:
        nonlocal seq
        seq += 1
        events.append(
            Event.create(
                run_id=result.run_id,
                trajectory_id=trajectory_id,
                seq=seq,
                event_type=event_type,
                payload=payload,
            )
        )

    by_lane = {trajectory.trajectory_id: trajectory for trajectory in result.trajectories}
    for lane in lanes:
        trajectory_id = str(lane["id"])
        trajectory = by_lane[trajectory_id]
        add(
            trajectory_id,
            EventType.TRAJECTORY_STARTED,
            {"index": int(lane.get("index", 1)) - 1, "task_id": result.task_id},
        )
        for index, node in enumerate(workflow_nodes):
            node_id = str(node.get("id", node.get("node_id", f"step_{index}")))
            op = str(node.get("op", "step"))
            add(
                trajectory_id,
                EventType.STEP_STARTED,
                {"index": index, "phase": op, "node_id": node_id},
            )
            if op in {"generate", "map"}:
                add(
                    trajectory_id,
                    EventType.MODEL_CALL,
                    {
                        "model": _node_model(node) or "workflow-agent",
                        "input_tokens": 0,
                        "output_tokens": int(lane.get("tokens", 0) or 0),
                        "latency_ms": _node_latency(rows, node_id),
                        "finish_reason": "stop" if lane.get("status") != "error" else "error",
                    },
                )
            elif op in {"verify", "exec"}:
                ok = trajectory.outcome == "pass" or (
                    failure_step is not None and index < failure_step
                )
                add(trajectory_id, EventType.TOOL_CALL, {"tool": node_id, "args": {}})
                payload: dict[str, Any] = {
                    "tool": node_id,
                    "latency_ms": _node_latency(rows, node_id),
                }
                if not ok:
                    payload["error"] = _failure_detail(proof) or "workflow contract failed"
                    payload["error_type"] = _failure_class(proof)
                add(trajectory_id, EventType.TOOL_RESULT, payload)
        accepted = trajectory.outcome == "pass"
        add(
            trajectory_id,
            EventType.CONTRACT_CHECK,
            {
                "accepted": accepted,
                "step": None if accepted else failure_step,
                "diagnostic_ids": list(proof.get("failed_requirements", ())),
            },
        )
        add(
            trajectory_id,
            EventType.VERDICT,
            {
                "outcome": trajectory.outcome,
                "failure_class": trajectory.failure_class,
                "failure_step": trajectory.failure_step,
                "failure_detail": trajectory.failure_detail,
                "failure_confidence": trajectory.failure_confidence,
            },
        )
        add(
            trajectory_id,
            EventType.TRAJECTORY_FINISHED,
            {
                "outcome": trajectory.outcome,
                "cost_usd": trajectory.cost_usd,
                "latency_ms": trajectory.latency_ms,
            },
        )
    return events


def _traces(
    rows: list[dict[str, Any]],
    proof: dict[str, Any],
    lanes: list[dict[str, Any]],
    result: RunResult,
) -> list[Trace]:
    workflow_nodes = _workflow_nodes(rows, proof)
    node_timings = _node_timings(rows)
    tool_rows = [row for row in rows if row.get("type") == "tool_result"]
    model_rows = [row for row in rows if row.get("type") == "model_call_finished"]
    by_lane = {trajectory.trajectory_id: trajectory for trajectory in result.trajectories}
    traces: list[Trace] = []

    for lane in lanes:
        trajectory_id = str(lane["id"])
        trajectory = by_lane[trajectory_id]
        spans: list[Span] = []
        root_id = _sid(trajectory_id, "root")
        root = Span(
            span_id=root_id,
            parent_id=None,
            name="workflow.run",
            kind="run",
            depth=0,
            start_ms=0.0,
            duration_ms=max(trajectory.latency_ms, 1.0),
            status="ok" if trajectory.outcome == "pass" else "error",
            attributes={
                "gen_ai.operation.name": "invoke_agent_workflow",
                "murmur.run.id": result.run_id,
                "murmur.trajectory.id": trajectory_id,
                "murmur.agent.label": str(lane.get("label", trajectory_id)),
                "murmur.workflow.status": result.verdict,
            },
        )
        if trajectory.failure_class:
            root.attributes["murmur.failure.class"] = trajectory.failure_class
            if trajectory.failure_detail:
                root.attributes["murmur.failure.detail"] = trajectory.failure_detail
        spans.append(root)

        planner = dict(proof.get("planner", {}))
        if planner:
            spans.append(
                Span(
                    span_id=_sid(trajectory_id, "planning"),
                    parent_id=root_id,
                    name=f"planning {planner.get('mode', 'workflow')}",
                    kind="step",
                    depth=1,
                    start_ms=0.0,
                    duration_ms=float(planner.get("duration_ms", 0.0) or 0.0),
                    status="ok",
                    attributes={
                        "murmur.planner.mode": str(planner.get("mode", "")),
                        "murmur.planner.reason": str(planner.get("reason", "")),
                        "murmur.thinking.summary": str(planner.get("reasoning", "")),
                    },
                )
            )

        for index, node in enumerate(workflow_nodes):
            node_id = str(node.get("id", node.get("node_id", f"step_{index}")))
            op = str(node.get("op", "step"))
            timing = node_timings.get(node_id, {})
            start_ms = float(timing.get("start_ms", index * 10.0))
            duration_ms = float(timing.get("duration_ms", _node_latency(rows, node_id)) or 1.0)
            node_status = _node_status(rows, node_id)
            step_id = _sid(trajectory_id, f"node:{node_id}")
            step_attrs: dict[str, Any] = {
                "murmur.workflow.node": node_id,
                "murmur.workflow.op": op,
                "murmur.workflow.role": str(node.get("role", "")),
            }
            detail = _node_detail(rows, node_id)
            if detail:
                step_attrs["murmur.output.preview"] = detail
            spans.append(
                Span(
                    span_id=step_id,
                    parent_id=root_id,
                    name=f"{node_id} - {op}",
                    kind="step",
                    depth=1,
                    start_ms=start_ms,
                    duration_ms=duration_ms,
                    status="error" if node_status in {"failed", "quarantined"} else "ok",
                    attributes=step_attrs,
                )
            )
            _append_model_spans(
                spans,
                trajectory_id=trajectory_id,
                parent_id=step_id,
                node_id=node_id,
                node=node,
                lane=lane,
                rows=model_rows,
                start_ms=start_ms,
                duration_ms=duration_ms,
            )

        lane_tool_rows = _tool_rows_for_lane(tool_rows, lane)
        if lane_tool_rows:
            artifact_step_id = _sid(trajectory_id, "node:site_artifact")
            artifact_start = max((span.end_ms for span in spans), default=0.0)
            spans.append(
                Span(
                    span_id=artifact_step_id,
                    parent_id=root_id,
                    name="site_artifact - verify",
                    kind="step",
                    depth=1,
                    start_ms=artifact_start,
                    duration_ms=sum(_tool_latency(row) for row in lane_tool_rows),
                    status="error" if result.verdict != "pass" else "ok",
                    attributes={
                        "murmur.workflow.node": "site_artifact",
                        "murmur.workflow.op": "verify",
                        "murmur.agent.id": trajectory_id,
                        "murmur.output.preview": _failure_detail(proof),
                    },
                )
            )
            cursor = artifact_start
            for offset, row in enumerate(lane_tool_rows):
                payload = dict(row.get("payload", {}))
                result_payload = dict(payload.get("result", {}))
                result_detail = dict(result_payload.get("result", {}))
                ok = bool(result_payload.get("ok", True))
                latency = _tool_latency(row)
                spans.append(
                    Span(
                        span_id=_sid(trajectory_id, f"tool:{offset}:{payload.get('tool', '')}"),
                        parent_id=artifact_step_id,
                        name=f"execute_tool {payload.get('tool', 'tool')}",
                        kind="tool",
                        depth=2,
                        start_ms=cursor,
                        duration_ms=latency,
                        status="ok" if ok else "error",
                        attributes={
                            "gen_ai.operation.name": "execute_tool",
                            "gen_ai.tool.name": str(payload.get("tool", "")),
                            "murmur.workflow.node": str(
                                dict(payload.get("metadata", {})).get("node_id", "")
                            ),
                            "murmur.agent.id": trajectory_id,
                            "murmur.candidate.index": result_detail.get("candidate_index", ""),
                            "murmur.tool.ok": ok,
                            "murmur.failure.detail": str(result_payload.get("error", "")),
                        },
                    )
                )
                cursor += latency

        contract_id = _sid(trajectory_id, "contract")
        spans.append(
            Span(
                span_id=contract_id,
                parent_id=root_id,
                name="contract.check",
                kind="contract",
                depth=1,
                start_ms=max((span.end_ms for span in spans), default=0.0),
                duration_ms=0.0,
                status="ok" if trajectory.outcome == "pass" else "error",
                attributes={
                    "murmur.contract.result": "pass" if trajectory.outcome == "pass" else "fail",
                    "murmur.contract.diagnostic_ids": list(proof.get("failed_requirements", ())),
                    "murmur.failure.class": trajectory.failure_class or "",
                    "murmur.failure.detail": trajectory.failure_detail or "",
                },
            )
        )

        root.duration_ms = max((span.end_ms for span in spans), default=root.duration_ms)
        budget_cost = float(dict(proof.get("budget", {})).get("cost_usd", 0.0) or 0.0)
        traces.append(
            Trace(
                trace_id=_tid(trajectory_id),
                run_id=result.run_id,
                trajectory_id=trajectory_id,
                outcome=trajectory.outcome,
                replay=False,
                spans=sorted(spans, key=lambda span: (span.start_ms, span.depth, span.name)),
                total_ms=root.duration_ms,
                total_tokens=int(lane.get("tokens", 0) or 0),
                total_cost_usd=float(
                    lane.get("cost_usd", 0.0) or _divide(budget_cost, len(lanes))
                ),
            )
        )
    return traces


def _append_model_spans(
    spans: list[Span],
    *,
    trajectory_id: str,
    parent_id: str,
    node_id: str,
    node: dict[str, Any],
    lane: dict[str, Any],
    rows: list[dict[str, Any]],
    start_ms: float,
    duration_ms: float,
) -> None:
    node_rows = [
        row
        for row in rows
        if str(dict(row.get("payload", {})).get("node_id", "")) == node_id
    ]
    lane_index = int(lane.get("index", 1)) - 1
    selected_rows = node_rows
    if str(node.get("op", "")) == "map" and len(node_rows) >= lane_index + 1:
        selected_rows = [node_rows[lane_index]]
    if selected_rows:
        for index, row in enumerate(selected_rows):
            payload = dict(row.get("payload", {}))
            spans.append(
                Span(
                    span_id=_sid(trajectory_id, f"model:{node_id}:{index}"),
                    parent_id=parent_id,
                    name=f"chat {payload.get('model', _node_model(node) or 'model')}",
                    kind="model",
                    depth=2,
                    start_ms=start_ms + min(duration_ms, index * 2.0),
                    duration_ms=float(payload.get("latency_ms", 0.0) or max(duration_ms, 1.0)),
                    status="ok",
                    attributes={
                        "gen_ai.operation.name": "chat",
                        "gen_ai.request.model": str(payload.get("model", _node_model(node) or "")),
                        "gen_ai.usage.input_tokens": int(payload.get("input_tokens", 0) or 0),
                        "gen_ai.usage.output_tokens": int(payload.get("output_tokens", 0) or 0),
                        "gen_ai.response.finish_reasons": ["stop"],
                        "murmur.workflow.node": node_id,
                        "murmur.agent.id": str(lane.get("id", "")),
                        "murmur.agent.index": int(lane.get("index", 0) or 0),
                        "murmur.candidate.index": int(lane.get("candidate_index", 0) or 0),
                        "murmur.output.fingerprint": str(lane.get("fingerprint", "")),
                        "murmur.output.bytes": int(lane.get("bytes", 0) or 0),
                        "murmur.thinking.summary": str(payload.get("thinking", "")),
                        "murmur.output.preview": str(payload.get("output_preview", "")),
                    },
                )
            )
        return

    if str(node.get("op", "")) not in {"generate", "map"}:
        return
    is_lane_node = str(lane.get("node_id", "")) == node_id
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.request.model": _node_model(node) or "deterministic-scaffold",
        "gen_ai.usage.input_tokens": 0,
        "gen_ai.usage.output_tokens": int(lane.get("tokens", 0) or 0) if is_lane_node else 0,
        "gen_ai.response.finish_reasons": ["stop" if lane.get("status") != "error" else "error"],
        "murmur.workflow.node": node_id,
    }
    if is_lane_node:
        attrs.update(
            {
                "murmur.agent.id": str(lane.get("id", "")),
                "murmur.agent.index": int(lane.get("index", 0) or 0),
                "murmur.candidate.index": int(lane.get("candidate_index", 0) or 0),
                "murmur.output.fingerprint": str(lane.get("fingerprint", "")),
                "murmur.output.bytes": int(lane.get("bytes", 0) or 0),
                "murmur.output.preview": str(lane.get("detail", "")),
            }
        )
    span_name = (
        f"{lane.get('label', 'agent')} - {node_id}"
        if is_lane_node
        else f"generate {node_id}"
    )
    spans.append(
        Span(
            span_id=_sid(trajectory_id, f"agent:{node_id}"),
            parent_id=parent_id,
            name=span_name,
            kind="model",
            depth=2,
            start_ms=start_ms,
            duration_ms=max(float(lane.get("latency_ms", 0.0) or duration_ms), 1.0),
            status="error" if lane.get("status") == "error" else "ok",
            attributes=attrs,
        )
    )


def _progress_payload(
    rows: list[dict[str, Any]],
    proof: dict[str, Any],
    lanes: list[dict[str, Any]],
    result: RunResult,
) -> dict[str, Any]:
    budget = dict(proof.get("budget", {}))
    workflow = _workflow(rows, proof)
    return {
        "summary": {
            "workflow": str(workflow.get("name", result.task_id)),
            "status": result.verdict,
            "agents": len(lanes),
            "nodes": len(_workflow_nodes(rows, proof)),
            "model_calls": int(budget.get("model_calls", 0) or 0),
            "tool_calls": int(budget.get("tool_calls", 0) or 0),
            "cost_usd": float(budget.get("cost_usd", 0.0) or 0.0),
            "run_id": result.run_id,
        },
        "lanes": [
            {
                "id": str(lane.get("id", "")),
                "label": str(lane.get("label", "")),
                "status": _lane_display_status(lane, result.verdict),
                "preview": str(lane.get("preview", "")),
            }
            for lane in lanes
        ],
        "events": [_progress_row(row) for row in rows if _is_progress_event(row)],
    }


def _tool_rows_for_lane(
    tool_rows: list[dict[str, Any]],
    lane: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep artifact tool evidence on the candidate lane it belongs to."""

    lane_candidate = _as_int(lane.get("candidate_index"), int(lane.get("index", 1)) - 1)
    current_candidate: int | None = None
    selected: list[dict[str, Any]] = []
    for row in tool_rows:
        candidate = _tool_candidate_index(row)
        if candidate is not None:
            current_candidate = candidate
        if candidate == lane_candidate or (
            candidate is None and current_candidate == lane_candidate
        ):
            selected.append(row)
    return selected


def _tool_candidate_index(row: dict[str, Any]) -> int | None:
    payload = dict(row.get("payload", {}))
    result_payload = dict(payload.get("result", {}))
    result_detail = dict(result_payload.get("result", {}))
    if "candidate_index" not in result_detail:
        return None
    return _as_int(result_detail.get("candidate_index"), -1)


def _lane_display_status(lane: dict[str, Any], verdict: str) -> str:
    if lane.get("status") == "error":
        return "error"
    return "pass" if verdict == "pass" else "fail"


def _progress_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row.get("payload", {}))
    event_type = str(row.get("type", ""))
    node_id = str(
        payload.get("node_id")
        or dict(payload.get("metadata", {})).get("node_id", "")
        or ",".join(str(item) for item in payload.get("nodes", ()))
    )
    detail = ""
    thinking = ""
    status = "running"
    if event_type == "workflow_planned":
        planner = dict(payload.get("planner", {}))
        node_id = "planner"
        status = "pass"
        detail = str(planner.get("reason", ""))
        thinking = str(planner.get("reasoning", ""))
    elif event_type == "workflow_node_started":
        detail = str(payload.get("op", ""))
    elif event_type in NODE_TERMINAL_EVENTS:
        status = "pass" if payload.get("passed") else "fail"
        detail = str(
            payload.get("output")
            or payload.get("error")
            or payload.get("skipped_reason")
            or payload.get("status", "")
        )
    elif event_type == "model_call_finished":
        status = "pass"
        detail = str(payload.get("output_preview") or payload.get("model", ""))
        thinking = str(payload.get("thinking", ""))
    elif event_type == "workflow_map_attempt":
        status = "pass" if payload.get("status") == "ok" else "fail"
        detail = str(payload.get("text") or payload.get("error", ""))
        node_id = f"{node_id}_{payload.get('attempt', '')}".rstrip("_")
    elif event_type == "tool_call_requested":
        detail = str(payload.get("tool", ""))
    elif event_type == "tool_result":
        result_payload = dict(payload.get("result", {}))
        status = "pass" if result_payload.get("ok", True) else "fail"
        detail = str(
            result_payload.get("error")
            or result_payload.get("tool")
            or payload.get("tool", "")
        )
    elif event_type == "workflow_finished":
        status = str(payload.get("status", ""))
        detail = "workflow runtime finished"
    return {
        "seq": int(row.get("seq", 0) or 0),
        "type": event_type,
        "node": node_id,
        "status": status,
        "detail": _preview(detail, limit=480),
        "thinking": _preview(thinking, limit=2000),
    }


def _is_progress_event(row: dict[str, Any]) -> bool:
    event_type = str(row.get("type", ""))
    return event_type.startswith("workflow_") or event_type in {
        "model_call_finished",
        "model_call_retry",
        "model_candidate_failed",
        "tool_call_requested",
        "tool_result",
    }


def _workflow_judge_summary(proof: dict[str, Any], lanes: list[dict[str, Any]]) -> dict[str, Any]:
    budget = dict(proof.get("budget", {}))
    return {
        "baseline_cost_usd": float(budget.get("cost_usd", 0.0) or 0.0),
        "cascade_cost_usd": float(budget.get("cost_usd", 0.0) or 0.0),
        "cost_ratio": 1.0 if float(budget.get("cost_usd", 0.0) or 0.0) else 0.0,
        "tier_hits": {"workflow_agents": len(lanes)},
    }


def _proof_nodes(proof: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = proof.get("nodes", ())
    if isinstance(nodes, list):
        return [dict(node) for node in nodes if isinstance(node, dict)]
    return []


def _workflow(rows: list[dict[str, Any]], proof: dict[str, Any]) -> dict[str, Any]:
    for row in rows:
        if row.get("type") == "workflow_started":
            workflow = dict(row.get("payload", {})).get("workflow", {})
            if isinstance(workflow, dict):
                return dict(workflow)
    workflow = proof.get("workflow", {})
    return dict(workflow) if isinstance(workflow, dict) else {}


def _workflow_nodes(rows: list[dict[str, Any]], proof: dict[str, Any]) -> list[dict[str, Any]]:
    workflow_nodes = _workflow(rows, proof).get("nodes", ())
    if isinstance(workflow_nodes, list) and workflow_nodes:
        return [dict(node) for node in workflow_nodes if isinstance(node, dict)]
    return [
        {
            "id": str(node.get("node_id", "")),
            "op": str(node.get("op", "")),
            "role": "",
            "params": {},
        }
        for node in _proof_nodes(proof)
    ]


def _run_id(rows: list[dict[str, Any]], proof: dict[str, Any]) -> str:
    if proof.get("run_id"):
        return str(proof["run_id"])
    for row in rows:
        if row.get("run_id"):
            return str(row["run_id"])
    return "workflow_run"


def _task_id(rows: list[dict[str, Any]], proof: dict[str, Any]) -> str:
    workflow = _workflow(rows, proof)
    return str(workflow.get("name") or workflow.get("goal") or "workflow")


def _final_status(proof: dict[str, Any]) -> str:
    return "pass" if str(proof.get("status", "")).lower() == "pass" else "fail"


def _failure_class(proof: dict[str, Any]) -> str:
    for flag in proof.get("risk_flags", ()):
        label = str(flag)
        if label and label != "playwright_unavailable":
            return label
    if proof.get("failed_requirements"):
        return "contract_violation"
    return "workflow_failed"


def _failure_detail(proof: dict[str, Any]) -> str:
    if proof.get("artifact_generation_error"):
        return str(proof["artifact_generation_error"])
    failed = [str(item) for item in proof.get("failed_requirements", ())]
    if failed:
        return "failed requirements: " + ", ".join(failed)
    if proof.get("winner_reason"):
        return str(proof["winner_reason"])
    return ""


def _failure_step(rows: list[dict[str, Any]], proof: dict[str, Any]) -> int | None:
    if _final_status(proof) == "pass":
        return None
    failed_nodes = {
        str(dict(row.get("payload", {})).get("node_id", ""))
        for row in rows
        if row.get("type") in {"workflow_node_failed", "workflow_node_quarantined"}
    }
    nodes = _workflow_nodes(rows, proof)
    for index, node in enumerate(nodes):
        if str(node.get("id", node.get("node_id", ""))) in failed_nodes:
            return index
    return max(0, len(nodes) - 1) if nodes else 0


def _workflow_latency_ms(rows: list[dict[str, Any]], proof: dict[str, Any]) -> float:
    timed = [_timestamp_ms(row) for row in rows if _timestamp_ms(row) is not None]
    if len(timed) >= 2:
        return max(timed) - min(timed)
    return sum(float(node.get("latency_ms", 0.0) or 0.0) for node in _proof_nodes(proof))


def _node_timings(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    base = _base_time(rows)
    starts: dict[str, float] = {}
    timings: dict[str, dict[str, float]] = {}
    for row in rows:
        payload = dict(row.get("payload", {}))
        node_id = str(payload.get("node_id", ""))
        if not node_id:
            continue
        stamp = _row_offset(row, base)
        if row.get("type") == "workflow_node_started":
            starts[node_id] = stamp
        elif row.get("type") in NODE_TERMINAL_EVENTS:
            duration = float(payload.get("latency_ms", 0.0) or 0.0)
            start = starts.get(node_id, max(0.0, stamp - duration))
            timings[node_id] = {
                "start_ms": start,
                "duration_ms": duration or max(1.0, stamp - start),
            }
    return timings


def _node_latency(rows: list[dict[str, Any]], node_id: str) -> float:
    for row in rows:
        if row.get("type") not in NODE_TERMINAL_EVENTS:
            continue
        payload = dict(row.get("payload", {}))
        if str(payload.get("node_id", "")) == node_id:
            return float(payload.get("latency_ms", 0.0) or 0.0)
    return 0.0


def _node_status(rows: list[dict[str, Any]], node_id: str) -> str:
    status = "completed"
    for row in rows:
        payload = dict(row.get("payload", {}))
        if str(payload.get("node_id", "")) != node_id:
            continue
        event_type = str(row.get("type", ""))
        if event_type == "workflow_node_failed":
            return "failed"
        if event_type == "workflow_node_quarantined":
            return "quarantined"
        if event_type == "workflow_node_skipped":
            return "skipped"
        if event_type == "workflow_node_finished":
            status = "completed" if payload.get("passed", True) else "failed"
    return status


def _node_detail(rows: list[dict[str, Any]], node_id: str) -> str:
    detail = ""
    for row in rows:
        if row.get("type") not in NODE_TERMINAL_EVENTS:
            continue
        payload = dict(row.get("payload", {}))
        if str(payload.get("node_id", "")) != node_id:
            continue
        detail = str(
            payload.get("output")
            or payload.get("error")
            or payload.get("skipped_reason")
            or payload.get("status", "")
        )
    return _preview(detail, limit=600)


def _tool_latency(row: dict[str, Any]) -> float:
    result = dict(dict(row.get("payload", {})).get("result", {}))
    return max(float(result.get("latency_ms", 0.0) or 0.0), 1.0)


def _node_model(node: dict[str, Any]) -> str:
    return str(node.get("model") or dict(node.get("params", {})).get("model", ""))


def _base_time(rows: list[dict[str, Any]]) -> datetime | None:
    for row in rows:
        parsed = _parse_time(str(row.get("timestamp", "")))
        if parsed is not None:
            return parsed
    return None


def _row_offset(row: dict[str, Any], base: datetime | None) -> float:
    if base is None:
        return float(row.get("seq", 0) or 0)
    parsed = _parse_time(str(row.get("timestamp", "")))
    if parsed is None:
        return float(row.get("seq", 0) or 0)
    return max(0.0, (parsed - base).total_seconds() * 1000)


def _timestamp_ms(row: dict[str, Any]) -> float | None:
    parsed = _parse_time(str(row.get("timestamp", "")))
    if parsed is None:
        return None
    base = datetime.fromtimestamp(0, tz=parsed.tzinfo)
    return (parsed - base).total_seconds() * 1000


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _preview(text: str, *, limit: int = 220) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "..."


def _divide(value: float, denominator: int) -> float:
    return value / denominator if denominator else value


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sid(trajectory_id: str, name: str) -> str:
    return sha256(f"{trajectory_id}:{name}".encode()).hexdigest()[:16]


def _tid(trajectory_id: str) -> str:
    return sha256(trajectory_id.encode()).hexdigest()[:32]
