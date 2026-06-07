"""PR proof package data for contract-first runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from chorus.domain.contract import Contract
from chorus.domain.trust import TrustScore
from chorus.domain.verification import VerificationResult


@dataclass(frozen=True, slots=True)
class ProofPackage:
    run_id: str
    verdict: str
    contract: Contract
    verification: VerificationResult
    diff: str
    model_calls: int
    tool_calls: int
    cost_usd: float
    summary: str = ""
    attempts: tuple[dict[str, Any], ...] = ()
    tool_summary: dict[str, Any] = field(default_factory=dict)
    trust_score: TrustScore | None = None
    risk_flags: tuple[str, ...] = ()
    artifact_index: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["contract"] = self.contract.to_dict()
        data["verification"] = self.verification.to_dict()
        data["trust_score"] = self.trust_score.to_dict() if self.trust_score else None
        data["risk_flags"] = list(self.risk_flags)
        data["artifact_index"] = list(self.artifact_index)
        return data
