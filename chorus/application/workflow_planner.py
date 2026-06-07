"""Template planner for Murmur workflow YAML."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, Protocol

import yaml

from chorus.application.artifact_contracts import classify_deliverable, looks_like_program_task
from chorus.benchmarks.swe.types import ModelResponse
from chorus.domain.workflow import WorkflowNode, WorkflowPlan

TEMPLATES = (
    "coding_fix_test",
    "coding_generate_and_test",
    "site_generate_validate_repair",
    "strategy_research_backtest",
    "writing_tournament",
    "document_review",
)

_BUILD_KEYWORDS = (
    "website",
    "webapp",
    "web app",
    "landing page",
    "landing site",
    "frontend",
    "front-end",
    "full stack",
    "fullstack",
    "animation",
    "interactive",
    "ui ",
    " ux",
    "component",
    "react",
    "vue",
    "svelte",
    "html",
    "css",
    "javascript",
    "typescript",
    "api",
    "backend",
    "mobile app",
    "dashboard",
    "deploy",
    "production-ready",
    "single-page",
)

_GREENFIELD_PHRASES = (
    "create a ",
    "create an ",
    "build a ",
    "build an ",
    "implement a ",
    "implement an ",
    "develop a ",
    "develop an ",
    "design a ",
    "design an ",
)

_SITE_KEYWORDS = (
    "website",
    "web app",
    "webapp",
    "landing page",
    "landing site",
    "frontend",
    "front-end",
    "html",
    "css",
    "javascript",
    "three.js",
    "threejs",
    "animation",
    "interactive",
)

_WRITING_PHRASES = (
    "cover letter",
    "application",
    "essay",
    "draft",
    "writing",
    "rewrite",
    "story",
    "write a ",
    "write an ",
    "narrative",
    "poem",
    "blog post",
)


@dataclass(frozen=True, slots=True)
class WorkflowSize:
    attempts: int
    max_repairs: int
    reason: str


class WorkflowPlannerModel(Protocol):
    def complete(
        self,
        *,
        system: str,
        user: str,
        seed: int,
        max_tokens: int = ...,
    ) -> ModelResponse:
        """Return one structured workflow-plan completion."""


def plan_from_task(
    *,
    task: str,
    template: str = "auto",
    command: str = "",
    attempts: int = 1,
    max_repairs: int = 0,
) -> WorkflowPlan:
    selected = _select_template(task, template)
    if selected == "site_generate_validate_repair":
        return _site_generate_plan(task, attempts, max_repairs)
    if selected == "coding_fix_test":
        if not command:
            raise RuntimeError("coding_fix_test requires --cmd")
        return _coding_fix_test(task, command, attempts, max_repairs)
    if selected == "strategy_research_backtest":
        return _strategy_research(task, command, attempts)
    if selected == "writing_tournament":
        return _writing_tournament(task, attempts)
    if selected == "document_review":
        return _document_review(task)
    if selected == "coding_generate_and_test" and _is_site_task(task) and not command:
        return _site_generate_plan(task, attempts, max_repairs)
    return _coding_generate_and_test(task, command, attempts, max_repairs)


def _is_build_task(task: str) -> bool:
    lowered = task.lower()
    if any(keyword in lowered for keyword in _BUILD_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in _GREENFIELD_PHRASES)


def _is_site_task(task: str) -> bool:
    lowered = task.lower()
    return any(keyword in lowered for keyword in _SITE_KEYWORDS)


def _is_hard_site_task(task: str) -> bool:
    lowered = task.lower()
    return _is_site_task(task) and any(
        token in lowered
        for token in (
            "dashboard",
            "simulator",
            "terminal",
            "trading",
            "trade",
            "order book",
            "orderbook",
            "orderflow",
            "order flow",
            "ticket",
            "chart",
            "volume",
            "real data",
            "live data",
            "multi",
            "complex",
            "real-time",
            "realtime",
        )
    )


def _is_writing_task(task: str) -> bool:
    lowered = task.lower()
    return (
        any(phrase in lowered for phrase in _WRITING_PHRASES)
        and not _is_build_task(task)
        and not looks_like_program_task(task)
    )


def choose_workflow_size(
    *,
    task: str,
    command: str = "",
    budget_usd: float = 0.50,
) -> WorkflowSize:
    """Choose fan-out and repair budget from task risk, scope, and objective feedback."""

    lowered = f"{task} {command}".lower()
    score = 0
    reasons: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(reason)

    if command.strip():
        add(2, "objective command")
    repair_words = ("fix", "bug", "failing", "failure", "regression", "repair")
    if any(word in lowered for word in repair_words):
        add(2, "repair task")
    if _is_writing_task(task):
        if any(word in lowered for word in ("short", "brief", "simple", "quick", "one-liner")):
            add(1, "light writing")
        else:
            add(2, "subjective writing")
    if _is_build_task(task):
        add(2, "software build")
        matched = [kw for kw in _BUILD_KEYWORDS if kw in lowered]
        if len(matched) >= 2:
            add(1, "multi-surface build")
    if any(phrase in lowered for phrase in _GREENFIELD_PHRASES):
        add(1, "greenfield deliverable")
    if any(
        word in lowered
        for word in (
            "trading",
            "jane street",
            "janestreet",
            "payment",
            "auth",
            "security",
            "money",
            "finance",
        )
    ):
        add(2, "high-risk domain")
    if any(word in lowered for word in ("complex", "hard", "ambiguous", "unknown", "uncertain")):
        add(1, "ambiguous task")
    if any(
        phrase in lowered
        for phrase in (
            "step-by-step",
            "exactly ",
            "measure out",
            "puzzle",
            "reasoning",
            "logic problem",
            "how many",
            "which container",
        )
    ):
        add(2, "reasoning puzzle")
    if any(word in lowered for word in ("production", "complete", "comprehensive", "quality")):
        add(1, "high bar")

    words = len(lowered.split())
    if words >= 15:
        add(1, "detailed brief")
    if words >= 30:
        add(2, "long brief")
    if words >= 60:
        add(2, "very long brief")
    if lowered.count(" and ") >= 2 or "deliverable" in lowered:
        add(1, "multi-deliverable")

    if budget_usd < 0.05:
        budget_cap = 1
    elif budget_usd < 0.15:
        budget_cap = 2
    elif budget_usd < 0.50:
        budget_cap = 6
    else:
        budget_cap = 12

    if score <= 1:
        attempts = 1
    elif score <= 3:
        attempts = 2
    elif score <= 6:
        attempts = 4
    elif score <= 9:
        attempts = 6
    else:
        attempts = 8
    attempts = max(1, min(attempts, budget_cap))

    max_repairs = 0
    if command.strip():
        max_repairs = 1 if score <= 4 else 2
    elif _is_hard_site_task(task):
        if budget_cap >= 6:
            max_repairs = 3
        elif budget_cap >= 2:
            max_repairs = 1
    elif _is_site_task(task) and score >= 4 and budget_cap >= 6:
        max_repairs = 1

    reason = ", ".join(reasons) if reasons else "simple task"
    reason = f"{reason}; score={score}; budget_cap={budget_cap}"
    return WorkflowSize(attempts=attempts, max_repairs=max_repairs, reason=reason)


def _author_workflow_with_usage(
    *,
    task: str,
    model: WorkflowPlannerModel,
    command: str,
    attempts: int,
    max_repairs: int,
    max_cost_usd: float,
    seed: int,
    max_tokens: int,
) -> tuple[WorkflowPlan, ModelResponse]:
    response = model.complete(
        system=_SELF_WRITE_SYSTEM,
        user=_self_write_prompt(
            task=task,
            command=command,
            attempts=attempts,
            max_repairs=max_repairs,
            max_cost_usd=max_cost_usd,
        ),
        seed=seed,
        max_tokens=max_tokens,
    )
    workflow = parse_model_workflow(response.text)
    _check_model_workflow_bounds(workflow, command=command, max_cost_usd=max_cost_usd)
    return workflow, response


def plan_from_model(
    *,
    task: str,
    model: WorkflowPlannerModel,
    command: str = "",
    attempts: int = 1,
    max_repairs: int = 0,
    max_cost_usd: float = 0.50,
    seed: int = 0,
    max_tokens: int = 6000,
) -> WorkflowPlan:
    """Ask a model to write a workflow IR, then validate it before use."""

    workflow, _ = _author_workflow_with_usage(
        task=task,
        model=model,
        command=command,
        attempts=attempts,
        max_repairs=max_repairs,
        max_cost_usd=max_cost_usd,
        seed=seed,
        max_tokens=max_tokens,
    )
    return workflow


def parse_model_workflow(text: str) -> WorkflowPlan:
    """Parse a model-authored JSON/YAML workflow document."""

    candidate = _strip_fence(text)
    data: object
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        data = yaml.safe_load(candidate)
    if not isinstance(data, dict):
        raise RuntimeError("model planner must return one JSON/YAML object")
    workflow = WorkflowPlan.from_dict(data)
    issues = workflow.validate()
    if issues:
        raise RuntimeError("model-written workflow failed validation: " + "; ".join(issues))
    return workflow


@dataclass(frozen=True, slots=True)
class PlannerOutcome:
    """A planned workflow plus how it was produced (model vs deterministic template)."""

    workflow: WorkflowPlan
    mode: str  # "model" | "template"
    reason: str = ""
    duration_ms: float = 0.0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    reasoning: str = ""

    def meta(self) -> dict[str, Any]:
        data: dict[str, Any] = {"mode": self.mode, "duration_ms": round(self.duration_ms, 1)}
        if self.reason:
            data["reason"] = self.reason
        if self.model_calls:
            data["model_calls"] = self.model_calls
            data["input_tokens"] = self.input_tokens
            data["output_tokens"] = self.output_tokens
            data["cost_usd"] = self.cost_usd
        if self.reasoning:
            data["reasoning"] = self.reasoning[:2000]
        return data


def plan_task(
    *,
    task: str,
    model: WorkflowPlannerModel | None = None,
    command: str = "",
    budget_usd: float = 0.50,
    template: str = "auto",
    attempts: int = 0,
    max_repairs: int = 0,
    seed: int = 0,
) -> PlannerOutcome:
    """Plan a workflow from the task.

    Model-authored by default when a model is available and ``template == "auto"``; otherwise
    (no model, forced template, or any planning failure) it falls back to the deterministic
    keyword templates. A valid plan is always returned.
    """

    start = perf_counter()

    def elapsed_ms() -> float:
        return (perf_counter() - start) * 1000

    size = choose_workflow_size(task=task, command=command, budget_usd=budget_usd)
    chosen_attempts = attempts or size.attempts
    chosen_repairs = max_repairs or size.max_repairs
    keyword_kind = classify_deliverable(task)

    def site_plan() -> WorkflowPlan:
        return _with_kind(
            plan_from_task(
                task=task,
                template="site_generate_validate_repair",
                command=command,
                attempts=chosen_attempts,
                max_repairs=chosen_repairs,
            ),
            "site",
        )

    def template_plan(kind: str) -> WorkflowPlan:
        return _with_kind(
            plan_from_task(
                task=task,
                template=template,
                command=command,
                attempts=chosen_attempts,
                max_repairs=chosen_repairs,
            ),
            kind,
        )

    if template != "auto":
        return PlannerOutcome(
            workflow=template_plan(keyword_kind),
            mode="template",
            reason=f"template forced: {template}",
            duration_ms=elapsed_ms(),
        )

    # A clearly-interactive deliverable uses the proven site closed loop. Skipping the model
    # planning call here also removes the wasted ~35s on tasks that are obviously web apps.
    if keyword_kind == "site" and not command:
        return PlannerOutcome(
            workflow=site_plan(),
            mode="template",
            reason="interactive web app -> site pipeline",
            duration_ms=elapsed_ms(),
        )

    if model is not None:
        try:
            authored, response = _author_workflow_with_usage(
                task=task,
                model=model,
                command=command,
                attempts=chosen_attempts,
                max_repairs=chosen_repairs,
                max_cost_usd=budget_usd,
                seed=seed,
                max_tokens=6000,
            )
            kind = authored.artifact_kind or keyword_kind or "program"
            if kind == "site" and not command:
                # The model decided a web app: prefer the deterministic closed loop over an
                # ad-hoc DAG so it gets browser validation, richness ranking, and repair.
                workflow = site_plan()
            else:
                workflow = _with_kind(_finalize_plan(authored, task), kind)
            return PlannerOutcome(
                workflow=workflow,
                mode="model",
                duration_ms=elapsed_ms(),
                model_calls=1,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost_usd,
                reasoning=getattr(response, "reasoning", ""),
            )
        except Exception as exc:  # noqa: BLE001 - any planner/provider fault falls back safely
            return PlannerOutcome(
                workflow=template_plan(keyword_kind),
                mode="template",
                reason=f"model planning failed: {exc}"[:300],
                duration_ms=elapsed_ms(),
            )

    return PlannerOutcome(
        workflow=template_plan(keyword_kind),
        mode="template",
        reason="no model configured",
        duration_ms=elapsed_ms(),
    )


def _with_kind(workflow: WorkflowPlan, kind: str) -> WorkflowPlan:
    if not kind or workflow.artifact_kind == kind:
        return workflow
    return replace(workflow, artifact_kind=kind)


def _finalize_plan(workflow: WorkflowPlan, task: str) -> WorkflowPlan:
    """Back-fill empty generate/map roles from the role library to protect output quality."""

    default_role = _generation_role(task)
    updated: list[WorkflowNode] = []
    changed = False
    for node in workflow.nodes:
        if node.op in ("generate", "map") and node.id != "brief" and not node.role.strip():
            updated.append(replace(node, role=default_role))
            changed = True
        else:
            updated.append(node)
    if not changed:
        return workflow
    return replace(workflow, nodes=tuple(updated))


def _select_template(task: str, template: str) -> str:
    if template != "auto":
        if template not in TEMPLATES:
            raise RuntimeError(f"unknown workflow template: {template}")
        return template
    lowered = task.lower()
    if "strategy" in lowered or "backtest" in lowered or "sharpe" in lowered:
        return "strategy_research_backtest"
    kind = classify_deliverable(task)
    if kind == "site":
        return "site_generate_validate_repair"
    if kind == "program":
        return "coding_generate_and_test"
    if kind == "document":
        return "writing_tournament" if _is_writing_task(task) else "document_review"
    if _is_writing_task(task):
        return "writing_tournament"
    if _is_build_task(task):
        return "coding_generate_and_test"
    if "document" in lowered or "review" in lowered:
        return "document_review"
    if "fix" in lowered or "test" in lowered or "bug" in lowered:
        if command_placeholder_possible(task):
            return "coding_fix_test"
        return "coding_generate_and_test"
    return "coding_generate_and_test"


_SELF_WRITE_SYSTEM = """\
You are the Murmur workflow planner. You design the best workflow for the user's actual task.
Return ONLY a single JSON object for WorkflowPlan version 1 (no prose, no markdown, no code).
The runtime interprets this data as a DAG; it never executes any code you write.

