"""Maple-style agent operator map — static HTML + xyflow bundle."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from murmur.domain.workflow import WorkflowPlan
from murmur.report.agent_map_projector import build_preview_demos, project_agent_map
from murmur.report.ui_theme import (
    murmur_modal_markup,
    murmur_ui_js,
    document_head,
    hud_shell_end,
    hud_shell_start,
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_BUNDLE_JS = _STATIC_DIR / "agent-map.js"
_BUNDLE_CSS = _STATIC_DIR / "agent-map.css"

_SUPPORTED_OPS = (
    "classify",
    "map",
    "reduce",
    "tournament",
    "verify",
    "filter",
    "loop",
    "generate",
    "exec",
    "rank",
    "report",
)


def render_agent_map_html(
    *,
    workflow: WorkflowPlan | None = None,
    embedded_task: str = "",
    run_dir: Path | None = None,
    preview: bool = False,
) -> str:
    if workflow is None:
        from murmur.application.workflow_planner import choose_workflow_size, plan_from_task

        task = embedded_task or "Write a cover letter for a quant trading internship."
        size = choose_workflow_size(task=task)
        workflow = plan_from_task(
            task=task,
            command="",
            attempts=size.attempts,
            max_repairs=size.max_repairs,
        )

    events_path = run_dir / "events.jsonl" if run_dir else None
    proof_path = run_dir / "proof.json" if run_dir else None
    payload = project_agent_map(
        workflow,
        events_path=events_path,
        proof_path=proof_path,
        run_dir=run_dir,
    )
    if embedded_task:
        payload["embedded_task"] = embedded_task
    payload["preview"] = preview
    if preview:
        payload["demos"] = build_preview_demos()

    payload_json = json.dumps(payload, default=str)
    bundle_js = _bundle_href()
    bundle_css = _bundle_css_href()
    task_default = embedded_task or workflow.goal
    ops_html = "\n".join(
        f'<span class="am-op-chip-static" data-op="{escape(op)}">{escape(op)}</span>'
        for op in _SUPPORTED_OPS
    )

    extra_css = r"""
.am-map-controls .am-label {
  display: block;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--txt);
  margin-bottom: 8px;
}
.am-task {
  width: 100%;
  font-family: var(--sans);
  font-size: 0.9375rem;
  line-height: 1.55;
  padding: 12px 14px;
  border: var(--hud-border);
  background: var(--panel-solid);
  color: var(--txt);
  resize: vertical;
  min-height: 88px;
}
.am-task:focus {
  outline: none;
}
.am-task:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.am-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.am-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.am-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.am-field span,
.am-toggle span {
  font: 600 0.6875rem var(--mono);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #3f3f3b;
}
.am-input {
  min-height: 38px;
  border: var(--hud-border);
  background: var(--panel-solid);
  color: var(--txt);
  font: 0.8125rem var(--sans);
  padding: 8px 10px;
}
.am-input:focus {
  outline: none;
}
.am-input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.am-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
}
.am-toggle input {
  inline-size: 18px;
  block-size: 18px;
  accent-color: var(--accent);
}
.am-map-controls .am-btn {
  border: 1px solid var(--line);
  background: var(--panel-solid);
  font: 600 0.6875rem var(--mono);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  min-height: 40px;
  padding: 0 16px;
  cursor: pointer;
  color: var(--txt);
}
.am-map-controls .am-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.am-map-controls .am-btn:focus {
  outline: none;
}
.am-map-controls .am-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.am-map-hint {
  font: 0.6875rem var(--mono);
  color: #3f3f3b;
  line-height: 1.5;
  margin-top: 12px;
  max-width: 65ch;
}
.am-stage-wrap .hud-widget__bd { padding: 16px; }
#agent-map-root { min-height: clamp(520px, 72vh, 760px); height: clamp(520px, 72vh, 760px); width: 100%; }
"""

    css_link = ""
    if bundle_css:
        css_link = f'<link rel="stylesheet" href="{escape(bundle_css)}"/>'

    head = document_head(title="Murmur — agent map", extra_css=extra_css)
    shell = hud_shell_start(
        brand="murmur",
        run_line="operator map · draggable modules · live flow playback",
        quote="Every agent lane visible. Every operator accountable.",
    )

    body = f"""
{css_link}
<section class="hud-widget am-map-controls">
  <div class="hud-widget__hd">workflow task</div>
  <div class="hud-widget__bd">
    <label class="am-label" for="am-task">Natural-language goal</label>
    <textarea id="am-task" class="am-task" rows="3">{escape(task_default)}</textarea>
    <div class="am-options">
      <label class="am-field" for="am-command">
        <span>Command</span>
        <input id="am-command" class="am-input" type="text" value="" placeholder="pytest -q"/>
      </label>
      <label class="am-field" for="am-provider">
        <span>Provider</span>
        <input id="am-provider" class="am-input" type="text" value="deepseek"/>
      </label>
      <label class="am-field" for="am-model">
        <span>Model</span>
        <input id="am-model" class="am-input" type="text" value="deepseek-v4-pro"/>
      </label>
      <label class="am-field" for="am-budget">
        <span>Budget</span>
        <input id="am-budget" class="am-input" type="number" min="0.01" step="0.01" value="0.50"/>
      </label>
      <label class="am-toggle" for="am-use-model">
        <input id="am-use-model" type="checkbox"/>
        <span>Use model</span>
      </label>
    </div>
    <div class="am-presets">
      <button type="button" class="am-btn" data-preset="writing_tournament">Writing tournament</button>
      <button type="button" class="am-btn" data-preset="coding_fix_test">Fix-test loop</button>
    </div>
    <p class="am-map-hint">
      Edit the task, then Run agents. Results and artifacts appear in the right panel when gates finish.
    </p>
  </div>
