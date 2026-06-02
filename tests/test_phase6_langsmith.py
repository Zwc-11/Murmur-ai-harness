"""Phase 6 LangSmith export tests.

Verify the LangSmith OTLP contract (endpoint + headers), the project URL, and that
the event->span->emit pipeline LangSmith receives produces balanced ``gen_ai.*``
spans -- all without a live LangSmith account or the network.
"""

from __future__ import annotations

import asyncio
import importlib.util

from chorus.adapters.agents.stochastic import stochastic_agent_factory, stochastic_tools
from chorus.adapters.storage.memory import InMemoryEventStore
from chorus.adapters.trace.memory import InMemoryTraceCollector
from chorus.adapters.trace.otlp import (
    _BACKEND_DEFAULTS,
    LANGSMITH_APP_URL,
    _langsmith_headers,
    build_otlp_trace_port,
    langsmith_project_url,
)
from chorus.core.conductor import RunConductor
from chorus.core.types import TaskSpec
from chorus.trace.emit import emit_traces
from chorus.trace.mapper import events_to_traces

TASK = TaskSpec(
    task_id="demo.echo_uppercase",
    prompt="hello chorus",
    expected_output="HELLO CHORUS",
)


def test_langsmith_endpoint_matches_the_otel_contract() -> None:
    endpoint = _BACKEND_DEFAULTS["langsmith"]
    assert endpoint.startswith("https://api.smith.langchain.com")
    assert endpoint.endswith("/otel/v1/traces")


def test_langsmith_headers_carry_key_and_project(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "my-project")
    headers = _langsmith_headers()
    assert headers["x-api-key"] == "ls-test-key"
    assert headers["Langsmith-Project"] == "my-project"


def test_langsmith_headers_omit_key_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_PROJECT", "p")
    headers = _langsmith_headers()
    assert "x-api-key" not in headers
    assert headers["Langsmith-Project"] == "p"


def test_project_url_is_well_formed_and_encoded() -> None:
    url = langsmith_project_url("my proj")
    assert url.startswith(LANGSMITH_APP_URL)
    assert "my%20proj" in url  # the project name is URL-encoded


def test_export_pipeline_emits_balanced_gen_ai_spans() -> None:
    # The exact path LangSmith receives: events -> traces -> emit -> TracePort.
    store = InMemoryEventStore()
    conductor = RunConductor(
        agent_factory=stochastic_agent_factory(success_rate=1.0, error_rate=0.0, base_seed=1),
        storage=store,
        tools=stochastic_tools(),
    )
    asyncio.run(conductor.run(TASK, n=1))
    events = list(asyncio.run(store.read_events()))

    collector = InMemoryTraceCollector()
    emit_traces(events_to_traces(events), collector)

    assert collector.flushed
    assert collector.depth_balanced
    assert collector.spans[0].name == "agent.run"
    model_spans = [span for span in collector.spans if span.kind == "model"]
    assert model_spans
    assert model_spans[0].attributes["gen_ai.operation.name"] == "chat"


def test_build_langsmith_port_constructs_when_otel_present() -> None:
    if importlib.util.find_spec("opentelemetry") is None:  # pragma: no cover - extra absent
        return  # the [otel] extra is not installed; construction is a Tier-B/live concern
    port = build_otlp_trace_port(backend="langsmith")
    # Buffer a span without flushing -- exercises construction with no network.
    port.start_span("agent.run", kind="run", attrs={"gen_ai.operation.name": "invoke_agent"})
    port.set_status("ok")
    port.end_span()
