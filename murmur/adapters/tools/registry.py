"""Tool adapter registry for contract execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from murmur.adapters.sandboxes.local_worktree import LocalWorktreeSandbox
from murmur.application.event_log import JsonlRunEventLog
from murmur.domain.policy import BudgetState, PolicyEngine


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    name: str
    schema: dict[str, Any] = field(default_factory=dict)
    read_only: bool = False
    destructive: bool = False
    requires_network: bool = False
    writes_files: bool = False
    timeout_s: int = 60
    approval_mode: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolContext:
    sandbox: LocalWorktreeSandbox
    policy: PolicyEngine
    budget: BudgetState
    events: JsonlRunEventLog


class ToolAdapter(Protocol):
    metadata: ToolMetadata

    def call(self, args: dict[str, Any], context: ToolContext) -> Any:
        """Execute one policy-approved tool call."""


class ListFilesAdapter:
    metadata = ToolMetadata(
        name="list_files",
        schema={"glob": "string"},
        read_only=True,
    )

    def call(self, args: dict[str, Any], context: ToolContext) -> Any:
        return context.sandbox.list_files(str(args.get("glob", "**/*")))


class SearchAdapter:
    metadata = ToolMetadata(
        name="search",
        schema={"query": "string", "glob": "string"},
        read_only=True,
    )

    def call(self, args: dict[str, Any], context: ToolContext) -> Any:
        return context.sandbox.search(str(args.get("query", "")), str(args.get("glob", "**/*")))


class ReadFileAdapter:
    metadata = ToolMetadata(
        name="read_file",
        schema={"path": "string"},
        read_only=True,
    )

    def call(self, args: dict[str, Any], context: ToolContext) -> Any:
        return context.sandbox.read_file(str(args["path"]))


class ApplyPatchAdapter:
    metadata = ToolMetadata(
        name="apply_patch",
        schema={"patch": "unified diff string"},
        writes_files=True,
        timeout_s=30,
    )

    def call(self, args: dict[str, Any], context: ToolContext) -> Any:
        proc = context.sandbox.apply_patch(str(args["patch"]))
        if proc.returncode != 0:
            raise RuntimeError(proc.output or "patch apply failed")
        context.events.emit("patch_applied", {"stdout": proc.stdout, "stderr": proc.stderr})
        return "patch applied"


class RunTestAdapter:
    metadata = ToolMetadata(
        name="run_test",
        schema={"command": "string"},
        timeout_s=600,
    )

    def call(self, args: dict[str, Any], context: ToolContext) -> Any:
        proc = context.sandbox.run(
            str(args["command"]),
            timeout_s=context.policy.contract.budget.max_runtime_seconds,
            parser="pytest",
        )
        context.budget.runtime_seconds += proc.latency_ms / 1000
        return proc.to_dict()


class GitDiffAdapter:
    metadata = ToolMetadata(
        name="git_diff",
        schema={},
        read_only=True,
    )

    def call(self, _args: dict[str, Any], context: ToolContext) -> Any:
        return context.sandbox.git_diff()


class FinishAdapter:
    metadata = ToolMetadata(
        name="finish",
        schema={"summary": "string"},
        read_only=True,
    )

    def call(self, args: dict[str, Any], _context: ToolContext) -> Any:
        return str(args.get("summary", ""))


def default_tool_adapters() -> dict[str, ToolAdapter]:
    adapters: tuple[ToolAdapter, ...] = (
        ListFilesAdapter(),
        SearchAdapter(),
        ReadFileAdapter(),
        ApplyPatchAdapter(),
        RunTestAdapter(),
        GitDiffAdapter(),
        FinishAdapter(),
    )
    return {adapter.metadata.name: adapter for adapter in adapters}


def default_tool_metadata() -> list[dict[str, Any]]:
    return [adapter.metadata.to_dict() for adapter in default_tool_adapters().values()]
