"""Run natural-language Murmur tasks for the agent-map workbench."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from murmur.application.artifact_contracts import (
    ArtifactBuildResult,
    append_run_event,
    artifact_trust_score,
    build_acceptance_contract,
    build_site_artifact,
    contract_for_kind,
    extract_index_html,
    looks_like_site_task,
    select_artifact_contract,
)
from murmur.application.artifacts import update_json_file, write_artifact_index
from murmur.application.fix_test import run_fix_test_workflow
from murmur.application.tool_summary import RunEvidenceIndex
from murmur.application.workflow_planner import choose_workflow_size, plan_task
from murmur.application.workflow_runtime import WorkflowRunResult, WorkflowRuntime
from murmur.domain.proof import ProofPackage
from murmur.domain.workflow import WorkflowPlan
from murmur.report.agent_map_projector import project_agent_map
from murmur.report.workflow_observability import write_workflow_observability_reports

SITE_MAX_PASSES = 4
SITE_GEN_MAX_TOKENS = 24000
_CONTINUE_SYSTEM = (
    "Continue an incomplete generated website artifact. Do not repeat the "
    "already-written content. Return only the missing suffix."
)
_ENRICH_SYSTEM = (
    "You are a world-class creative frontend engineer. Substantially expand a working "
    "single-file website into a richer, more immersive experience. Return ONLY one "
    "complete HTML document from <!doctype html> to </html> (one ```html fence is "
    "allowed; no other prose)."
)


@dataclass(frozen=True, slots=True)
class AgentMapRunOptions:
    task: str
    command: str = ""
    template: str = "auto"
    budget_usd: float = 0.50
    provider: str = ""
    model: str = ""
    use_model: bool = False
    agent: str = "scripted"
    concurrency: int = 1
    attempt_concurrency: int = 1
    run_id: str = ""


def run_agent_map_task(
    *,
    repo_root: Path,
    out_root: Path,
    options: AgentMapRunOptions,
    public_run_prefix: str = "runs",
) -> dict[str, Any]:
    """Run one UI-submitted task and return the projected map payload."""

    task = options.task.strip()
    if not task:
        raise RuntimeError("task is required")

    size = choose_workflow_size(
        task=task,
        command=options.command,
        budget_usd=options.budget_usd,
    )
    outcome = plan_task(
        task=task,
        model=_build_model(options),
        command=options.command,
        budget_usd=options.budget_usd,
        template=options.template or "auto",
        attempts=size.attempts,
        max_repairs=size.max_repairs,
    )
    workflow = outcome.workflow
    planner_meta = outcome.meta()
    run_id = _safe_run_id(options.run_id)
    if _is_coding_fix_test(workflow):
        payload = _run_fix_test_map(
            workflow=workflow,
            repo_root=repo_root,
            out_root=out_root,
            run_id=run_id,
            options=options,
            size_reason=size.reason,
            public_run_prefix=public_run_prefix,
            planner_meta=planner_meta,
        )
    else:
        payload = _run_generic_map(
            workflow=workflow,
            repo_root=repo_root,
            out_root=out_root,
            run_id=run_id,
            options=options,
            size_reason=size.reason,
            public_run_prefix=public_run_prefix,
            planner_meta=planner_meta,
        )
    payload["embedded_task"] = task
    payload["planner"] = planner_meta
    payload["workflow_size"] = _plan_size_summary(workflow, size.reason)
    _persist_planner_provenance(out_root / run_id, planner_meta, payload)
    return payload


def _run_generic_map(
    *,
    workflow: WorkflowPlan,
    repo_root: Path,
    out_root: Path,
    run_id: str,
    options: AgentMapRunOptions,
    size_reason: str,
    public_run_prefix: str,
    planner_meta: dict[str, Any],
) -> dict[str, Any]:
    runtime = WorkflowRuntime(
        repo_root=repo_root,
        out_root=out_root,
        model=_build_model(options),
        concurrency=options.concurrency,
    )
    result = runtime.run(workflow, run_id=run_id)
    artifact_build = _build_expected_artifacts(result, workflow, use_model=options.use_model)
    is_site = workflow.artifact_kind == "site" or looks_like_site_task(workflow.goal)
    if is_site and options.use_model:
        artifact_build = _improve_site_artifact(
            result=result,
            workflow=workflow,
            options=options,
            artifact_build=artifact_build,
        )
    result = _refresh_workflow_proof(result, artifact_build)
    _persist_planner_provenance(result.run_dir, planner_meta, {})
    _write_observability_reports(result.run_dir, out_root)
    artifact_index = write_artifact_index(result.run_dir)
    run_meta = _run_metadata(
        run_dir=result.run_dir,
        status=result.status,
        artifact_index=artifact_index,
        public_run_prefix=public_run_prefix,
        size_reason=size_reason,
    )
    live_result = _live_result_from_workflow_run(result, artifact_index=artifact_index)
    live_result["planner"] = planner_meta
    live_result["timeline"] = _timeline_from_events(result.run_dir / "events.jsonl", planner_meta)
    live_result["artifacts"] = run_meta["artifacts"]
    live_result["primary_artifact"] = _public_primary_artifact(
        live_result.get("primary_artifact"),
        run_meta["artifacts"],
    )
    (result.run_dir / "run_result.json").write_text(
        json.dumps(live_result, indent=2, default=str),
        encoding="utf-8",
    )
    artifact_index = write_artifact_index(result.run_dir)
    run_meta = _run_metadata(
        run_dir=result.run_dir,
        status=result.status,
        artifact_index=artifact_index,
        public_run_prefix=public_run_prefix,
        size_reason=size_reason,
    )
    live_result["artifacts"] = run_meta["artifacts"]
    live_result["primary_artifact"] = _public_primary_artifact(
        live_result.get("primary_artifact"),
        run_meta["artifacts"],
    )
    (result.run_dir / "run_result.json").write_text(
        json.dumps(live_result, indent=2, default=str),
        encoding="utf-8",
    )
    payload = project_agent_map(
        workflow,
        events_path=result.run_dir / "events.jsonl",
        proof_path=result.run_dir / "proof.json",
        run_dir=result.run_dir,
    )
    payload["preview_result"] = live_result
    payload["run"] = run_meta
    return payload


def _run_fix_test_map(
    *,
    workflow: WorkflowPlan,
    repo_root: Path,
    out_root: Path,
    run_id: str,
    options: AgentMapRunOptions,
    size_reason: str,
    public_run_prefix: str,
    planner_meta: dict[str, Any],
) -> dict[str, Any]:
    proof = run_fix_test_workflow(
        workflow=workflow,
        repo_root=repo_root,
        out_root=out_root,
        agent_name=options.agent,
        provider=options.provider if options.use_model else "",
        model=options.model if options.use_model else "",
        attempt_concurrency=options.attempt_concurrency,
        run_id=run_id,
    )
    run_dir = out_root / proof.run_id
    artifact_index = write_artifact_index(run_dir)
    run_meta = _run_metadata(
        run_dir=run_dir,
        status=proof.verdict,
        artifact_index=artifact_index,
        public_run_prefix=public_run_prefix,
        size_reason=size_reason,
    )
    live_result = _live_result_from_proof(proof, artifact_index=artifact_index)
    live_result["planner"] = planner_meta
    live_result["timeline"] = _timeline_from_events(run_dir / "events.jsonl", planner_meta)
    live_result["artifacts"] = run_meta["artifacts"]
    (run_dir / "run_result.json").write_text(
        json.dumps(live_result, indent=2, default=str),
        encoding="utf-8",
    )
    _persist_planner_provenance(run_dir, planner_meta, {})
    _write_observability_reports(run_dir, out_root)
    artifact_index = write_artifact_index(run_dir)
    run_meta = _run_metadata(
        run_dir=run_dir,
        status=proof.verdict,
        artifact_index=artifact_index,
        public_run_prefix=public_run_prefix,
        size_reason=size_reason,
    )
    live_result["artifacts"] = run_meta["artifacts"]
    (run_dir / "run_result.json").write_text(
        json.dumps(live_result, indent=2, default=str),
        encoding="utf-8",
    )
    payload = project_agent_map(
        workflow,
        events_path=run_dir / "events.jsonl",
        proof_path=run_dir / "proof.json",
        run_dir=run_dir,
    )
    payload["preview_result"] = live_result
    payload["run"] = run_meta
    return payload


def _build_model(options: AgentMapRunOptions) -> Any | None:
    if not options.use_model:
        return None
    from murmur.benchmarks.swe.providers import create_patch_model, default_model

    return create_patch_model(
        provider=options.provider or None,
        model=options.model or default_model(options.provider),
    )


def _write_observability_reports(run_dir: Path, out_root: Path) -> None:
    mirror = out_root.parent if out_root.name == "runs" else None
    write_workflow_observability_reports(run_dir, mirror_dir=mirror)


def _live_result_from_workflow_run(
    result: WorkflowRunResult,
    *,
    artifact_index: list[dict[str, str]],
) -> dict[str, Any]:
    final = result.node_results[-1] if result.node_results else None
    winner = _winner_from_nodes(result)
    lane_previews = _lane_previews_from_nodes(result, selected_id=winner.get("id", ""))
    failure = _first_failure(result) if result.status != "pass" else {}
    if not failure and result.status != "pass":
        artifact_error = str(
            result.proof.get("artifact_generation_error")
            or result.proof.get("site_generation_error", "")
        )
        if artifact_error:
            failure = {
                "node_id": "artifact",
                "op": "artifact",
                "message": artifact_error,
            }
    final_text = (
        failure.get("message")
        or winner.get("text")
        or (final.output if final else "")
        or result.status
    )
    site_preview = result.run_dir / "site" / "index.html"
    document_path = result.run_dir / "document.md"
    program_files = sorted((result.run_dir / "program").glob("main.*"))
    program_path = program_files[0] if program_files else None
    program_rel = program_path.relative_to(result.run_dir).as_posix() if program_path else ""
    document_preview = ""
    program_preview = ""
    if site_preview.is_file() and not failure:
        final_text = "Generated website preview: site/index.html"
    elif document_path.is_file() and not failure:
        final_text = "Generated document: document.md"
    elif program_path is not None and not failure:
        final_text = f"Generated program: {program_rel}"
    if document_path.is_file():
        document_preview = document_path.read_text(encoding="utf-8")[:4000]
    if program_path is not None:
        program_preview = program_path.read_text(encoding="utf-8")[:4000]
    winner_id = winner.get("id", final.node_id if final else "")
    winner_label = winner.get("label", final.node_id if final else "run")
    if failure:
        winner_id = failure["node_id"]
        winner_label = f"{failure['node_id']} failed"
    report = _generic_report_text(
        run_id=result.run_id,
        status=result.status,
        workflow_name=str(result.proof.get("workflow", {}).get("name", "")),
        winner_label=winner_label,
        final_text=final_text,
        node_count=len(result.node_results),
        budget=dict(result.proof.get("budget", {})),
    )
    artifacts = _artifact_links(artifact_index)
    primary_artifact = _primary_artifact(artifact_index)
    validation_summary = result.proof.get("validation_summary")
    failed_requirements = [
        str(item) for item in result.proof.get("failed_requirements", ())
    ]
    acceptance_summary = {
        "passed": bool(result.proof.get("requirements_passed", result.status == "pass")),
        "failed_requirements": failed_requirements,
        "winner_reason": str(result.proof.get("winner_reason", "")),
        "repair_count": int(result.proof.get("repair_count", 0) or 0),
    }
    return {
        "mode": "live",
        "status": result.status,
        "run_id": result.run_id,
        "run_dir": str(result.run_dir),
        "winner_id": winner_id,
        "winner_label": winner_label,
        "summary": _first_line(final_text) or f"Run {result.status}.",
        "report": report,
        "lane_previews": lane_previews,
        "gate_log": _gate_log_from_events(result.run_dir / "events.jsonl"),
        "artifacts": artifacts,
        "primary_artifact": primary_artifact,
        "validation_summary": validation_summary,
        "acceptance_summary": acceptance_summary,
        "failed_requirements": failed_requirements,
        "repair_iterations": _repair_iterations_payload(result.run_dir),
        "document_preview": document_preview,
        "program_preview": program_preview,
        "proof": result.proof,
        "note": _run_note(result.proof, failure),
    }


def _live_result_from_proof(
    proof: ProofPackage,
    *,
    artifact_index: list[dict[str, str]],
) -> dict[str, Any]:
    winner_id = _winner_attempt_id(proof)
    lane_previews = [
        {
            "id": str(attempt.get("attempt_id", "")),
            "label": str(attempt.get("attempt_id", "")),
            "selected": str(attempt.get("attempt_id", "")) == winner_id,
            "preview": _first_line(str(attempt.get("summary", "")))
            or ("passed" if attempt.get("passed") else "failed"),
        }
        for attempt in proof.attempts
    ]
    summary = _first_line(proof.summary) or f"Fix-test {proof.verdict}."
    report = (
        f"Run: {proof.run_id}\n"
        f"Status: {proof.verdict}\n"
        f"Winner: {winner_id or 'none'}\n"
        f"Attempts: {len(proof.attempts)}\n"
        f"Tool calls: {proof.tool_calls}\n"
        f"Model calls: {proof.model_calls}\n\n"
        f"{proof.summary}"
    )
    return {
        "mode": "live",
        "status": proof.verdict,
        "run_id": proof.run_id,
        "winner_id": winner_id,
        "winner_label": winner_id or "none",
        "summary": summary,
        "report": report,
        "lane_previews": lane_previews,
        "gate_log": [],
        "artifacts": _artifact_links(artifact_index),
        "primary_artifact": _primary_artifact(artifact_index),
        "validation_summary": None,
        "proof": proof.to_dict(),
    }


def _winner_from_nodes(result: WorkflowRunResult) -> dict[str, str]:
    for node in reversed(result.node_results):
        candidate = node.result.get("winner")
        if isinstance(candidate, dict):
            return {
                "id": str(candidate.get("id", node.node_id)),
                "label": str(candidate.get("id", node.node_id)).replace("_", " "),
                "text": str(candidate.get("text", "")),
            }
        if isinstance(candidate, str) and candidate:
            text = _candidate_text(result, candidate)
            if not text:
                continue
            return {
                "id": candidate,
                "label": candidate.replace("_", " "),
                "text": text,
            }
    for node in result.node_results:
        items = node.result.get("items")
        if isinstance(items, list) and items:
            return {
                "id": f"{node.node_id}_1",
                "label": f"{node.node_id} 1",
                "text": str(items[0]),
            }
    return {}


def _build_expected_artifacts(
    result: WorkflowRunResult,
    workflow: WorkflowPlan,
    *,
    use_model: bool,
) -> ArtifactBuildResult | None:
    contract = (
        contract_for_kind(workflow.artifact_kind)
        if workflow.artifact_kind
        else select_artifact_contract(workflow.goal)
    )
    if contract is None:
        return None
    # Offline there is no deterministic code generator, so skip the program contract
    # rather than failing the run on stub text that isn't real code.
    if contract.kind == "program" and not use_model:
        return None
    return contract.build(
        run_dir=result.run_dir,
        run_id=result.run_id,
        goal=workflow.goal,
        candidate_texts=_candidate_texts_from_result(result),
        events_path=result.run_dir / "events.jsonl",
    )


def _candidate_texts_from_result(result: WorkflowRunResult) -> list[str]:
    texts: list[str] = []
    winner = _winner_from_nodes(result)
    if winner.get("text"):
        texts.append(winner["text"])
    for node in reversed(result.node_results):
        if node.output:
            texts.append(node.output)
        content = node.result.get("content")
        if isinstance(content, str):
            texts.append(content)
        items = node.result.get("items")
        if isinstance(items, list):
            texts.extend(str(item) for item in reversed(items))
    return texts


def _needs_site_continuation(artifact_build: ArtifactBuildResult | None) -> bool:
    if artifact_build is None or artifact_build.validation.passed:
        return False
    return "missing_complete_site_artifact" in artifact_build.validation.risk_flags


def _improve_site_artifact(
    *,
    result: WorkflowRunResult,
    workflow: WorkflowPlan,
    options: AgentMapRunOptions,
    artifact_build: ArtifactBuildResult | None,
) -> ArtifactBuildResult | None:
    """Assemble truncated sites across passes, then enrich thin-but-working ones."""

    if _needs_site_continuation(artifact_build):
        artifact_build = _assemble_site_artifact(
            result=result,
            workflow=workflow,
            options=options,
        )
    if _site_is_thin(artifact_build):
        artifact_build = _enrich_site_artifact(
            result=result,
            workflow=workflow,
            options=options,
            artifact_build=artifact_build,
        )
    if _site_needs_repair(artifact_build):
        artifact_build = _repair_site_artifact(
            result=result,
            workflow=workflow,
            options=options,
            artifact_build=artifact_build,
        )
    return artifact_build


def _assemble_site_artifact(
    *,
    result: WorkflowRunResult,
    workflow: WorkflowPlan,
    options: AgentMapRunOptions,
) -> ArtifactBuildResult:
    """Stitch a truncated site across up to SITE_MAX_PASSES continuation calls."""

    candidates = _candidate_texts_from_result(result)
    model = _build_model(options)
    if model is None or not candidates:
        return _rebuild_site(result, workflow, candidates)
    base = _grow_site_text(
        result=result,
        model=model,
        goal=workflow.goal,
        base=max(candidates, key=len),
        seed=91,
        artifact_name="continuation",
    )
    return _rebuild_site(result, workflow, [base, *candidates])


def _enrich_site_artifact(
    *,
    result: WorkflowRunResult,
    workflow: WorkflowPlan,
    options: AgentMapRunOptions,
    artifact_build: ArtifactBuildResult | None,
) -> ArtifactBuildResult | None:
    """One enhancement pass for a complete-but-thin site; keep the richer artifact."""

    model = _build_model(options)
    site_path = result.run_dir / "site" / "index.html"
    if model is None or not site_path.is_file():
        return artifact_build
    current = site_path.read_text(encoding="utf-8")
    prompt = (
        "Here is a working single-file website. Substantially expand it into a richer, "
        "more immersive single valid HTML file: add the missing section types, real "
        "interactivity, polished motion, deeper subject-specific copy, and a responsive "
        "layout. Return ONLY the full updated HTML document.\n\n"
        f"Task:\n{workflow.goal}\n\n"
        f"Current site:\n{current}"
    )
    response = model.complete(
        system=_ENRICH_SYSTEM,
        user=prompt,
        seed=131,
        max_tokens=SITE_GEN_MAX_TOKENS,
    )
    _record_model_continuation(result, model, response)
    enriched = _grow_site_text(
        result=result,
        model=model,
        goal=workflow.goal,
        base=response.text.strip(),
        seed=151,
        artifact_name="enrichment",
    )
    # build_site_artifact keeps whichever candidate scores richest, so a weaker or
    # truncated enrichment can never replace the working original.
    return _rebuild_site(result, workflow, [enriched, current])


def _grow_site_text(
    *,
    result: WorkflowRunResult,
    model: Any,
    goal: str,
    base: str,
    seed: int,
    artifact_name: str,
) -> str:
    """Loop continuation calls until the HTML is complete or passes are exhausted."""

    artifacts_dir = result.run_dir / "nodes" / "site_artifact" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    text = base
    for pass_index in range(SITE_MAX_PASSES):
        if extract_index_html(text):
            break
        prompt = (
            "The previous HTML artifact was truncated. Continue from the exact tail "
            "below until the document is complete. Return only continuation text. End "
            "with </html> and close the markdown fence if the original used one.\n\n"
            f"Task:\n{goal}\n\n"
            f"Tail:\n{text[-3000:]}"
        )
        response = model.complete(
            system=_CONTINUE_SYSTEM,
            user=prompt,
            seed=seed + pass_index,
            max_tokens=SITE_GEN_MAX_TOKENS,
        )
        _record_model_continuation(result, model, response)
        continuation = response.text.strip()
        if not continuation:
            break
        (artifacts_dir / f"{artifact_name}_{pass_index + 1}.txt").write_text(
            continuation, encoding="utf-8"
        )
        text = _merge_site_continuation(text, continuation)
    return text


def _rebuild_site(
    result: WorkflowRunResult,
    workflow: WorkflowPlan,
    candidate_texts: list[str],
) -> ArtifactBuildResult:
    return build_site_artifact(
        run_dir=result.run_dir,
        run_id=result.run_id,
        goal=workflow.goal,
        candidate_texts=candidate_texts,
        events_path=result.run_dir / "events.jsonl",
    )


def _site_is_thin(artifact_build: ArtifactBuildResult | None) -> bool:
    if artifact_build is None or not artifact_build.validation.passed:
        return False
    return "thin_site" in artifact_build.validation.risk_flags


def _site_needs_repair(artifact_build: ArtifactBuildResult | None) -> bool:
    if artifact_build is None or artifact_build.validation.passed:
        return False
    return artifact_build.primary_artifact is not None or (
        "missing_complete_site_artifact" not in artifact_build.validation.risk_flags
    )


def _repair_site_artifact(
    *,
    result: WorkflowRunResult,
    workflow: WorkflowPlan,
    options: AgentMapRunOptions,
    artifact_build: ArtifactBuildResult | None,
) -> ArtifactBuildResult | None:
    model = _build_model(options)
    max_iterations = _site_repair_budget(workflow)
    site_path = result.run_dir / "site" / "index.html"
    if model is None or max_iterations <= 0 or not site_path.is_file():
        _write_repair_iterations(result.run_dir, [])
        return artifact_build

    current = site_path.read_text(encoding="utf-8")
    iterations: list[dict[str, Any]] = []
    current_build = artifact_build
    for index in range(1, max_iterations + 1):
        validation = current_build.validation if current_build is not None else None
        prompt = _site_repair_prompt(
            goal=workflow.goal,
            html=current,
            validation=validation,
        )
        (result.run_dir / "repair_prompt.md").write_text(prompt, encoding="utf-8")
        append_run_event(
            result.run_dir / "events.jsonl",
            result.run_id,
            "workflow_node_started",
            {
                "node_id": "repair_loop",
                "op": "loop",
                "message": f"site repair iteration {index}/{max_iterations}",
            },
        )
        response = model.complete(
            system=_ENRICH_SYSTEM,
            user=prompt,
            seed=211 + index,
            max_tokens=SITE_GEN_MAX_TOKENS,
        )
        _record_model_continuation(result, model, response)
        repaired = _grow_site_text(
            result=result,
            model=model,
            goal=workflow.goal,
            base=response.text.strip(),
            seed=241 + index * 10,
            artifact_name=f"repair_{index}",
        )
        current_build = _rebuild_site(result, workflow, [repaired])
        if site_path.is_file():
            current = site_path.read_text(encoding="utf-8")
        iteration = {
            "iteration": index,
            "passed": current_build.validation.passed,
            "summary": current_build.validation.summary,
            "risk_flags": list(current_build.validation.risk_flags),
            "failed_requirements": _failed_requirements(current_build.validation),
        }
        iterations.append(iteration)
        append_run_event(
            result.run_dir / "events.jsonl",
            result.run_id,
            "workflow_node_finished"
            if current_build.validation.passed
            else "workflow_node_failed",
            {
                "node_id": "repair_loop",
                "op": "loop",
                "message": iteration["summary"],
                "status": "pass" if current_build.validation.passed else "fail",
            },
        )
        if current_build.validation.passed:
            break
    _write_repair_iterations(result.run_dir, iterations)
    return current_build


def _site_repair_budget(workflow: WorkflowPlan) -> int:
    budget = int(workflow.budget.get("max_repairs", 0) or 0)
    for node in workflow.nodes:
        if node.op == "loop":
            budget = max(budget, _as_int(node.params.get("max_iterations"), 0))
    return max(0, budget)


def _site_repair_prompt(
    *,
    goal: str,
    html: str,
    validation: Any,
) -> str:
    validation_payload: dict[str, Any] = {}
    if validation is not None:
        validation_payload = validation.to_dict()
    contract = build_acceptance_contract(goal)
    return (
        "# Site repair task\n\n"
        "Return ONLY one complete HTML document from <!doctype html> to </html>. "
        "Do not include prose or markdown fences. Fix every hard failed requirement.\n\n"
        "## User goal\n"
        f"{goal}\n\n"
        "## Acceptance contract\n"
        f"{json.dumps(contract, indent=2, default=str)}\n\n"
        "## Failed validation evidence\n"
        f"{json.dumps(validation_payload, indent=2, default=str)[:12000]}\n\n"
        "## Current HTML\n"
        f"{html[:60000]}"
    )


def _write_repair_iterations(run_dir: Path, iterations: list[dict[str, Any]]) -> None:
    (run_dir / "repair_iterations.json").write_text(
        json.dumps(iterations, indent=2, default=str),
        encoding="utf-8",
    )


def _failed_requirements(validation: Any) -> list[str]:
    details = validation.details or {}
    acceptance = details.get("acceptance", {})
    failed = acceptance.get("failed_requirements", ())
    return [str(item) for item in failed]


def _repair_iterations_payload(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "repair_iterations.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _record_model_continuation(
    result: WorkflowRunResult,
    model: Any,
    response: Any,
) -> None:
    append_run_event(
        result.run_dir / "events.jsonl",
        result.run_id,
        "model_call_finished",
        {
            "node_id": "site_artifact",
            "model": getattr(model, "model", "model"),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": response.cost_usd,
            "continuation": True,
        },
    )


def _merge_site_continuation(base: str, continuation: str) -> str:
    merged = base + continuation
    if "```" in base and "```" not in continuation and "</html>" in continuation.lower():
        return merged.rstrip() + "\n```"
    return merged


def _refresh_workflow_proof(
    result: WorkflowRunResult,
    artifact_build: ArtifactBuildResult | None,
) -> WorkflowRunResult:
    proof = dict(result.proof)
    if artifact_build is not None:
        _record_artifact_gate_events(result, artifact_build.validation)
    evidence = RunEvidenceIndex.from_paths((result.run_dir / "events.jsonl",))
    tool_summary = evidence.tool_summary()
    (result.run_dir / "tool_summary.json").write_text(
        json.dumps(tool_summary, indent=2, default=str),
        encoding="utf-8",
    )
    proof["tool_summary"] = tool_summary
    budget = dict(proof.get("budget", {}))
    budget["tool_calls"] = int(tool_summary.get("total", budget.get("tool_calls", 0)))
    budget["model_calls"] = max(
        int(budget.get("model_calls", 0)),
        evidence.count("model_call_finished"),
    )
    budget["cost_usd"] = max(
        float(budget.get("cost_usd", 0.0)),
        _model_cost_from_events(evidence.rows),
    )
    proof["budget"] = budget
    status = result.status
    if artifact_build is not None:
        validation = artifact_build.validation
        proof["validation_summary"] = validation.to_dict()
        proof["risk_flags"] = list(validation.risk_flags)
        proof["trust_score"] = artifact_trust_score(validation, tool_summary)
        acceptance = _acceptance_from_validation(validation)
        proof["acceptance_contract"] = acceptance.get("contract", {})
        proof["requirements_passed"] = bool(acceptance.get("passed", validation.passed))
        proof["failed_requirements"] = [
            str(item) for item in acceptance.get("failed_requirements", ())
        ]
        proof["repair_count"] = _repair_count(result.run_dir)
        proof["winner_reason"] = _winner_reason(validation)
        if artifact_build.primary_artifact:
            proof["primary_artifact"] = artifact_build.primary_artifact
        if not validation.passed:
            status = "fail"
            proof["artifact_generation_error"] = validation.summary
    proof["status"] = status
    artifact_index = write_artifact_index(result.run_dir)
    proof["artifact_index"] = artifact_index
    (result.run_dir / "proof.json").write_text(
        json.dumps(proof, indent=2, default=str),
        encoding="utf-8",
    )
    return WorkflowRunResult(
        run_id=result.run_id,
        status=status,
        run_dir=result.run_dir,
        node_results=result.node_results,
        proof=proof,
    )


def _acceptance_from_validation(validation: Any) -> dict[str, Any]:
    details = validation.details or {}
    acceptance = details.get("acceptance", {})
    return dict(acceptance) if isinstance(acceptance, dict) else {}


def _repair_count(run_dir: Path) -> int:
    path = run_dir / "repair_iterations.json"
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return len(payload) if isinstance(payload, list) else 0


def _winner_reason(validation: Any) -> str:
    if validation.passed:
        return "Selected artifact passed hard acceptance and browser validation."
    failed = _failed_requirements(validation)
    if failed:
        return "No artifact satisfied hard requirements: " + ", ".join(failed[:6])
    return validation.summary


def _record_artifact_gate_events(
    result: WorkflowRunResult,
    validation: Any,
) -> None:
    events_path = result.run_dir / "events.jsonl"
    acceptance = _acceptance_from_validation(validation)
    passed = bool(validation.passed)
    node_status = {
        "validate_site": bool(validation.checks.get("html_complete", False))
        and bool(validation.checks.get("artifact_written", False)),
        "browser_verify": bool(validation.checks.get("browser_rendered", False))
        and bool(validation.checks.get("dom_visible", False))
        and bool(validation.checks.get("console_clean", False)),
        "requirement_assert": bool(acceptance.get("passed", passed)),
    }
    if _workflow_has_node(result, "repair_loop"):
        node_status["repair_loop"] = passed
    for node_id, node_passed in node_status.items():
        if not _workflow_has_node(result, node_id):
            continue
        append_run_event(
            events_path,
            result.run_id,
            "workflow_node_finished" if node_passed else "workflow_node_failed",
            {
                "node_id": node_id,
                "op": "verify" if node_id != "repair_loop" else "loop",
                "message": validation.summary if not node_passed else "validated",
                "status": "pass" if node_passed else "fail",
            },
        )


def _workflow_has_node(result: WorkflowRunResult, node_id: str) -> bool:
    workflow = result.proof.get("workflow", {})
    nodes = workflow.get("nodes", ())
    if isinstance(nodes, list) and any(
        isinstance(node, dict) and node.get("node_id") == node_id for node in nodes
    ):
        return True
    return any(node.node_id == node_id for node in result.node_results)


def _model_cost_from_events(rows: tuple[dict[str, Any], ...]) -> float:
    total = 0.0
    for row in rows:
        if row.get("type") != "model_call_finished":
            continue
        payload = dict(row.get("payload", {}))
        total += float(payload.get("cost_usd", 0.0))
    return total


def _first_failure(result: WorkflowRunResult) -> dict[str, str]:
    for node in result.node_results:
        if node.passed and not node.quarantined:
            continue
        message = node.error or node.skipped_reason or node.output or node.status
        return {
            "node_id": node.node_id,
            "op": node.op,
            "message": message,
        }
    return {}


def _candidate_text(result: WorkflowRunResult, candidate_id: str) -> str:
    for node in result.node_results:
        candidates = node.result.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict) and str(candidate.get("id", "")) == candidate_id:
                    return str(candidate.get("text", ""))
        items = node.result.get("items")
        if isinstance(items, list):
            prefix = f"{node.node_id}_"
            if candidate_id.startswith(prefix):
                try:
                    index = int(candidate_id.removeprefix(prefix)) - 1
                except ValueError:
                    continue
                if 0 <= index < len(items):
                    return str(items[index])
    return ""


def _lane_previews_from_nodes(
    result: WorkflowRunResult,
    *,
    selected_id: str,
) -> list[dict[str, Any]]:
    for node in result.node_results:
        items = node.result.get("items")
        if not isinstance(items, list):
            continue
        lanes: list[dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            candidate_id = f"{node.node_id}_{index}"
            item_text = str(item)
            preview = _site_candidate_preview(item_text)
            if not preview:
                preview = _first_line(item_text) or f"candidate {index}"
            lanes.append(
                {
                    "id": candidate_id,
                    "label": f"agent {index}",
                    "selected": selected_id == candidate_id,
                    "preview": preview,
                }
            )
        return lanes
    return []


def _site_candidate_preview(text: str) -> str:
    html = extract_index_html(text)
    if not html:
        return ""
    richness = "rich"
    if len(html) < 4000:
        richness = "thin"
    return f"HTML site candidate ({len(html):,} chars, {richness})"


def _generic_report_text(
    *,
    run_id: str,
    status: str,
    workflow_name: str,
    winner_label: str,
    final_text: str,
    node_count: int,
    budget: dict[str, Any],
) -> str:
    return (
        f"Run: {run_id}\n"
        f"Workflow: {workflow_name or 'workflow'}\n"
        f"Status: {status}\n"
        f"Winner: {winner_label or 'single path'}\n"
        f"Nodes: {node_count}\n"
        f"Model calls: {budget.get('model_calls', 0)}\n"
        f"Tool calls: {budget.get('tool_calls', 0)}\n"
        f"Cost: ${float(budget.get('cost_usd', 0.0)):.4f}\n\n"
        f"Final output:\n{final_text}"
    )


def _gate_log_from_events(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        payload = event.get("payload", {})
        event_type = str(event.get("type", ""))
        if not event_type.startswith("workflow_node_") and event_type != "workflow_finished":
            continue
        gate = str(payload.get("node_id", ""))
        rows.append(
            {
                "gate": gate,
                "type": event_type,
                "message": str(payload.get("message", payload.get("status", ""))),
            }
        )
    return rows


def _artifact_links(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "kind": item["kind"],
            "path": item["path"],
            "description": item.get("description", ""),
            "href": item["path"],
        }
        for item in entries
    ]


def _primary_artifact(entries: list[dict[str, str]]) -> dict[str, str] | None:
    for kind in ("site_preview", "program", "document"):
        for item in entries:
            if item["kind"] == kind:
                return {
                    "kind": item["kind"],
                    "path": item["path"],
                    "description": item.get("description", ""),
                    "href": item["path"],
                }
    return None


def _public_primary_artifact(
    artifact: object,
    public_artifacts: list[dict[str, str]],
) -> dict[str, str] | None:
    if not isinstance(artifact, dict):
        return None
    kind = str(artifact.get("kind", ""))
    path = str(artifact.get("path", ""))
    for public in public_artifacts:
        if public.get("kind") == kind and public.get("path") == path:
            return public
    return {
        "kind": kind,
        "path": path,
        "href": str(artifact.get("href", path)),
        "description": str(artifact.get("description", "")),
    }


def _run_metadata(
    *,
    run_dir: Path,
    status: str,
    artifact_index: list[dict[str, str]],
    public_run_prefix: str,
    size_reason: str,
) -> dict[str, Any]:
    run_id = run_dir.name
    artifacts = []
    for item in artifact_index:
        relative = item["path"]
        artifacts.append(
            {
                **item,
                "href": f"{public_run_prefix}/{run_id}/{relative}",
            }
        )
    return {
        "run_id": run_id,
        "status": status,
        "run_dir": str(run_dir),
        "size_reason": size_reason,
        "artifacts": artifacts,
    }


def _winner_attempt_id(proof: ProofPackage) -> str:
    for attempt in proof.attempts:
        if attempt.get("passed"):
            return str(attempt.get("attempt_id", ""))
    if proof.attempts:
        return str(proof.attempts[0].get("attempt_id", ""))
    return ""


def _run_note(proof: dict[str, Any], failure: dict[str, str]) -> str:
    if failure:
        message = failure.get("message", "")
        if "API_KEY" in message:
            return (
                "Model generation was requested, but provider credentials are missing. "
                "Set the API key and restart the server, or uncheck Use model for a "
                "deterministic local run."
            )
        if proof.get("failed_requirements"):
            return (
                "The artifact is visible, but it is not trusted because hard "
                "acceptance requirements failed."
            )
        return f"Node {failure.get('node_id', 'unknown')} failed: {message}"
    return _model_note(proof)


def _model_note(proof: dict[str, Any]) -> str:
    if int(proof.get("model_retries", 0)) > 0:
        return "Model retries were recorded. Open proof.json for provider error details."
    budget = dict(proof.get("budget", {}))
    if int(budget.get("model_calls", 0)) == 0:
        return "Local deterministic run. Set provider/model controls to make live model calls."
    return ""


def _safe_run_id(value: str) -> str:
    raw = value.strip()
    if not raw:
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"web_{stamp}_{uuid4().hex[:8]}"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
    return safe.strip("._-") or f"web_{uuid4().hex[:8]}"


def _is_coding_fix_test(workflow: WorkflowPlan) -> bool:
    return workflow.name == "coding_fix_test"


def _plan_size_summary(workflow: WorkflowPlan, reason: str) -> dict[str, Any]:
    """Derive the displayed fan-out/repair size from the actual plan, not the heuristic."""

    attempts = 1
    max_repairs = 0
    for node in workflow.nodes:
        if node.op == "map":
            attempts = max(attempts, _as_int(node.params.get("n"), 1))
        elif node.op == "loop":
            max_repairs = max(max_repairs, _as_int(node.params.get("max_iterations"), 0))
    return {"attempts": attempts, "max_repairs": max_repairs, "reason": reason}


def _persist_planner_provenance(
    run_dir: Path,
    planner_meta: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Record how the plan was produced (model vs template) in the run's evidence."""

    preview = payload.get("preview_result")
    if isinstance(preview, dict):
        preview["planner"] = planner_meta
    _merge_planner_into_proof(run_dir / "proof.json", planner_meta)
    update_json_file(run_dir / "run_result.json", {"planner": planner_meta})
    events_path = run_dir / "events.jsonl"
    if events_path.is_file() and not _planner_event_recorded(events_path):
        append_run_event(
            events_path,
            run_dir.name,
            "workflow_planned",
            {"planner": planner_meta},
        )