Operators (op):
- classify: route/label the task (params.task).
- generate: one model call producing one artifact (params.prompt; set node.role for guidance).
- map: fan out N independent candidates of the same kind (params.n, params.prompt).
- tournament: pairwise-judge candidates and keep the winner (subjective quality).
- rank: pick the best candidate by objective signals.
- exec: run the user's objective command ONLY (never invent commands).
- loop: bounded repair loop (params.until, params.max_iterations).
- filter / reduce: drop or collapse candidates.
- verify: re-check the winner.
- report: final node; every plan ends here.

First decide the DELIVERABLE the user actually wants and set the top-level "artifact_kind":
- "site": an interactive single-page web app (dashboards, charts, trading/candlestick UIs,
  games, visualizations, anything the user opens in a browser and clicks).
- "program": runnable code (a CLI, library, script, algorithm) the user runs themselves.
- "document": prose (a letter, essay, story, report).
When in doubt for something visual or interactive, prefer "site".

Design principles:
- Match the shape to the task. Creative/greenfield/subjective work (websites, apps, essays,
  designs) benefits from fanning out several competing candidates (typically 3-6) then ranking
  or judging them. Simple, single-answer tasks need just generate -> report (1 candidate).
- A strong build shape: classify -> brief (generate) -> generate (map, n candidates) -> rank ->
  report, where the map node reads the brief via params.context_nodes=["brief"].
