"""End-to-end test for the background-run + SSE streaming endpoints."""

from __future__ import annotations

import json
import threading
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

from chorus.ui.server import AgentMapPreviewHandler


def _read_sse(stream) -> list[tuple[str | None, str]]:
    events: list[tuple[str | None, str]] = []
    current: str | None = None
    data_lines: list[str] = []
    for raw in stream:
        line = raw.decode("utf-8").rstrip("\n")
        if line.startswith(":"):  # heartbeat comment
            continue
        if line == "":
            if data_lines:
                events.append((current, "\n".join(data_lines)))
                if current == "done":
                    break
            current, data_lines = None, []
            continue
        if line.startswith("event:"):
            current = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    return events


def test_run_streams_events_then_result(tmp_path) -> None:
    handler = partial(
        AgentMapPreviewHandler,
        directory=str(tmp_path),
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    try:
        body = json.dumps(
            {
                "task": "Write a short cover letter for a quant internship.",
                "run_id": "sse_test",
                "use_model": False,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/agent-map/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        started = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        run_id = started["run_id"]
        assert started["status"] == "running"

        url = f"http://127.0.0.1:{port}/api/agent-map/stream?run_id={run_id}"
        with urllib.request.urlopen(url, timeout=30) as stream:
            events = _read_sse(stream)
    finally:
        httpd.shutdown()

    kinds = [event for event, _ in events]
    assert "result" in kinds  # final payload delivered
    assert "done" in kinds
    # at least one per-line workflow event streamed (default message, event is None)
    assert any(event is None for event, _ in events)
    result_data = next(data for event, data in events if event == "result")
    payload = json.loads(result_data)
    assert payload["preview_result"]["status"] in {"pass", "fail"}


def test_stream_unknown_run_id_is_404(tmp_path) -> None:
    handler = partial(
        AgentMapPreviewHandler,
        directory=str(tmp_path),
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    try:
        url = f"http://127.0.0.1:{port}/api/agent-map/stream?run_id=does_not_exist"
        try:
            urllib.request.urlopen(url, timeout=10)
            raise AssertionError("expected HTTP 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        httpd.shutdown()
