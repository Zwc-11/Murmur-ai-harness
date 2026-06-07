"""Verify pull-request style diffs without using a model."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

from murmur.adapters.sandboxes.local_worktree import LocalWorktreeSandbox
from murmur.adapters.tools.contract_proxy import ContractToolProxy
from murmur.application.event_log import JsonlRunEventLog
from murmur.application.proof_builder import write_proof_package
from murmur.application.tool_summary import summarize_tool_events
from murmur.domain.contract import (
    BudgetSpec,
    Contract,
    ContractTask,
    FilePolicy,
    ProofSpec,
    RepoSpec,
    RiskSpec,
    ToolPolicy,
)
from murmur.domain.policy import BudgetState, PolicyEngine
from murmur.domain.proof import ProofPackage
from murmur.domain.tool import ExecResult
from murmur.domain.trust import compute_trust_score
from murmur.domain.verification import VerificationResult


def verify_pr(
    *,
    repo_root: Path,
    base: str,
    head: str,
    out_root: Path,
    commands: tuple[str, ...] = (),
    budget_usd: float = 0.10,
    run_id: str = "",
) -> ProofPackage:
    run_id = run_id or f"pr_{uuid4().hex[:12]}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    events = JsonlRunEventLog(run_dir / "events.jsonl", run_id=run_id)

    diff = _git(repo_root, "diff", "--find-renames", f"{base}..{head}", "--")
    changed_files = _changed_files(repo_root, base, head)
    contract = compile_pr_diff_contract(
        repo_root=repo_root,
        base=base,
        head=head,
        changed_files=changed_files,
        commands=commands,
        budget_usd=budget_usd,
    )
    contract.write(run_dir / "contract.yaml")
    (run_dir / "diff.patch").write_text(diff, encoding="utf-8")

    sandbox = _head_sandbox(repo_root=repo_root, run_dir=run_dir, head=head)
    budget = BudgetState()
    policy = PolicyEngine(contract, budget)
    proxy = ContractToolProxy(
        sandbox=sandbox,
        policy=policy,
        budget=budget,
        events=events,
        metadata={"node_id": "verify_pr"},
    )
    test_results = tuple(_run_policy_command(proxy, command) for command in commands)
    verification = _verify_pr_contract(
        contract=contract,
        policy=policy,
        diff=diff,
        changed_files=changed_files,
        test_results=test_results,
    )
    tool_summary = summarize_tool_events((events.path,))
    (run_dir / "tool_summary.json").write_text(
        json.dumps(tool_summary, indent=2),
        encoding="utf-8",
    )
    trust_score = compute_trust_score(
        contract=contract,
        verification=verification,
        budget=budget,
        tool_summary=tool_summary,
    )
    proof = ProofPackage(
        run_id=run_id,
        verdict="pass" if verification.passed else "fail",
        contract=contract,
        verification=verification,
        diff=diff,
        model_calls=budget.model_calls,
        tool_calls=budget.tool_calls,
        cost_usd=budget.cost_usd,
        summary=_summary(verification, trust_score.score),
        attempts=(),
        tool_summary=tool_summary,
        trust_score=trust_score,
        risk_flags=trust_score.risk_flags,
    )
    (run_dir / "proof.json").write_text(
        json.dumps(_proof_json(proof, budget), indent=2, default=str),
        encoding="utf-8",
    )
    (run_dir / "review_comment.md").write_text(render_review_comment(proof), encoding="utf-8")
    write_proof_package(proof, run_dir)
    return proof


def compile_pr_diff_contract(
    *,
    repo_root: Path,
    base: str,
    head: str,
    changed_files: tuple[str, ...],
    commands: tuple[str, ...] = (),
    budget_usd: float = 0.10,
) -> Contract:
    file_defaults = FilePolicy()
    tool_defaults = ToolPolicy()
    return Contract(
        version=1,
        task=ContractTask(
            id=f"verify-pr-{_short_ref(base)}-{_short_ref(head)}",
            type="pr_diff",
            title=f"Verify PR diff {base}..{head}",
            command=commands[0] if commands else "",
        ),
        repo=RepoSpec(root=str(repo_root), base_ref=base, worktree_mode="isolated"),
        risk=RiskSpec(level="medium", reason=("Generated from PR diff",)),
        budget=BudgetSpec(max_cost_usd=budget_usd, max_model_calls=0, max_tool_calls=40),
        files=FilePolicy(
            allow_read=("*", "**/*"),
            allow_edit=tuple(changed_files) or ("**/*",),
            deny_read=file_defaults.deny_read,
            deny_edit=file_defaults.deny_edit,
        ),
        tools=ToolPolicy(allow=("run_test", "finish"), deny=tool_defaults.deny),
        required_proof=ProofSpec(
            reproduce_before_fix=False,
            target_test_passes_after_fix=bool(commands),
            related_tests=(),
            static_checks=commands,
            forbidden_files_unchanged=True,
            max_files_changed=20,
            max_diff_lines=400,
        ),
    )


def render_review_comment(proof: ProofPackage) -> str:
    trust = proof.trust_score.score if proof.trust_score else "n/a"
    level = proof.trust_score.level if proof.trust_score else "unscored"
    failures = ", ".join(proof.verification.failures) if proof.verification.failures else "none"
    changed = ", ".join(proof.verification.changed_files) or "none"
    return (
        "## Murmur PR Proof\n\n"
        f"- Verdict: **{proof.verdict.upper()}**\n"
        f"- Trust: **{trust}/100 ({level})**\n"
        f"- Changed files: {changed}\n"
        f"- Diff lines: {proof.verification.diff_lines}\n"
        f"- Failures: {failures}\n"
        f"- Report: `report.html`\n"
        f"- Workbench: `workbench.html`\n"
    )


def _verify_pr_contract(
    *,
    contract: Contract,
    policy: PolicyEngine,
    diff: str,
    changed_files: tuple[str, ...],
    test_results: tuple[ExecResult, ...],
) -> VerificationResult:
    failures: list[str] = []
    forbidden = tuple(path for path in changed_files if not policy.check_changed_file(path).allowed)
    if forbidden:
        failures.append("forbidden_file_touched")
    if len(changed_files) > contract.required_proof.max_files_changed:
        failures.append("too_many_files_changed")
    diff_lines = _diff_line_count(diff)
    if diff_lines > contract.required_proof.max_diff_lines:
        failures.append("diff_too_large")
    tests_passed = all(result.passed for result in test_results) if test_results else True
    if not tests_passed:
        failures.append("test_failed")

    target_output = "\n\n".join(result.output for result in test_results)
    static_outputs = {result.command: result.output for result in test_results}
    passed = not failures
    return VerificationResult(
        passed=passed,
        failure_reproduced=True,
        target_test_passed=tests_passed,
        related_tests_passed=True,
        static_checks_passed=tests_passed,
        forbidden_files_touched=forbidden,
        changed_files=changed_files,
        diff_lines=diff_lines,
        failures=tuple(dict.fromkeys(failures)),
        target_output=target_output,
        related_outputs={},
        static_outputs=static_outputs,
    )


def _head_sandbox(*, repo_root: Path, run_dir: Path, head: str) -> LocalWorktreeSandbox:
    worktree = run_dir / "head" / "worktree"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), head],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        _clone_head(repo_root=repo_root, worktree=worktree, head=head)
    return LocalWorktreeSandbox(repo_root, worktree)


def _clone_head(*, repo_root: Path, worktree: Path, head: str) -> None:
    if worktree.exists():
        import shutil

        shutil.rmtree(worktree)
    clone = subprocess.run(
        ["git", "clone", "--no-checkout", str(repo_root.resolve()), str(worktree)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if clone.returncode != 0:
        raise RuntimeError(clone.stderr or clone.stdout or "git clone failed")
    checkout = subprocess.run(
        ["git", "checkout", "--detach", head],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if checkout.returncode != 0:
        raise RuntimeError(checkout.stderr or checkout.stdout or "git checkout failed")


def _run_policy_command(proxy: ContractToolProxy, command: str) -> ExecResult:
    result = proxy.call("run_test", {"command": command})
    if result.ok and isinstance(result.result, dict):
        return ExecResult.from_dict(result.result)
    return ExecResult(
        command=command,
        returncode=1,
        stdout="",
        stderr=result.error,
        passed=False,
        summary=result.error or "command denied",
        latency_ms=result.latency_ms,
    )


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or f"git {' '.join(args)} failed")
    return proc.stdout


def _changed_files(repo_root: Path, base: str, head: str) -> tuple[str, ...]:
    output = _git(repo_root, "diff", "--name-only", f"{base}..{head}", "--")
    return tuple(line.strip().replace("\\", "/") for line in output.splitlines() if line.strip())


def _diff_line_count(diff: str) -> int:
    return sum(
        1
        for line in diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _proof_json(proof: ProofPackage, budget: BudgetState) -> dict[str, object]:
    payload = proof.to_dict()
    payload["status"] = proof.verdict
    payload["budget"] = {
        "model_calls": budget.model_calls,
        "tool_calls": budget.tool_calls,
        "runtime_seconds": budget.runtime_seconds,
        "cost_usd": budget.cost_usd,
    }
    return payload


def _summary(verification: VerificationResult, score: int) -> str:
    failures = ", ".join(verification.failures) if verification.failures else "none"
    return f"PR trust score {score}/100. Failures: {failures}."


def _short_ref(ref: str) -> str:
    return ref.replace("/", "-")[:24] or "ref"
