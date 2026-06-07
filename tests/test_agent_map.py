"""Agent map projector and HTML report tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from murmur.application import artifact_contracts as artifact_contracts_module
from murmur.application.agent_map_runner import (
    AgentMapRunOptions,
    _grow_site_text,
    _live_result_from_workflow_run,
    run_agent_map_task,
)
from murmur.application.artifact_contracts import (
    RICH_SITE_MIN,
    RICH_SITE_TARGET,
    DocumentContract,
    SiteContract,
    build_document_artifact,
    build_site_artifact,
    extract_document,
    extract_index_html,
    select_artifact_contract,
    site_richness_score,
    site_trust_score,
    validate_site_artifact,
)
from murmur.application.tool_summary import RunEvidenceIndex
from murmur.application.workflow_planner import (
    _coding_fix_test,
    _writing_tournament,
    choose_workflow_size,
    plan_from_task,
    plan_task,
)
from murmur.application.workflow_runtime import (
    WorkflowNodeResult,
    WorkflowRunResult,
    _augment_prompt_with_context,
)
from murmur.benchmarks.swe.types import ModelResponse
from murmur.domain.workflow import WorkflowNode
from murmur.report.agent_map_html import render_agent_map_html, write_agent_map_html
from murmur.report.agent_map_projector import (
    build_preview_demos,
    plan_agent_map_from_task,
    project_agent_map,
)
from murmur.ui.server import load_server_env


def test_writing_tournament_expands_agents_and_converges() -> None:
    workflow = _writing_tournament("Write a cover letter.", attempts=4)
    graph = project_agent_map(workflow)["graph"]

    ops = {node["id"]: node for node in graph["nodes"] if node["kind"] == "operator"}
    agents = [node for node in graph["nodes"] if node["kind"] == "agent"]
    assert "draft" in ops
    assert ops["draft"]["scope"] == "fanout"
    assert ops["judge"]["scope"] == "combine"
    assert len(agents) == 4

    combine_edges = [
        e
        for e in graph["edges"]
        if e["target"] == "judge" and e["kind"] == "combine_in"
    ]
    assert len(combine_edges) == 4


def test_coding_fix_test_lane_and_combine_modules() -> None:
    workflow = _coding_fix_test("Fix checkout.", "pytest -q", attempts=3, max_repairs=1)
    graph = project_agent_map(workflow)["graph"]
    by_id = {node["id"]: node for node in graph["nodes"]}

    assert by_id["reproduce"]["scope"] == "shared"
    assert by_id["generate"]["scope"] == "fanout"
    assert by_id["run_tests"]["scope"] == "combine"
    assert by_id["rank"]["scope"] == "combine"

    lane_tests = [n for n in graph["nodes"] if n["id"].startswith("run_tests::agent_")]
    assert len(lane_tests) == 3
    assert all(n["scope"] == "lane" for n in lane_tests)

    into_combine = [
        e
        for e in graph["edges"]
        if e["target"] == "run_tests" and e["kind"] == "combine_in"
    ]
    assert len(into_combine) == 3


def test_fan_count_follows_workflow_params_not_hardcoded() -> None:
    workflow = _writing_tournament("Task", attempts=6)
    graph = project_agent_map(workflow)["graph"]
    agents = [n for n in graph["nodes"] if n["kind"] == "agent"]
    assert len(agents) == 6


def test_gate_playback_is_sequential() -> None:
    workflow = _writing_tournament("Task", attempts=2)
    payload = project_agent_map(workflow)
    steps = payload["playback"]
    assert steps[0]["type"] == "gate_opened"
    gate_ids = [step["gate"] for step in steps if step.get("gate")]
    assert gate_ids.index("draft") < gate_ids.index("draft::agent_1")
    assert gate_ids.index("draft::agent_2") < gate_ids.index("judge")


def test_agent_map_html_embeds_graph_and_bundle(tmp_path) -> None:
    workflow = _writing_tournament("Demo task", attempts=3)
    path = write_agent_map_html(tmp_path / "workflow.html", workflow=workflow, preview=True)
    html = path.read_text(encoding="utf-8")
    assert "MURMUR_AGENT_MAP" in html
    assert "agent-map-root" in html
    assert (tmp_path / "static" / "agent-map.js").is_file()

    payload_marker = "window.MURMUR_AGENT_MAP = "
    start = html.index(payload_marker) + len(payload_marker)
    end = html.index(";", start)
    payload = json.loads(html[start:end])
    assert payload["graph"]["nodes"]


def test_preview_demos_use_dynamic_sizing() -> None:
    demos = build_preview_demos()
    assert "writing_tournament" in demos
    assert "coding_fix_test" in demos
    assert demos["writing_tournament"]["playback"]
    assert demos["coding_fix_test"]["playback"]


def test_render_agent_map_html_no_threejs() -> None:
    html = render_agent_map_html(preview=True)
    assert "murmur-canvas" not in html


def test_agent_map_html_defaults_to_deepseek_v4_pro() -> None:
    html = render_agent_map_html(preview=True)
    assert 'id="am-provider" class="am-input" type="text" value="deepseek"' in html
    assert 'id="am-model" class="am-input" type="text" value="deepseek-v4-pro"' in html
    assert 'value="deepseek-chat"' not in html


def test_ui_server_loads_repo_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")

    loaded = load_server_env(tmp_path)

    assert loaded == tmp_path / ".env"
    assert bool(os.environ.get("DEEPSEEK_API_KEY"))


def test_story_task_routes_to_writing_tournament() -> None:
    task = "Write a story about the 2006 financial crisis."
    workflow = plan_from_task(task=task)
    assert workflow.name == "writing_tournament"


def test_plan_agent_map_from_task_uses_task_text() -> None:
    task = "Write a story about the 2006 financial crisis."
    payload = plan_agent_map_from_task(task=task)
    assert payload["embedded_task"] == task
    assert payload["workflow_name"] == "writing_tournament"
    assert payload["playback"]
    agents = [n for n in payload["graph"]["nodes"] if n["kind"] == "agent"]
    assert len(agents) == payload["workflow_size"]["attempts"]


def test_preview_result_includes_report_and_winner() -> None:
    task = "create a animation website for Caesar"
    payload = plan_agent_map_from_task(task=task)
    result = payload["preview_result"]
    assert result["winner_label"]
    assert result["report"]
    assert result["gate_log"]


def test_water_puzzle_routes_to_coding_not_writing() -> None:
    task = (
        "Imagine I am in my kitchen in Waterloo, ON, and I need to measure out exactly "
        "350 ml of water. I only have two empty containers: a 500 ml jar and a 300 ml bowl."
    )
    workflow = plan_from_task(task=task, attempts=choose_workflow_size(task=task).attempts)
    assert workflow.name == "coding_generate_and_test"
    assert "350 ml" in plan_agent_map_from_task(task=task)["preview_result"]["report"]


def test_animation_website_routes_to_competitive_coding_workflow() -> None:
    task = "create a animation website for Caesar"
    size = choose_workflow_size(task=task, budget_usd=0.50)
    workflow = plan_from_task(task=task, attempts=size.attempts)
    assert workflow.name == "site_generate_validate_repair"
    generate = next(node for node in workflow.nodes if node.id == "generate")
    assert generate.op == "map"
    assert generate.params["n"] >= 4
    assert {
        "acceptance_spec",
        "brief",
        "generate",
        "validate_site",
        "browser_verify",
        "requirement_assert",
    } <= {node.id for node in workflow.nodes}

    payload = plan_agent_map_from_task(task=task)
    agents = [n for n in payload["graph"]["nodes"] if n["kind"] == "agent"]
    ops = {n["id"]: n for n in payload["graph"]["nodes"] if n["kind"] == "operator"}
    assert len(agents) >= 4
    assert "classify" in ops
    assert "validate_site" in ops
    assert "requirement_assert" in ops
    assert "rank" in ops
    assert ops["generate"]["scope"] == "fanout"


def test_animation_website_plan_allocates_complete_artifact_budget() -> None:
    workflow = plan_from_task(task="Create a website for Elon Musk", attempts=2)
    generate = next(node for node in workflow.nodes if node.id == "generate")

    assert generate.params["max_tokens"] >= 7000
    assert "complete HTML file" in str(generate.role)


def test_hard_website_task_scales_fanout() -> None:
    from murmur.core.agent_tasks import hard_website_task

    task = hard_website_task().prompt
    size = choose_workflow_size(task=task, budget_usd=0.50)
    assert size.attempts >= 6
    assert size.max_repairs >= 1
    workflow = plan_from_task(task=task, attempts=size.attempts)
    generate = next(node for node in workflow.nodes if node.id == "generate")
    assert generate.params["n"] == size.attempts


def test_agent_map_live_run_writes_artifacts(tmp_path) -> None:
    payload = run_agent_map_task(
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
        public_run_prefix="runs",
        options=AgentMapRunOptions(
            task="Write a short cover letter for a quant trading internship.",
            run_id="ui_smoke",
        ),
    )

    result = payload["preview_result"]
    run = payload["run"]
    run_dir = tmp_path / "runs" / "ui_smoke"
    assert result["mode"] == "live"
    assert result["status"] == "pass"
    assert result["lane_previews"]
    assert (run_dir / "proof.json").is_file()
    assert (run_dir / "workflow.html").is_file()
    assert any(item["kind"] == "run_result" for item in run["artifacts"])


def test_agent_map_website_run_writes_site_preview(tmp_path) -> None:
    task = "create a animation website using three.js"
    payload = run_agent_map_task(
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
        public_run_prefix="runs",
        options=AgentMapRunOptions(
            task=task,
            run_id="site_smoke",
            use_model=False,
        ),
    )

    result = payload["preview_result"]
    run = payload["run"]
    html_path = tmp_path / "runs" / "site_smoke" / "site" / "index.html"
    html = html_path.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["summary"] == "Generated website preview: site/index.html"
    assert result["winner_id"] == "generate_1"
    assert any(item["id"] == "generate_1" and item["selected"] for item in result["lane_previews"])
    assert result["primary_artifact"]["kind"] == "site_preview"
    assert result["validation_summary"]["passed"] is True
    assert "three.module.js" in html
    assert "<canvas id=\"scene\"" in html
    assert any(item["kind"] == "site_preview" for item in run["artifacts"])
    proof_path = tmp_path / "runs" / "site_smoke" / "proof.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["budget"]["tool_calls"] > 0
    assert proof["tool_summary"]["total"] > 0
    assert proof["trust_score"]["score"] >= 50


def test_site_extractor_rejects_truncated_html() -> None:
    truncated = "```html\n<!doctype html><html><head><title>x</title></head><body><main>"
    complete = "```html\n<!doctype html><html><body><main>ok</main></body></html>\n```"

    assert extract_index_html(truncated) == ""
    assert extract_index_html(complete).startswith("<!doctype html>")


def test_site_artifact_contract_fails_truncated_html(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")

    result = build_site_artifact(
        run_dir=run_dir,
        run_id="site_fail",
        goal="Create a website for Elon Musk",
        candidate_texts=[
            "```html\n<!doctype html><html><head><title>x</title></head><body><main>"
        ],
        events_path=events_path,
    )
    summary = RunEvidenceIndex.from_paths((events_path,)).tool_summary()

    assert result.written is False
    assert result.validation.passed is False
    assert "missing_complete_site_artifact" in result.validation.risk_flags
    assert not (run_dir / "site" / "index.html").exists()
    assert (run_dir / "site_validation.json").is_file()
    assert summary["failed"] == 1


def test_select_artifact_contract_routes_by_task() -> None:
    assert isinstance(select_artifact_contract("Create a website for Elon Musk"), SiteContract)
    assert isinstance(
        select_artifact_contract("Write a cover letter for a quant role"),
        DocumentContract,
    )
    # Site wins over document when a task mentions both surfaces.
    assert isinstance(
        select_artifact_contract("Write a blog post as a single-page web app"),
        SiteContract,
    )
    assert select_artifact_contract("Refactor the payment service") is None


def test_extract_document_unwraps_fence_and_keeps_truncation() -> None:
    fenced = "```markdown\nDear team,\n\nThank you.\n```"
    truncated = "```markdown\nDear team, I am writing because"
    plain = "Dear team,\n\nThank you for the opportunity."

    assert extract_document(fenced) == "Dear team,\n\nThank you."
    assert "```" in extract_document(truncated)
    assert extract_document(plain) == plain
    assert extract_document("   ") == ""


def test_document_artifact_contract_passes_complete_text(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    body = (
        "Dear hiring team,\n\nI am excited to apply for the quant internship. "
        "My background in probability and systems makes me a strong fit.\n\nSincerely, Caesar"
    )

    result = build_document_artifact(
        run_dir=run_dir,
        run_id="doc_ok",
        goal="Write a cover letter",
        candidate_texts=[f"```\n{body}\n```"],
        events_path=events_path,
    )
    summary = RunEvidenceIndex.from_paths((events_path,)).tool_summary()

    assert result.written is True
    assert result.validation.passed is True
    assert result.primary_artifact == {
        "kind": "document",
        "path": "document.md",
        "href": "document.md",
        "description": "generated document",
    }
    assert (run_dir / "document.md").read_text(encoding="utf-8") == body
    assert (run_dir / "document_validation.json").is_file()
    assert summary["succeeded"] == 3


def test_document_artifact_contract_fails_truncated_text(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")

    result = build_document_artifact(
        run_dir=run_dir,
        run_id="doc_fail",
        goal="Write a cover letter",
        candidate_texts=["```markdown\nDear team, I am writing because"],
        events_path=events_path,
    )

    assert result.written is False
    assert result.validation.passed is False
    assert "unterminated_code_fence" in result.validation.risk_flags
    assert (run_dir / "document_validation.json").is_file()


def test_document_artifact_contract_fails_empty_text(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")

    result = build_document_artifact(
        run_dir=run_dir,
        run_id="doc_empty",
        goal="Write a cover letter",
        candidate_texts=["", "   "],
        events_path=events_path,
    )

    assert result.written is False
    assert "missing_document_artifact" in result.validation.risk_flags
    assert not (run_dir / "document.md").exists()


def test_agent_map_writing_run_writes_document_artifact(tmp_path) -> None:
    payload = run_agent_map_task(
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
        public_run_prefix="runs",
        options=AgentMapRunOptions(
            task="Write a short cover letter for a quant trading internship.",
            run_id="doc_run",
            use_model=False,
        ),
    )

    result = payload["preview_result"]
    run = payload["run"]
    run_dir = tmp_path / "runs" / "doc_run"

    assert result["status"] == "pass"
    assert result["summary"] == "Generated document: document.md"
    assert result["primary_artifact"]["kind"] == "document"
    assert result["validation_summary"]["passed"] is True
    assert result["document_preview"]
    assert (run_dir / "document.md").is_file()
    assert any(item["kind"] == "document" for item in run["artifacts"])
    proof = json.loads((run_dir / "proof.json").read_text(encoding="utf-8"))
    assert proof["trust_score"]["score"] >= 50
    assert proof["tool_summary"]["total"] > 0


_RICH_SITE_HTML = (
    "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
    "<title>Cosmic Portal</title>\n"
    "<script src=\"https://cdn.tailwindcss.com\"></script>\n"
    "<link href=\"https://fonts.googleapis.com/css2?family=Inter\" rel=\"stylesheet\">\n"
    "<style>\n:root{--accent:#e8192a;}\n"
    "@keyframes float{from{transform:none;}to{transform:translateY(-10px);}}\n"
    ".card{transition:all .3s ease;}\n"
    "@media (max-width:600px){.grid{display:block;}}\n</style>\n</head>\n"
    "<body data-rich-marker=\"yes\">\n"
    "<header id=\"top\"><nav id=\"nav\"><a href=\"#features\">Features</a>"
    "<a href=\"#story\">Story</a></nav></header>\n"
    "<main>\n"
    "<section id=\"hero\"><h1>Engineering the Future</h1>"
    "<button id=\"explore\">Explore</button>"
    "<canvas id=\"scene\"></canvas></section>\n"
    "<section id=\"features\"><h2>Ventures</h2>"
    "<article><h3>Rockets</h3><p>" + ("Reusable orbital systems. " * 12) + "</p></article>"
    "<article><h3>Energy</h3><p>" + ("Sustainable batteries at scale. " * 12) + "</p></article>"
    "</section>\n"
    "<section id=\"story\"><h2>Timeline</h2><svg viewBox=\"0 0 10 10\"></svg>"
    "<form><input id=\"q\" type=\"text\"><button type=\"submit\">Ask</button></form>"
    "<p>" + ("A chronology of milestones. " * 12) + "</p></section>\n"
    "</main>\n"
    "<footer id=\"foot\"><p>Archive</p></footer>\n"
    "<script>\n"
    "document.getElementById('explore').addEventListener('click',()=>{});\n"
    "window.addEventListener('scroll',()=>{});\n"
    "function frame(){requestAnimationFrame(frame);}requestAnimationFrame(frame);\n"
    "</script>\n</body>\n</html>"
)


def _thin_site_html(marker: str) -> str:
    return (
        "<!doctype html><html><head><title>Thin</title></head><body><main>"
        f"<h1>{marker}</h1><p>" + ("plain copy " * 60) + "</p></main></body></html>"
    )


def test_site_richness_score_orders_rich_above_thin() -> None:
    rich = site_richness_score(_RICH_SITE_HTML)
    thin = site_richness_score(_thin_site_html("Thin"))

    assert rich["score"] >= RICH_SITE_TARGET
    assert thin["score"] < RICH_SITE_MIN
    assert rich["score"] > thin["score"]
    assert rich["signals"]["interactivity"] > 0


def test_build_site_artifact_selects_richest_candidate(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")

    result = build_site_artifact(
        run_dir=run_dir,
        run_id="rich_pick",
        goal="Create a website for Elon Musk",
        candidate_texts=[_thin_site_html("First"), _RICH_SITE_HTML],
        events_path=events_path,
    )
    written = (run_dir / "site" / "index.html").read_text(encoding="utf-8")

    assert result.validation.passed is True
    assert 'data-rich-marker="yes"' in written
    assert result.validation.details["richness"]["score"] >= RICH_SITE_TARGET


def test_site_artifact_flags_thin_site(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")

    result = build_site_artifact(
        run_dir=run_dir,
        run_id="thin_flag",
        goal="Create a website",
        candidate_texts=[_thin_site_html("Thin")],
        events_path=events_path,
    )

    assert result.validation.passed is True
    assert "thin_site" in result.validation.risk_flags
    assert result.validation.details["richness"]["score"] < RICH_SITE_MIN


def _stub_browser_payload(
    *,
    body: str = "visible page",
    console_errors: list[str] | None = None,
    large_blank_panels: int = 0,
    buttons: int = 0,
    inputs: int = 0,
    selects: int = 0,
    table_rows: int = 0,
    trade_changed: bool = False,
    ticks_changed: bool = False,
) -> dict[str, object]:
    errors = console_errors or []
    return {
        "checks": {
            "browser_rendered": True,
            "dom_visible": True,
            "console_clean": not errors,
            "canvas_nonblank": True,
        },
        "risk_flags": ["console_errors"] if errors else [],
        "console_errors": errors,
        "desktop": {
            "bodyText": body,
            "bodyTextLength": len(body),
            "elementCount": 30,
            "canvasCount": 1,
            "canvasNonBlank": True,
            "buttonCount": buttons,
            "inputCount": inputs,
            "selectCount": selects,
            "tableRowCount": table_rows,
            "largeBlankPanels": large_blank_panels,
        },
        "mobile": {
            "bodyText": body,
            "bodyTextLength": len(body),
            "elementCount": 30,
            "canvasCount": 1,
            "canvasNonBlank": True,
            "buttonCount": buttons,
            "inputCount": inputs,
            "selectCount": selects,
            "tableRowCount": table_rows,
            "largeBlankPanels": large_blank_panels,
        },
        "interactions": {
            "tradeStateChanged": trade_changed,
            "marketTicksChanged": ticks_changed,
        },
    }


def _write_site_for_validation(tmp_path, html: str) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "site").mkdir(parents=True)
    (run_dir / "site" / "index.html").write_text(html, encoding="utf-8")
    return run_dir


def test_site_validation_fails_console_errors(tmp_path, monkeypatch) -> None:
    html = (
        "<!doctype html><html><body><main><h1>Trading App</h1>"
        "<canvas></canvas><script>throw new Error('boom')</script></main></body></html>"
    )
    run_dir = _write_site_for_validation(tmp_path, html)
    monkeypatch.setattr(
        artifact_contracts_module,
        "_browser_render_check",
        lambda **_: _stub_browser_payload(
            body="Trading App",
            console_errors=["LightweightCharts is not defined"],
        ),
    )

    validation = validate_site_artifact(
        html=html,
        goal="Create an interactive trading website",
        run_dir=run_dir,
        run_id="console_fail",
    )

    assert validation.passed is False
    assert "console_errors" in validation.risk_flags
    trust = site_trust_score(validation, {"total": 3})
    assert trust["score"] < 70


def test_trading_shell_fails_missing_domain_requirements(tmp_path, monkeypatch) -> None:
    html = (
        "<!doctype html><html><body><main>"
        "<h1>OrderFlow Simulator</h1><section>Order Book DOM</section>"
        "<section>Trade Ticket <button>Buy</button><button>Sell</button></section>"
        "<section>Volume Analysis</section><canvas></canvas>"
        "<script>setInterval(()=>{}, 1000)</script></main></body></html>"
    )
    run_dir = _write_site_for_validation(tmp_path, html)
    monkeypatch.setattr(
        artifact_contracts_module,
        "_browser_render_check",
        lambda **_: _stub_browser_payload(
            body="OrderFlow Simulator Order Book DOM Trade Ticket Buy Sell Volume Analysis",
            large_blank_panels=2,
            buttons=2,
        ),
    )

    validation = validate_site_artifact(
        html=html,
        goal=(
            "Generate an orderflow quantitative trading simulator website "
            "with orderbook and ticket"
        ),
        run_dir=run_dir,
        run_id="trading_shell",
    )

    assert validation.passed is False
    assert "blank_large_panel" in validation.risk_flags
    assert "missing_orderbook_rows" in validation.risk_flags
    assert "missing_trade_ticket_interaction" in validation.risk_flags
    failed = validation.details["acceptance"]["failed_requirements"]
    assert "orderbook_rows" in failed
    assert "ticket_interaction_updates_state" in failed


def test_real_data_request_requires_verified_provenance(tmp_path, monkeypatch) -> None:
    html = (
        "<!doctype html><html><body><main><h1>Market Simulator</h1>"
        "<p>Simulated live data for training.</p><canvas></canvas>"
        "<script>setInterval(()=>{}, 1000)</script></main></body></html>"
    )
    run_dir = _write_site_for_validation(tmp_path, html)
    monkeypatch.setattr(
        artifact_contracts_module,
        "_browser_render_check",
        lambda **_: _stub_browser_payload(
            body="Market Simulator simulated live data",
            trade_changed=True,
            ticks_changed=True,
        ),
    )

    validation = validate_site_artifact(
        html=html,
        goal="Create a trading simulator website with real data",
        run_dir=run_dir,
        run_id="real_data_fail",
    )

    assert validation.passed is False
    assert "unproven_real_data" in validation.risk_flags
    assert "real_data_provenance" in validation.details["acceptance"]["failed_requirements"]


def test_site_plan_includes_creative_brief_and_threads_context() -> None:
    workflow = plan_from_task(task="Create a website for Elon Musk", attempts=2)
    brief = next(node for node in workflow.nodes if node.id == "brief")
    generate = next(node for node in workflow.nodes if node.id == "generate")

    assert brief.op == "generate"
    assert "BUILD BRIEF" in str(brief.role)
    assert "brief" in generate.dependencies
    assert generate.params["context_nodes"] == ("brief",)
    assert generate.params["n"] >= 4


def test_augment_prompt_with_context_prepends_brief() -> None:
    brief = WorkflowNodeResult(
        node_id="brief",
        op="generate",
        status="completed",
        passed=True,
        output="THEME: cosmic red",
    )
    context = SimpleNamespace(results={"brief": brief})
    node = WorkflowNode(id="generate", op="map", params={"context_nodes": ("brief",)})

    augmented = _augment_prompt_with_context("Create a site", node, context)
    assert augmented.startswith("CREATIVE BRIEF:")
    assert "THEME: cosmic red" in augmented
    assert augmented.rstrip().endswith("Create a site")

    bare = WorkflowNode(id="generate", op="map", params={})
    assert _augment_prompt_with_context("Create a site", bare, context) == "Create a site"


def test_grow_site_text_assembles_truncated_html(tmp_path) -> None:
    result = WorkflowRunResult(
        run_id="grow",
        status="fail",
        run_dir=tmp_path,
        node_results=(),
        proof={},
    )
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")

    class _StubModel:
        model = "stub"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, *, system, user, seed, max_tokens):
            self.calls += 1
            return SimpleNamespace(
                text="</main></body></html>\n```",
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.0,
            )

    base = "```html\n<!doctype html><html><head><title>x</title></head><body><main>partial"
    model = _StubModel()
    text = _grow_site_text(
        result=result,
        model=model,
        goal="Create a website",
        base=base,
        seed=1,
        artifact_name="continuation",
    )

    assert extract_index_html(text)
    assert model.calls == 1
    assert (tmp_path / "nodes" / "site_artifact" / "artifacts" / "continuation_1.txt").is_file()


def _model_plan_json(goal: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "schema_version": 1,
            "name": "site_build",
            "goal": goal,
            "description": "model-authored",
            "budget": {"max_cost_usd": 0.5},
            "nodes": [
                {"id": "classify", "op": "classify", "params": {"task": goal}},
                {
                    "id": "generate",
                    "op": "map",
                    "inputs": ["classify"],
                    "params": {"n": 2, "prompt": goal},
                },
                {"id": "rank", "op": "rank", "inputs": ["generate"]},
                {"id": "report", "op": "report", "inputs": ["rank"]},
            ],
        }
    )


class _PlannerStubModel:
    """Stub model: writes a workflow IR for planning, rich HTML for generation."""

    model = "stub"

    def __init__(self, goal: str = "Create a website for Ada Lovelace") -> None:
        self.goal = goal

    def complete(self, *, system, user, seed, max_tokens=2400):
        if "workflow planner" in system.lower():
            text = _model_plan_json(self.goal)
        elif "complete HTML file" in system:
            text = _RICH_SITE_HTML
        else:
            text = "THEME: archival cyan. STRUCTURE: hero, work, legacy, footer."
        return ModelResponse(text=text, input_tokens=10, output_tokens=50, cost_usd=0.0)


def test_plan_task_uses_model_when_available_for_non_site_task() -> None:
    outcome = plan_task(task="Plan a data pipeline", model=_PlannerStubModel())

    assert outcome.mode == "model"
    assert outcome.workflow.name == "site_build"
    generate = next(node for node in outcome.workflow.nodes if node.id == "generate")
    assert generate.role.strip()  # back-filled from the role library


def test_plan_task_falls_back_on_invalid_model_plan() -> None:
    class _BadModel:
        model = "bad"

        def complete(self, *, system, user, seed, max_tokens=2400):
            return ModelResponse(text="not a workflow", cost_usd=0.0)

    outcome = plan_task(task="Write a cover letter", model=_BadModel())

    assert outcome.mode == "template"
    assert outcome.reason
    assert outcome.workflow.validate() == []
    assert outcome.workflow.name == "writing_tournament"


def test_plan_task_without_model_uses_template() -> None:
    outcome = plan_task(task="Write a cover letter")

    assert outcome.mode == "template"
    assert outcome.reason == "no model configured"
    assert outcome.workflow.name == "writing_tournament"


def test_plan_task_forced_template_ignores_model() -> None:
    outcome = plan_task(
        task="Create a website",
        model=_PlannerStubModel(),
        template="writing_tournament",
    )

    assert outcome.mode == "template"
    assert outcome.workflow.name == "writing_tournament"


def test_agent_map_records_model_planner_provenance(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "murmur.application.agent_map_runner._build_model",
        lambda options: _PlannerStubModel(goal=options.task),
    )
    payload = run_agent_map_task(
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
        public_run_prefix="runs",
        options=AgentMapRunOptions(
            task="Create a website for Ada Lovelace",
            run_id="model_plan",
            use_model=True,
        ),
    )
    run_dir = tmp_path / "runs" / "model_plan"

    assert payload["planner"]["mode"] == "template"
    assert "site pipeline" in payload["planner"]["reason"]
    assert payload["preview_result"]["planner"]["mode"] == "template"
    proof = json.loads((run_dir / "proof.json").read_text(encoding="utf-8"))
    assert proof["planner"]["mode"] == "template"
    assert (run_dir / "site" / "index.html").is_file()
    assert payload["preview_result"]["status"] == "pass"


def test_deliverable_routing_program_vs_app() -> None:
    # Explicit code -> coding workflow (not writing).
    program = plan_from_task(task="Build a command-line CSV parser in python", attempts=2)
    assert program.name == "coding_generate_and_test"
    assert program.name != "writing_tournament"
    # An interactive trading chart app -> the site pipeline, not a Python file or prose.
    app = plan_from_task(
        task="a crypto trading simulator with a live candlestick chart", attempts=2
    )
    assert app.name == "site_generate_validate_repair"


_PROGRAM_CODE = (
    "```python\n"
    "import statistics\n\n\n"
    "def simulate(prices):\n"
    '    """Tiny footprint-style trading simulator."""\n'
    "    pnl = 0.0\n"
    "    for prev, cur in zip(prices, prices[1:]):\n"
    "        pnl += cur - prev\n"
    "    return pnl\n\n\n"
    'if __name__ == "__main__":\n'
    "    print(simulate([100, 101, 102, 100]))\n"
    "```"
)


def _program_plan_json(goal: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "schema_version": 1,
            "name": "program_build",
            "goal": goal,
            "description": "model-authored",
            "budget": {"max_cost_usd": 0.5},
            "nodes": [
                {"id": "classify", "op": "classify", "params": {"task": goal}},
                {
                    "id": "generate",
                    "op": "map",
                    "inputs": ["classify"],
                    "params": {"n": 2, "prompt": goal},
                },
                {"id": "rank", "op": "rank", "inputs": ["generate"]},
                {"id": "report", "op": "report", "inputs": ["rank"]},
            ],
        }
    )


class _ProgramStubModel:
    model = "stub"

    def __init__(self, goal: str) -> None:
        self.goal = goal

    def complete(self, *, system, user, seed, max_tokens=2048):
        if "workflow planner" in system.lower():
            text = _program_plan_json(self.goal)
        else:
            text = _PROGRAM_CODE
        return ModelResponse(text=text, input_tokens=10, output_tokens=50, cost_usd=0.0)


def test_agent_map_program_run_writes_program_artifact(tmp_path, monkeypatch) -> None:
    task = "Build a command-line PnL calculator in python"
    monkeypatch.setattr(
        "murmur.application.agent_map_runner._build_model",
        lambda options: _ProgramStubModel(goal=options.task),
    )
    payload = run_agent_map_task(
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
        public_run_prefix="runs",
        options=AgentMapRunOptions(task=task, run_id="prog", use_model=True),
    )
    run_dir = tmp_path / "runs" / "prog"
    result = payload["preview_result"]

    assert result["status"] == "pass"
    assert result["primary_artifact"]["kind"] == "program"
    assert (run_dir / "program" / "main.py").is_file()
    assert "def simulate" in result["program_preview"]
    assert any(item["kind"] == "program" for item in payload["run"]["artifacts"])


def test_agent_map_program_run_offline_skips_program_artifact(tmp_path) -> None:
    payload = run_agent_map_task(
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
        public_run_prefix="runs",
        options=AgentMapRunOptions(
            task="Build a command-line PnL calculator in python",
            run_id="prog_offline",
            use_model=False,
        ),
    )
    run_dir = tmp_path / "runs" / "prog_offline"

    # No deterministic code generator offline: the program contract is skipped, not failed.
    assert not (run_dir / "program").exists()
    assert payload["preview_result"]["primary_artifact"] is None


def test_plan_task_captures_planning_time_and_usage() -> None:
    class _ReasoningPlanner:
        model = "stub"

        def complete(self, *, system, user, seed, max_tokens=6000):
            return ModelResponse(
                text=_model_plan_json("Build a CLI tool in python"),
                input_tokens=20,
                output_tokens=40,
                cost_usd=0.001,
                reasoning="I will fan out candidates then rank the best.",
            )

    outcome = plan_task(task="Build a CLI tool in python", model=_ReasoningPlanner())

    assert outcome.mode == "model"
    assert outcome.model_calls == 1
    assert outcome.output_tokens == 40
    assert outcome.duration_ms >= 0
    assert "fan out" in outcome.reasoning
    meta = outcome.meta()
    assert meta["model_calls"] == 1
    assert "reasoning" in meta and "duration_ms" in meta


def test_agent_map_run_records_timeline_and_planning(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "murmur.application.agent_map_runner._build_model",
        lambda options: _ProgramStubModel(goal=options.task),
    )
    payload = run_agent_map_task(
        repo_root=tmp_path,
        out_root=tmp_path / "runs",
        public_run_prefix="runs",
        options=AgentMapRunOptions(
            task="Build a command-line PnL calculator in python",
            run_id="tl",
            use_model=True,
        ),
    )
    result = payload["preview_result"]
    timeline = result["timeline"]

    assert timeline
    assert timeline[0]["kind"] == "planning"
    assert timeline[0]["status"] == "pass"
    assert any(row["kind"] == "node" for row in timeline)
    assert result["planner"]["mode"] == "model"
    proof = json.loads((tmp_path / "runs" / "tl" / "proof.json").read_text(encoding="utf-8"))
    assert proof["budget"]["model_calls"] >= 2  # planning call + generation call(s)
    assert "planning_ms" in proof["budget"]


def test_agent_map_live_result_surfaces_failed_node(tmp_path) -> None:
    result = WorkflowRunResult(
        run_id="missing_key",
        status="fail",
        run_dir=tmp_path,
        node_results=(
            WorkflowNodeResult(
                node_id="generate",
                op="map",
                status="failed",
                passed=False,
                error="DEEPSEEK_API_KEY is not set",
                quarantined=True,
            ),
            WorkflowNodeResult(
                node_id="report",
                op="report",
                status="skipped",
                passed=False,
                skipped_reason="dependency generate did not pass",
                quarantined=True,
            ),
        ),
        proof={
            "workflow": {"name": "coding_generate_and_test"},
            "budget": {"model_calls": 0, "tool_calls": 0, "cost_usd": 0.0},
            "model_retries": 3,
        },
    )

    payload = _live_result_from_workflow_run(result, artifact_index=[])

    assert payload["summary"] == "DEEPSEEK_API_KEY is not set"
    assert payload["winner_label"] == "generate failed"
    assert "credentials are missing" in payload["note"]
