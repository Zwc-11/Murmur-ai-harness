"""Policy-controlled typed tools for contract execution."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from chorus.adapters.sandboxes.local_worktree import LocalWorktreeSandbox
from chorus.adapters.tools.registry import ToolAdapter, ToolContext, default_tool_adapters
from chorus.application.event_log import JsonlRunEventLog
from chorus.domain.policy import BudgetState, PolicyEngine
from chorus.domain.tool import ToolRequest, ToolResult


class ContractToolProxy:
    def __init__(
        self,
        *,
        sandbox: LocalWorktreeSandbox,
        policy: PolicyEngine,
        budget: BudgetState,
        events: JsonlRunEventLog,
        metadata: dict[str, Any] | None = None,
        adapters: dict[str, ToolAdapter] | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.policy = policy
        self.budget = budget
        self.events = events
        self.metadata = metadata or {}
        self.adapters = adapters or default_tool_adapters()
        self.finished = False
        self.finish_summary = ""

    def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        request = ToolRequest(name, args)
        payload = {"tool": name, "args": args, "metadata": self.metadata}
        self.events.emit("tool_call_requested", payload)
        decision = self.policy.evaluate(request)
        self.events.emit(
            "policy_decision",
            {"tool": name, "decision": decision, "metadata": self.metadata},
        )
        if not decision.allowed:
            result = ToolResult(name, False, error=decision.reason)
            self.events.emit(
                "tool_call_denied",
                {"tool": name, "error": decision.reason, "metadata": self.metadata},
            )
            return result
        if name not in self.adapters:
            result = ToolResult(name, False, error=f"tool {name!r} is not registered")
            self.events.emit(
                "tool_call_denied",
                {"tool": name, "error": result.error, "metadata": self.metadata},
            )
            return result

        self.budget.tool_calls += 1
        start = perf_counter()
        try:
            payload = self._execute(name, args)
            result = ToolResult(name, True, result=payload, latency_ms=_elapsed(start))
        except Exception as exc:  # noqa: BLE001 - tool proxy records all tool faults
            result = ToolResult(name, False, error=str(exc), latency_ms=_elapsed(start))
        self.events.emit("tool_result", {"tool": name, "result": result, "metadata": self.metadata})
        return result

    def _execute(self, name: str, args: dict[str, Any]) -> Any:
        adapter = self.adapters.get(name)
        if adapter is None:
            raise KeyError(f"unknown tool {name!r}")
        result = adapter.call(
            args,
            ToolContext(
                sandbox=self.sandbox,
                policy=self.policy,
                budget=self.budget,
                events=self.events,
            ),
        )
        if name == "finish":
            self.finished = True
            self.finish_summary = str(result)
        return result


def _elapsed(start: float) -> float:
    return (perf_counter() - start) * 1000
