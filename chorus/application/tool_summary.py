"""Summaries for policy-controlled tool calls."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunEvidenceIndex:
    rows: tuple[dict[str, Any], ...]

    @classmethod
    def from_paths(cls, paths: Iterable[Path]) -> RunEvidenceIndex:
        rows: list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file():
                continue
            attempt_id = _attempt_id(path)
            for row in _event_rows(path):
                payload = dict(row.get("payload", {}))
                metadata = dict(payload.get("metadata", {}))
                if attempt_id and "attempt_id" not in metadata:
                    metadata["attempt_id"] = attempt_id
                    payload["metadata"] = metadata
                    row = {**row, "payload": payload}
                rows.append(row)
        return cls(rows=tuple(rows))

    def tool_summary(self) -> dict[str, Any]:
        return summarize_tool_rows(self.rows)

    def count(self, event_type: str) -> int:
        return sum(1 for row in self.rows if row.get("type") == event_type)


def summarize_tool_events(paths: Iterable[Path]) -> dict[str, Any]:
    return RunEvidenceIndex.from_paths(paths).tool_summary()


def summarize_tool_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "requested": 0,
        "allowed": 0,
        "denied": 0,
        "succeeded": 0,
        "failed": 0,
        "latency_ms": 0.0,
        "by_tool": {},
        "by_node": {},
        "by_attempt": {},
    }
    for row in rows:
        payload = dict(row.get("payload", {}))
        tool = str(payload.get("tool", ""))
        if not tool:
            continue
        metadata = dict(payload.get("metadata", {}))
        node_id = str(metadata.get("node_id", ""))
        scoped_attempt = str(metadata.get("attempt_id", ""))
        event_type = str(row.get("type", ""))

        if event_type == "tool_call_requested":
            _increment(summary, "requested", tool, node_id, scoped_attempt)
            continue
        if event_type == "policy_decision":
            raw_decision = payload.get("decision", {})
            decision = (
                raw_decision.get("decision")
                if isinstance(raw_decision, dict)
                else str(raw_decision)
            )
            if decision == "allow":
                _increment(summary, "allowed", tool, node_id, scoped_attempt)
            elif decision == "deny":
                _increment(summary, "denied", tool, node_id, scoped_attempt)
            continue
        if event_type == "tool_result":
            raw_result = payload.get("result", {})
            result = raw_result if isinstance(raw_result, dict) else {}
            latency_ms = float(result.get("latency_ms", 0.0))
            summary["latency_ms"] = float(summary["latency_ms"]) + latency_ms
            key = "succeeded" if result.get("ok") else "failed"
            _increment(summary, key, tool, node_id, scoped_attempt, latency_ms=latency_ms)
    summary["total"] = int(summary["succeeded"]) + int(summary["failed"]) + int(summary["denied"])
    summary["latency_ms"] = round(float(summary["latency_ms"]), 3)
    return summary


def _event_rows(path: Path) -> list[dict[str, Any]]:
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


def _increment(
    summary: dict[str, Any],
    key: str,
    tool: str,
    node_id: str,
    attempt_id: str,
    *,
    latency_ms: float = 0.0,
) -> None:
    summary[key] = int(summary[key]) + 1
    _bucket(summary["by_tool"], tool, key, latency_ms=latency_ms)
    if node_id:
        _bucket(summary["by_node"], node_id, key, latency_ms=latency_ms)
    if attempt_id:
        _bucket(summary["by_attempt"], attempt_id, key, latency_ms=latency_ms)


def _bucket(
    buckets: dict[str, dict[str, Any]],
    name: str,
    key: str,
    *,
    latency_ms: float,
) -> None:
    bucket = buckets.setdefault(
        name,
        {
            "requested": 0,
            "allowed": 0,
            "denied": 0,
            "succeeded": 0,
            "failed": 0,
            "latency_ms": 0.0,
        },
    )
    bucket[key] = int(bucket[key]) + 1
    if latency_ms:
        bucket["latency_ms"] = round(float(bucket["latency_ms"]) + latency_ms, 3)


def _attempt_id(path: Path) -> str:
    for parent in path.parents:
        if parent.name.startswith("attempt_"):
            return parent.name
    return ""