def _merge_planner_into_proof(path: Path, planner_meta: dict[str, Any]) -> None:
    """Fold the planning model call's time/tokens/cost into the proof budget."""

    if not path.is_file():
        return
    proof = json.loads(path.read_text(encoding="utf-8"))
    already_merged = proof.get("planner") == planner_meta
    proof["planner"] = planner_meta
    budget = dict(proof.get("budget", {}))
    if not already_merged:
        budget["model_calls"] = int(budget.get("model_calls", 0)) + int(
            planner_meta.get("model_calls", 0)
        )
        budget["cost_usd"] = round(
            float(budget.get("cost_usd", 0.0)) + float(planner_meta.get("cost_usd", 0.0)),
            6,
        )
    budget["planning_ms"] = round(float(planner_meta.get("duration_ms", 0.0)), 1)
    proof["budget"] = budget
    path.write_text(json.dumps(proof, indent=2, default=str), encoding="utf-8")


def _planner_event_recorded(events_path: Path) -> bool:
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") == "workflow_planned":
            return True
    return False


def _timeline_from_events(events_path: Path, planner_meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-module timeline (planning + each node) with time, tokens, and agent thinking."""

    timeline: list[dict[str, Any]] = []
    if planner_meta:
        timeline.append(
            {
                "step": f"planning ({planner_meta.get('mode', '?')})",
                "kind": "planning",
                "status": "pass",
                "duration_ms": float(planner_meta.get("duration_ms", 0.0)),
                "tokens": int(planner_meta.get("output_tokens", 0)),
                "cost_usd": float(planner_meta.get("cost_usd", 0.0)),
                "detail": str(planner_meta.get("reason", "")),
                "thinking": str(planner_meta.get("reasoning", "")),
            }
        )
    if not events_path.is_file():
        return timeline

    rows: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    thinking_by_node: dict[str, list[dict[str, Any]]] = {}
    for event in rows:
        if event.get("type") == "model_call_finished":
            payload = dict(event.get("payload", {}))
            thinking_by_node.setdefault(str(payload.get("node_id", "")), []).append(payload)

    terminal = {
        "workflow_node_finished",
        "workflow_node_failed",
        "workflow_node_quarantined",
        "workflow_node_skipped",
    }
    for event in rows:
        if event.get("type") not in terminal:
            continue
        payload = dict(event.get("payload", {}))
        node_id = str(payload.get("node_id", ""))
        calls = thinking_by_node.get(node_id, [])
        detail = (
            str(payload.get("output", ""))
            or str(payload.get("error", ""))
            or str(payload.get("skipped_reason", ""))
        )
        timeline.append(
            {
                "step": f"{node_id} [{payload.get('op', '')}]",
                "kind": "node",
                "status": "pass" if payload.get("passed") else "fail",
                "duration_ms": float(payload.get("latency_ms", 0.0)),
                "tokens": sum(int(call.get("output_tokens", 0)) for call in calls),
                "cost_usd": round(sum(float(call.get("cost_usd", 0.0)) for call in calls), 6),
                "detail": detail[:240],
                "thinking": " ".join(
                    str(call.get("thinking", "")) for call in calls if call.get("thinking")
                )[:2000],
            }
        )
    return timeline


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _first_line(text: str, *, max_len: int = 260) -> str:
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line[:max_len]