- A strong writing shape: map (n drafts) -> tournament -> report.
- Give every generate/map node a concrete, task-specific role (node.role) describing exactly
  what one excellent candidate looks like.
- Choose the candidate count yourself from the task's difficulty and the budget. More candidates
  cost more; stay within budget.max_cost_usd.
- Use exec ONLY for the exact objective command the user supplied. If an exec node consumes
  map/generate output, set params.allow_tainted_inputs=true and policy="allow_tainted_inputs".
  If no command was supplied, do not include any exec node.
"""


def _self_write_prompt(
    *,
    task: str,
    command: str,
    attempts: int,
    max_repairs: int,
    max_cost_usd: float,
) -> str:
    command_rule = (
        f'Objective command (use verbatim in every exec node): "{command}".'
        if command
        else "No objective command was supplied. Do not include any exec node."
    )
    return f"""\
Task:
{task}

Constraints and budget:
- version: 1, schema_version: 1
- budget.max_cost_usd <= {max_cost_usd}
- {command_rule}
- Suggested candidate count: ~{max(1, attempts)} (adjust up or down to fit the task and budget).
- Repair loop budget if you use loop: {max(0, max_repairs)}.
- End the DAG with a single report node.

Return one JSON object with keys: version, schema_version, name, goal, description,
artifact_kind, budget, nodes.
artifact_kind must be one of "site", "program", or "document" (the deliverable).
Each node: id, op, optional inputs (list of upstream ids), optional params, optional role.
Set goal to the task. Choose name to describe the workflow.
"""


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json|yaml|yml)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def _check_model_workflow_bounds(
    workflow: WorkflowPlan,
    *,
    command: str,
    max_cost_usd: float,
) -> None:
    issues: list[str] = []
    cost = workflow.budget.get("max_cost_usd")
    if isinstance(cost, int | float) and cost > max_cost_usd:
        issues.append(f"budget.max_cost_usd exceeds allowed maximum {max_cost_usd}")
    for node in workflow.nodes:
        if node.op != "exec":
            continue
        node_command = str(node.params.get("command", ""))
        if not command:
            issues.append(f"exec node {node.id} is not allowed without --cmd")
        elif node_command != command:
            issues.append(f"exec node {node.id} must use the supplied command")
    if issues:
        raise RuntimeError("model-written workflow violates planner bounds: " + "; ".join(issues))


def command_placeholder_possible(task: str) -> bool:
    return "pytest" in task.lower() or "test" in task.lower()


def _coding_fix_test(task: str, command: str, attempts: int, max_repairs: int) -> WorkflowPlan:
    attempts = max(1, attempts)
    max_repairs = max(0, max_repairs)
    return WorkflowPlan(
        version=1,
        schema_version=1,
        name="coding_fix_test",
        goal=task,
        description="Closed-loop coding repair from an objective test command.",
        budget={"max_cost_usd": 0.50, "max_candidates": attempts, "max_repairs": max_repairs},
        nodes=(
            WorkflowNode(
                id="reproduce",
                op="exec",
                params={"command": command, "parser": "pytest"},
            ),
            WorkflowNode(
                id="generate",
                op="generate",
                inputs=("reproduce",),
                params={
                    "n": attempts,
                    "agent": "scripted",
                    "provider": "",
                    "model": "",
                    "prompt": task,
                    "isolation": "worktree_per_attempt",
                },
                role="Generate independent repair candidates.",
            ),
            WorkflowNode(
                id="run_tests",
                op="exec",
                inputs=("generate",),
                params={"command": command, "parser": "pytest", "allow_tainted_inputs": True},
                policy="allow_tainted_inputs",
            ),
            WorkflowNode(
                id="repair",
                op="loop",
                inputs=("run_tests",),
                params={"until": "passed", "max_iterations": max_repairs},
            ),
            WorkflowNode(id="rank", op="rank", inputs=("repair",)),
            WorkflowNode(id="verify", op="verify", inputs=("rank",)),
            WorkflowNode(id="report", op="report", inputs=("verify",)),
        ),
    )


def _coding_generate_and_test(
    task: str,
    command: str,
    attempts: int = 1,
    max_repairs: int = 0,
) -> WorkflowPlan:
    attempts = max(1, attempts)
    max_repairs = max(0, max_repairs)
    generate_params = {"prompt": task, "max_tokens": _candidate_max_tokens(task)}
    nodes: list[WorkflowNode] = [
        WorkflowNode(id="classify", op="classify", params={"task": task}),
    ]
    if attempts > 1:
        nodes.append(
            WorkflowNode(
                id="generate",
                op="map",
                inputs=("classify",),
                params={"n": attempts, **generate_params},
                role=_generation_role(task),
            )
        )
        upstream = "generate"
        if command:
            nodes.append(
                WorkflowNode(
                    id="test",
                    op="exec",
                    inputs=("generate",),
                    params={
                        "command": command,
                        "parser": "pytest",
                        "allow_tainted_inputs": True,
                    },
                    policy="allow_tainted_inputs",
                )
            )
            upstream = "test"
        if max_repairs > 0 and command:
            nodes.append(
                WorkflowNode(
                    id="repair",
                    op="loop",
                    inputs=(upstream,),
                    params={"until": "passed", "max_iterations": max_repairs},
                )
            )
            upstream = "repair"
        nodes.append(WorkflowNode(id="rank", op="rank", inputs=(upstream,)))
        nodes.append(WorkflowNode(id="report", op="report", inputs=("rank",)))
        description = (
            "Classify the task, fan out competing build candidates, "
            "verify objectively, rank, and report the winner."
            if command
            else "Classify the task, fan out competing build candidates, rank, and report."
        )
    else:
        nodes.append(
            WorkflowNode(
                id="generate",
                op="generate",
                inputs=("classify",),
                params=generate_params,
                role=_generation_role(task),
            )
        )
        upstream = "generate"
        if command:
            nodes.append(
                WorkflowNode(
                    id="test",
                    op="exec",
                    inputs=("generate",),
                    params={
                        "command": command,
                        "parser": "pytest",
                        "allow_tainted_inputs": True,
                    },
                    policy="allow_tainted_inputs",
                )
            )
            upstream = "test"
        nodes.append(WorkflowNode(id="report", op="report", inputs=(upstream,)))
        description = "Generate a coding artifact and optionally check it."
    return WorkflowPlan(
        version=1,
        schema_version=1,
        name="coding_generate_and_test",
        goal=task,
        description=description,
        budget={"max_cost_usd": 0.50, "max_candidates": attempts, "max_repairs": max_repairs},
        nodes=tuple(nodes),
    )


def _site_generate_plan(
    task: str,
    attempts: int = 1,
    max_repairs: int = 0,
) -> WorkflowPlan:
    """Dedicated greenfield-site pipeline with visible acceptance and repair gates."""

    attempts = max(4, attempts)  # max-quality fan-out for site tasks
    max_repairs = max(0, max_repairs)
    nodes: list[WorkflowNode] = [
        WorkflowNode(id="classify", op="classify", params={"task": task}),
        WorkflowNode(
            id="acceptance_spec",
            op="classify",
            inputs=("classify",),
            params={"task": task, "default": "site_acceptance_contract"},
            role="Derive the hard artifact acceptance contract from the prompt.",
        ),
        WorkflowNode(
            id="brief",
            op="generate",
            inputs=("acceptance_spec",),
            params={"prompt": task, "max_tokens": 2000},
            role=_SITE_BRIEF_ROLE,
        ),
        WorkflowNode(
            id="generate",
            op="map",
            inputs=("acceptance_spec", "brief"),
            params={
                "n": attempts,
                "prompt": task,
                "max_tokens": _candidate_max_tokens(task),
                "context_nodes": ("brief",),
            },
            role=_generation_role(task),
        ),
        WorkflowNode(
            id="validate_site",
            op="verify",
            inputs=("generate",),
            role="Extract the site artifact and check HTML completeness.",
        ),
        WorkflowNode(
            id="browser_verify",
            op="verify",
            inputs=("validate_site",),
            role="Load the site in a browser, capture screenshots, and collect console evidence.",
        ),
        WorkflowNode(
            id="requirement_assert",
            op="verify",
            inputs=("browser_verify",),
            role="Assert prompt-specific hard requirements before ranking.",
        ),
    ]
    upstream = "requirement_assert"
    if max_repairs > 0:
        nodes.append(
            WorkflowNode(
                id="repair_loop",
                op="loop",
                inputs=(upstream,),
                params={"until": "acceptance_passed", "max_iterations": max_repairs},
                role="Repair failed site artifacts until hard validation passes or budget ends.",
            )
        )
        upstream = "repair_loop"
    nodes.extend(
        (
            WorkflowNode(id="rank", op="rank", inputs=(upstream,)),
            WorkflowNode(id="report", op="report", inputs=("rank",)),
        )
    )
    return WorkflowPlan(
        version=1,
        schema_version=1,
        name="site_generate_validate_repair",
        goal=task,
        description=(
            "Extract acceptance criteria, fan out website builds, validate in-browser, "
            "repair failed artifacts, rank, and report the best site."
        ),
        budget={"max_cost_usd": 0.75, "max_candidates": attempts, "max_repairs": max_repairs},
        nodes=tuple(nodes),
    )


def _candidate_max_tokens(task: str) -> int:
    if _is_site_task(task):
        return 24000
    if _is_build_task(task):
        return 4000
    return 1600


_SITE_BRIEF_ROLE = (
    "You are a creative director. Given a one-line website request, produce a tight "
    "BUILD BRIEF (not HTML, no code). Output these labeled sections:\n"
    "THEME: mood, central metaphor, and a palette of 3-5 hex colors.\n"
    "STRUCTURE: 6-8 page sections, each with a one-line purpose.\n"
    "SIGNATURE INTERACTION: one standout interactive idea and how it works.\n"
    "COPY: specific, true headlines and a 2-3 sentence blurb for each section, "
    "grounded in real facts about the subject.\n"
    "TECH: which CDN libraries to use (e.g. Tailwind, three.js, GSAP, lucide).\n"
    "Be concrete and opinionated. Keep it under 600 words."
)


def _generation_role(task: str) -> str:
    if _is_site_task(task):
        return (
            "You are a world-class creative frontend engineer and art director. Build "
            "one award-winning, immersive interactive website for the subject, and "
            "implement the provided CREATIVE BRIEF as the source of truth for theme, "
            "sections, and copy.\n"
            "Hard requirements:\n"
            "- Return ONLY one complete HTML file: a single document from <!doctype html> "
            "to </html> (one ```html fenced block is allowed; no other prose, comments, "
            "or explanation before or after).\n"
            "- At least 6 distinct, purposeful sections: a cinematic hero, an interactive "
            "showcase with working controls (tabs/sliders/buttons), at least one live "
            "<canvas> animation or data visualization, a narrative timeline or story arc, "
            "real subject-specific copy (never lorem or placeholder), and a footer.\n"
            "- Real interactivity wired in JavaScript (event listeners, state changes, "
            "hover and scroll effects); at least one non-blank animated visual.\n"
            "- A cohesive design system: CSS custom properties, fluid type with clamp(), "
            "responsive grid with @media, and tasteful motion "
            "(transitions/keyframes/requestAnimationFrame).\n"
            "- You MAY load CDN libraries (Tailwind, lucide, three.js, GSAP, Google "
            "Fonts); keep the page usable if a CDN is slow.\n"
            "- Accessible: semantic landmarks, alt text, visible focus states, strong "
            "contrast.\n"
            "Keep all CSS and JavaScript inline in the single file."
        )
    return "Generate one independent implementation candidate."


def _strategy_research(task: str, command: str, attempts: int = 3) -> WorkflowPlan:
    attempts = max(2, attempts)
    backtest_command = command or "python -m pytest tests/test_strategy_fixture.py -q"
    return WorkflowPlan(
        version=1,
        schema_version=1,
        name="strategy_research_backtest",
        goal=task,
        description="Research-only strategy workflow with fixture-backed backtest execution.",
        budget={"max_cost_usd": 0.50, "max_candidates": attempts},
        nodes=(
            WorkflowNode(id="classify", op="classify", params={"task": task}),
            WorkflowNode(
                id="generate",
                op="map",
                inputs=("classify",),
                params={"n": attempts, "prompt": task},
            ),
            WorkflowNode(
                id="backtest",
                op="exec",
                inputs=("generate",),
                params={
                    "command": backtest_command,
                    "parser": "pytest",
                    "allow_tainted_inputs": True,
                },
                policy="allow_tainted_inputs",
            ),
            WorkflowNode(id="rank", op="rank", inputs=("backtest",)),
            WorkflowNode(id="verify", op="verify", inputs=("rank",)),
            WorkflowNode(
                id="report",
                op="report",
                inputs=("verify",),
                params={"summary": "research only; no trading execution"},
            ),
        ),
    )


def _writing_tournament(task: str, attempts: int) -> WorkflowPlan:
    attempts = max(2, attempts)
    return WorkflowPlan(
        version=1,
        schema_version=1,
        name="writing_tournament",
        goal=task,
        description="Generate independent drafts, judge pairwise, and report the winner.",
        budget={"max_cost_usd": 0.25, "max_candidates": attempts},
        nodes=(
            WorkflowNode(
                id="draft",
                op="map",
                params={"n": attempts, "prompt": task},
                role=(
                    "Write one independent draft. Prefer specific, human, plain language. "
                    "Return only the draft."
                ),
            ),
            WorkflowNode(
                id="judge",
                op="tournament",
                inputs=("draft",),
                params={"max_tokens": 256},
                role="Pick the candidate that best satisfies the task. Return exactly A or B.",
            ),
            WorkflowNode(id="report", op="report", inputs=("judge",)),
        ),
    )


def _document_review(task: str) -> WorkflowPlan:
    return WorkflowPlan(
        version=1,
        schema_version=1,
        name="document_review",
        goal=task,
        description="Classify, review, verify, and summarize a document task.",
        budget={"max_cost_usd": 0.10},
        nodes=(
            WorkflowNode(id="classify", op="classify", params={"task": task}),
            WorkflowNode(id="review", op="generate", inputs=("classify",), params={"prompt": task}),
            WorkflowNode(id="verify", op="verify", inputs=("review",)),
            WorkflowNode(id="report", op="report", inputs=("verify",)),
        ),
    )
