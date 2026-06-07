"""Local HTTP server for the Murmur agent-map workbench."""

from __future__ import annotations

import argparse
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from murmur.application.agent_map_runner import (
    AgentMapRunOptions,
    _safe_run_id,
    run_agent_map_task,
)
from murmur.config import load_project_env
from murmur.report.agent_map_projector import plan_agent_map_from_task

# Background-run registry: run_id -> {"status": running|done|error, "payload": ..., "error": ...}.
# The run executes on a worker thread; the SSE endpoint tails the run's events.jsonl live.
_RUN_REGISTRY: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()
_STREAM_TIMEOUT_S = 1200.0


def serve_preview_dir(
    *,
    directory: Path,
    port: int,
    repo_root: Path = Path("."),
    host: str = "127.0.0.1",
) -> None:
    """Serve a static preview directory plus agent-map JSON endpoints."""

    resolved_dir = directory.resolve()
    resolved_repo = repo_root.resolve()
    if not resolved_dir.is_dir():
        raise RuntimeError(f"{resolved_dir} does not exist")
    load_server_env(resolved_repo)

    handler = partial(
        AgentMapPreviewHandler,
        directory=str(resolved_dir),
        repo_root=resolved_repo,
        out_root=resolved_dir / "runs",
    )
    print(f"Serving {resolved_dir} at http://{host}:{port}/", flush=True)
    print(f"Open http://{host}:{port}/agent-map.html for the operator map", flush=True)
    with ThreadingHTTPServer((host, port), handler) as httpd:
        httpd.serve_forever()


def load_server_env(repo_root: Path) -> Path | None:
    """Load project `.env` for direct `python -m murmur.ui.server` launches."""

    return load_project_env(start=repo_root)


class AgentMapPreviewHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args: Any,
        repo_root: Path,
        out_root: Path,
        **kwargs: Any,
    ) -> None:
        self.repo_root = repo_root
        self.out_root = out_root
        super().__init__(*args, **kwargs)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/agent-map/run":
            self._start_background_run()
            return
        if self.path not in {"/api/agent-map/plan", "/api/agent-map/run-blocking"}:
            self.send_error(404, "not found")
            return
        try:
            body = self._read_json_body()
            task = str(body.get("task", "")).strip()
            if not task:
                self.send_error(400, "task is required")
                return
            payload = self._run_payload(body, task)
            self._send_json(payload)
        except Exception as exc:  # noqa: BLE001 - local UI should expose runtime failure.
            self.send_error(500, str(exc))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/agent-map/stream":
            run_id = (parse_qs(parsed.query).get("run_id") or [""])[0]
            self._stream_run(run_id)
            return
        super().do_GET()

    def _start_background_run(self) -> None:
        try:
            body = self._read_json_body()
        except Exception as exc:  # noqa: BLE001 - surface a malformed request body.
            self.send_error(400, str(exc))
            return
        task = str(body.get("task", "")).strip()
        if not task:
            self.send_error(400, "task is required")
            return
        run_id = _safe_run_id(str(body.get("run_id", "")))
        options = self._build_options(body, task, run_id)
        with _REGISTRY_LOCK:
            _RUN_REGISTRY[run_id] = {"status": "running", "payload": None, "error": None}
        worker = threading.Thread(
            target=_execute_run,
            args=(run_id, options, self.repo_root, self.out_root),
            daemon=True,
        )
        worker.start()
        self._send_json({"run_id": run_id, "status": "running"})

    def _stream_run(self, run_id: str) -> None:
        safe = _safe_run_id(run_id)
        if not _registry_entry(safe):
            self.send_error(404, "unknown run_id")
            return
        events_path = self.out_root / safe / "events.jsonl"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        offset = 0
        deadline = time.time() + _STREAM_TIMEOUT_S
        try:
            while time.time() < deadline:
                sent = False
                if events_path.is_file():
                    size = events_path.stat().st_size
                    if size < offset:  # file was truncated/reset
                        offset = 0
                    if size > offset:
                        with events_path.open("r", encoding="utf-8") as handle:
                            handle.seek(offset)
                            chunk = handle.read()
                            offset = handle.tell()
                        for line in chunk.splitlines():
                            if line.strip():
                                self._sse(data=line)
                                sent = True
                entry = _registry_entry(safe)
                status = entry.get("status") if entry else "error"
                if status in {"done", "error"} and not sent:
                    if status == "done" and entry and entry.get("payload") is not None:
                        self._sse(event="result", data=json.dumps(entry["payload"], default=str))
                    else:
                        message = (entry or {}).get("error") or "run failed"
                        self._sse(event="run_error", data=json.dumps({"error": message}))
                    self._sse(event="done", data="{}")
                    return
                if not sent:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _sse(self, *, data: str, event: str | None = None) -> None:
        buffer = f"event: {event}\n" if event else ""
        buffer += f"data: {data}\n\n"
        self.wfile.write(buffer.encode("utf-8"))
        self.wfile.flush()

    def _build_options(self, body: dict[str, Any], task: str, run_id: str) -> AgentMapRunOptions:
        return AgentMapRunOptions(
            task=task,
            command=str(body.get("command", "")),
            template=str(body.get("template", "auto")),
            budget_usd=float(body.get("budget_usd", 0.50)),
            provider=str(body.get("provider", "")),
            model=str(body.get("model", "")),
            use_model=bool(body.get("use_model", False)),
            agent=str(body.get("agent", "scripted")),
            concurrency=int(body.get("concurrency", 1)),
            attempt_concurrency=int(body.get("attempt_concurrency", 1)),
            run_id=run_id,
        )

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("request body must be a JSON object")
        return payload

    def _run_payload(self, body: dict[str, Any], task: str) -> dict[str, Any]:
        if self.path == "/api/agent-map/run-blocking":
            return run_agent_map_task(
                repo_root=self.repo_root,
                out_root=self.out_root,
                public_run_prefix="runs",
                options=self._build_options(body, task, _safe_run_id(str(body.get("run_id", "")))),
            )
        return plan_agent_map_from_task(
            task=task,
            command=str(body.get("command", "")),
            template=str(body.get("template", "auto")),
            budget_usd=float(body.get("budget_usd", 0.50)),
        )

    def _send_json(self, payload: dict[str, Any]) -> None:
        out = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def _registry_entry(run_id: str) -> dict[str, Any] | None:
    with _REGISTRY_LOCK:
        entry = _RUN_REGISTRY.get(run_id)
        return dict(entry) if entry else None


def _execute_run(
    run_id: str,
    options: AgentMapRunOptions,
    repo_root: Path,
    out_root: Path,
) -> None:
    try:
        payload = run_agent_map_task(
            repo_root=repo_root,
            out_root=out_root,
            public_run_prefix="runs",
            options=options,
        )
        with _REGISTRY_LOCK:
            _RUN_REGISTRY[run_id] = {"status": "done", "payload": payload, "error": None}
    except Exception as exc:  # noqa: BLE001 - background run errors are surfaced over SSE.
        with _REGISTRY_LOCK:
            _RUN_REGISTRY[run_id] = {"status": "error", "payload": None, "error": str(exc)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the Murmur local workbench.")
    parser.add_argument("--dir", type=Path, default=Path(".murmur/preview"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve_preview_dir(
        directory=args.dir,
        repo_root=args.repo_root,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
