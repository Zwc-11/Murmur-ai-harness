"""Static run workbench for proof artifacts."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from murmur.domain.proof import ProofPackage
from murmur.report.ui_theme import document_close, document_head, hud_shell_start


def write_workbench_html(path: Path | str, *, proof: ProofPackage) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_workbench_html(proof=proof), encoding="utf-8")
    return out


def render_workbench_html(*, proof: ProofPackage) -> str:
    payload = proof.to_dict()
    payload_json = json.dumps(payload, default=str)
    pretty_payload = escape(json.dumps(payload, indent=2, default=str))
    trust = proof.trust_score.score if proof.trust_score else "n/a"
    level = proof.trust_score.level if proof.trust_score else "unscored"
    attempts = len(proof.attempts)
    artifacts = "\n".join(
        f"<li><a href=\"{escape(item['path'])}\">{escape(item['kind'])}</a>"
        f" <span>{escape(item.get('description', ''))}</span></li>"
        for item in proof.artifact_index
    )
    if not artifacts:
        artifacts = "<li>artifact index will be written at run finish</li>"

    extra_css = r"""
.wb-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
.wb-score { font: 600 42px/1 var(--mono); color: var(--accent); margin: 0; }
.wb-list { margin: 0; padding-left: 18px; line-height: 1.7; }
.wb-list span { color: var(--muted); }
.wb-pre {
  max-height: 46vh;
  overflow: auto;
  white-space: pre-wrap;
  font: 12px/1.45 var(--mono);
  border: var(--hud-border);
  background: var(--panel-solid);
  padding: 12px;
}
"""
    script = f"""
window.MURMUR_PROOF = {payload_json};
"""
    head = document_head(title=f"Murmur Workbench - {proof.run_id}", extra_css=extra_css)
    shell = hud_shell_start(
        brand="murmur",
        run_line=f"{escape(proof.run_id)} - static workbench",
        quote="One proof, every artifact, no hidden agent state.",
    )
    body = f"""
<section class="hud-widget">
  <div class="hud-widget__hd">trust</div>
  <div class="hud-widget__bd">
    <p class="wb-score">{escape(str(trust))}</p>
    <div class="kv"><span class="k">level</span><span>{escape(str(level))}</span></div>
    <div class="kv"><span class="k">verdict</span><span>{escape(proof.verdict)}</span></div>
    <div class="kv"><span class="k">attempts</span><span>{attempts}</span></div>
    <div class="kv"><span class="k">tool calls</span><span>{proof.tool_calls}</span></div>
    <div class="kv"><span class="k">model calls</span><span>{proof.model_calls}</span></div>
  </div>
</section>
<section class="hud-widget">
  <div class="hud-widget__hd">artifacts</div>
  <div class="hud-widget__bd"><ul class="wb-list">{artifacts}</ul></div>
</section>
<section class="hud-widget">
  <div class="hud-widget__hd">proof json</div>
  <div class="hud-widget__bd"><pre class="wb-pre">{pretty_payload}</pre></div>
</section>
"""
    return head + "<body>" + shell + body + document_close(extra_script=script)