</section>

<section class="hud-widget am-stage-wrap">
  <div class="hud-widget__hd">agent operator map</div>
  <div class="hud-widget__bd">
    <div id="agent-map-root" aria-label="Murmur agent operator map"></div>
  </div>
</section>

<section class="hud-widget">
  <div class="hud-widget__hd">operators</div>
  <div class="hud-widget__bd am-ops-static">{ops_html}</div>
</section>
"""

    preset_script = """
const taskEl = document.getElementById("am-task");
function loadDemo(key) {
  const demo = (window.MURMUR_AGENT_MAP.demos || {})[key];
  if (!demo) return;
  window.dispatchEvent(new CustomEvent("murmur-agent-map-load", { detail: demo }));
}
document.querySelectorAll("[data-preset]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.preset;
    if (key === "writing_tournament") {
      taskEl.value = "Write a cover letter for a quant trading internship.";
    } else if (key === "coding_fix_test") {
      taskEl.value = "Fix the failing checkout regression test.";
    }
    loadDemo(key);
  });
});
document.querySelectorAll(".am-op-chip-static").forEach((chip) => {
  chip.addEventListener("click", () => {
    window.dispatchEvent(
      new CustomEvent("murmur-agent-map-highlight", { detail: chip.dataset.op }),
    );
  });
});
"""

    close = f"""{murmur_modal_markup()}
<script>
window.MURMUR_AGENT_MAP = {payload_json};
{murmur_ui_js()}
{preset_script}
</script>
<script src="{escape(bundle_js)}"></script>
</body>
</html>"""

    return head + "<body>" + shell + body + hud_shell_end() + close


def write_agent_map_html(
    path: Path | str,
    *,
    workflow: WorkflowPlan | None = None,
    embedded_task: str = "",
    run_dir: Path | None = None,
    preview: bool = False,
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    copy_static_assets(out.parent)
    out.write_text(
        render_agent_map_html(
            workflow=workflow,
            embedded_task=embedded_task,
            run_dir=run_dir,
            preview=preview,
        ),
        encoding="utf-8",
    )
    return out


def _bundle_href() -> str:
    if _BUNDLE_JS.is_file():
        return "static/agent-map.js"
    return "static/agent-map.js"


def _bundle_css_href() -> str | None:
    if _BUNDLE_CSS.is_file():
        return "static/agent-map.css"
    return None


def copy_static_assets(target_dir: Path) -> None:
    """Copy built JS/CSS next to HTML when run_dir is not under report/static."""

    target_dir.mkdir(parents=True, exist_ok=True)
    static_target = target_dir / "static"
    static_target.mkdir(parents=True, exist_ok=True)
    if _BUNDLE_JS.is_file():
        (static_target / "agent-map.js").write_bytes(_BUNDLE_JS.read_bytes())
    if _BUNDLE_CSS.is_file():
        (static_target / "agent-map.css").write_bytes(_BUNDLE_CSS.read_bytes())
