# Development notes

Design rationale and working documents that shaped Murmur. These are historical
records, not current product claims — see the root [README](../../README.md)
for what is actually implemented and verified today.

- [architecture-and-build-plan.md](architecture-and-build-plan.md) — the
  original "self-writing multi-agent harness for cheap models" design: workflow
  IR, operator catalog, design patterns, and the phased build plan.
- [closed-loop-refactor-plan.md](closed-loop-refactor-plan.md) — the refactor
  plan that reconciled that design with the contract-first execution codebase
  (exec operator, candidate isolation, deterministic ranking).
- [code-review-2026-06-12.md](code-review-2026-06-12.md) — a full-codebase
  review pass: bugs found and fixed, modules reviewed clean, known limitations.

Repo-root config files `.mcp.json`, `.agents/`, `skills-lock.json`, and
`.codex/` are local AI-tooling configuration (MCP servers and editor-agent
skills) used during development; they are not part of the Murmur package or its
runtime.
