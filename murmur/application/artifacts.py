"""Artifact index helpers for proof runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_artifact_index(run_dir: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    specs = (
        ("proof", "proof.json", "machine-readable proof"),
        ("proof_markdown", "proof.md", "human-readable proof"),
        ("report", "report.html", "HTML proof report"),
        ("reliability_report", "fan.html", "workflow reliability report"),
        ("trace_viewer", "trace.html", "workflow trace viewer"),
        ("workbench", "workbench.html", "static run workbench"),
        ("review_comment", "review_comment.md", "PR review comment"),
        ("workflow", "workflow.yaml", "workflow plan"),
        ("workflow_report", "workflow.html", "agent operator map"),
        ("acceptance_contract", "acceptance_contract.json", "artifact acceptance contract"),
        ("site_preview", "site/index.html", "generated website preview"),
        ("site_validation", "site_validation.json", "site artifact validation"),
        ("browser_checks", "browser_checks.json", "browser render checks"),
        ("interaction_checks", "interaction_checks.json", "browser interaction checks"),
        ("repair_iterations", "repair_iterations.json", "site repair iterations"),
        ("repair_prompt", "repair_prompt.md", "latest repair prompt"),
        ("document", "document.md", "generated document"),
        ("document_validation", "document_validation.json", "document artifact validation"),
        ("program_validation", "program_validation.json", "program artifact validation"),
        ("screenshot_desktop", "screenshots/desktop.png", "desktop browser screenshot"),
        ("screenshot_mobile", "screenshots/mobile.png", "mobile browser screenshot"),
        ("events", "events.jsonl", "run event log"),
        ("tool_summary", "tool_summary.json", "tool-call summary"),
        ("run_result", "run_result.json", "UI run result payload"),
        ("attempts", "attempts.json", "attempt summaries"),
        ("winner_diff", "winner/diff.patch", "winning patch"),
        ("diff", "diff.patch", "final diff"),
    )
    for kind, relative, description in specs:
        if (run_dir / relative).is_file():
            entries.append({"kind": kind, "path": relative, "description": description})
    for path in sorted((run_dir / "program").glob("main.*")):
        entries.append(
            {
                "kind": "program",
                "path": path.relative_to(run_dir).as_posix(),
                "description": "generated program",
            }
        )
    for path in sorted((run_dir / "attempts").glob("attempt_*/summary.json")):
        relative = path.relative_to(run_dir).as_posix()
        entries.append(
            {
                "kind": "attempt_summary",
                "path": relative,
                "description": f"{path.parent.name} summary",
            }
        )
    return entries


def write_artifact_index(run_dir: Path) -> list[dict[str, str]]:
    entries = build_artifact_index(run_dir)
    (run_dir / "artifact_index.json").write_text(
        json.dumps(entries, indent=2),
        encoding="utf-8",
    )
    return entries


def update_json_file(path: Path, updates: dict[str, Any]) -> None:
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
