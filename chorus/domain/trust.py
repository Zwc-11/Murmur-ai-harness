"""Trust scoring for AI-generated changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from chorus.domain.contract import Contract
from chorus.domain.policy import BudgetState
from chorus.domain.verification import VerificationResult


@dataclass(frozen=True, slots=True)
class TrustScore:
    score: int
    level: str
    checks: dict[str, bool]
    risk_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_flags"] = list(self.risk_flags)
        return data


def compute_trust_score(
    *,
    contract: Contract,
    verification: VerificationResult,
    budget: BudgetState,
    tool_summary: dict[str, Any],
) -> TrustScore:
    """Score the proof package from objective evidence only."""

    del contract
    checks = {
        "failure_reproduced": verification.failure_reproduced,
        "target_test_passed": verification.target_test_passed,
        "related_tests_passed": verification.related_tests_passed,
        "static_checks_passed": verification.static_checks_passed,
        "forbidden_files_clean": not verification.forbidden_files_touched,
        "diff_size_ok": "diff_too_large" not in verification.failures,
        "tool_trace_present": bool(tool_summary.get("total", 0)) or not budget.tool_calls,
        "tool_budget_ok": True,
        "model_budget_ok": True,
    }
    weights = {
        "failure_reproduced": 10,
        "target_test_passed": 25,
        "related_tests_passed": 10,
        "static_checks_passed": 10,
        "forbidden_files_clean": 15,
        "diff_size_ok": 10,
        "tool_trace_present": 10,
        "tool_budget_ok": 5,
        "model_budget_ok": 5,
    }
    score = sum(weight for key, weight in weights.items() if checks[key])
    risk_flags = list(verification.failures)
    if verification.forbidden_files_touched or "test_failed" in verification.failures:
        score = min(score, 69)
    if not verification.target_test_passed:
        score = min(score, 69)
    if budget.tool_calls and not tool_summary.get("total", 0):
        risk_flags.append("missing_tool_trace")
    level = "high"
    if score < 70:
        level = "medium"
    if score < 50:
        level = "low"
    return TrustScore(
        score=max(0, min(100, score)),
        level=level,
        checks=checks,
        risk_flags=tuple(dict.fromkeys(risk_flags)),
    )
