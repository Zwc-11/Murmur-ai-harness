"""Failure classification helpers.

This file maps low-level errors into Chorus failure classes. The classifier
stays read-only: it labels what happened, but it never drives the agent.
"""

from __future__ import annotations


def classify_failure(error: BaseException | None) -> str | None:
    if error is None:
        return None
    error_name = error.__class__.__name__.lower()
    if "divergence" in error_name:
        return "nondeterministic_loop"
    if "timeout" in error_name:
        return "budget_exceeded"
    if "key" in error_name or "value" in error_name:
        return "schema_mismatch"
    return "tool_error"
