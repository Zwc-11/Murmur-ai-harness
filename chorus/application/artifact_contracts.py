"""Artifact contracts for workflow outputs."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

SITE_TOKENS = (
    "website",
    "web app",
    "webapp",
    "landing page",
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

HARD_APP_TOKENS = (
    "dashboard",
    "simulator",
    "terminal",
    "workbench",
    "trading",
    "trade",
    "order book",
    "orderbook",
    "orderflow",
    "order flow",
    "ticket",
    "chart",
    "volume",
    "portfolio",
    "account",
    "analytics",
    "real-time",
    "realtime",
    "live data",
)

TRADING_TOKENS = (
    "trading",
    "trade",
    "quant",
    "orderflow",
    "order flow",
    "order book",
    "orderbook",
    "dom",
    "bid",
    "ask",
    "volume",
    "footprint",
    "ticket",
)

REAL_DATA_TOKENS = (
    "real data",
    "real market",
    "live data",
    "actual data",
    "historical data",
    "real volume",
    "real order",
)

DOCUMENT_TOKENS = (
    "cover letter",
    "essay",
    "story",
    "poem",
    "blog post",
    "article",
    "letter",
    "narrative",
    "speech",
    "screenplay",
    "novel",
    "write a ",
    "write an ",
    "rewrite",
    "draft",
)

DOCUMENT_MIN_LENGTH = 40

# Richness is a soft quality signal for sites: it drives candidate selection,
# trust scoring, and the enrichment trigger, but never overrides a hard render
# or completeness failure.
RICH_SITE_TARGET = 60
RICH_SITE_MIN = 35

PROGRAM_TOKENS = (
    "script",
    "program",
    "cli",
    "command-line",
    "command line",
    "algorithm",
    "scraper",
    "crawler",
    "parser",
    "library",
    "package",
    "calculator",
    "solver",
    "compiler",
    "interpreter",
    "bot",
    "data pipeline",
    "pipeline",
    "in python",
    "in javascript",
    "in typescript",
    "in rust",
    "in c++",
    "in go",
    "in java",
    "python program",
    "function that",
    "class that",
    "code that",
)

PROGRAM_MIN_LENGTH = 80

# Fenced-language tag -> source file extension for written program artifacts.
_LANG_EXT = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "rust": ".rs",
    "go": ".go",
    "golang": ".go",
    "java": ".java",
    "c++": ".cpp",
    "cpp": ".cpp",
    "c": ".c",
    "csharp": ".cs",
    "cs": ".cs",
    "ruby": ".rb",
    "rb": ".rb",
    "php": ".php",
    "bash": ".sh",
    "sh": ".sh",
    "shell": ".sh",
    "sql": ".sql",
    "kotlin": ".kt",
    "swift": ".swift",
}


@dataclass(frozen=True, slots=True)
class ArtifactValidation:
    kind: str
    passed: bool
    summary: str
    checks: dict[str, bool]
    risk_flags: tuple[str, ...] = ()
    artifacts: tuple[dict[str, str], ...] = ()
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_flags"] = list(self.risk_flags)
        data["artifacts"] = list(self.artifacts)
        data["details"] = self.details or {}
        return data


@dataclass(frozen=True, slots=True)
class ArtifactBuildResult:
    written: bool
    validation: ArtifactValidation
    primary_artifact: dict[str, str] | None = None


def looks_like_site_task(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in SITE_TOKENS)


def looks_like_hard_app_task(text: str) -> bool:
    lowered = text.lower()
    return looks_like_site_task(text) and any(token in lowered for token in HARD_APP_TOKENS)


def looks_like_trading_task(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in TRADING_TOKENS)


def requests_real_data(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in REAL_DATA_TOKENS)


def looks_like_program_task(text: str) -> bool:
    if looks_like_site_task(text):
        return False
    lowered = text.lower()
    return any(token in lowered for token in PROGRAM_TOKENS)


def looks_like_document_task(text: str) -> bool:
    if looks_like_site_task(text) or looks_like_program_task(text):
        return False
    lowered = text.lower()
    return any(token in lowered for token in DOCUMENT_TOKENS)


class ArtifactContract(Protocol):
    """A concrete deliverable the harness can build and objectively validate."""

    kind: str

    def applies_to(self, goal: str) -> bool: ...

    def build(
        self,
        *,
        run_dir: Path,
        run_id: str,
        goal: str,
        candidate_texts: list[str],
        events_path: Path,
    ) -> ArtifactBuildResult: ...

    def trust_score(
        self,
        validation: ArtifactValidation,
        tool_summary: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SiteContract:
    kind: str = "site"

    def applies_to(self, goal: str) -> bool:
        return looks_like_site_task(goal)

    def build(
        self,
        *,
        run_dir: Path,
        run_id: str,
        goal: str,
        candidate_texts: list[str],
        events_path: Path,
    ) -> ArtifactBuildResult:
        return build_site_artifact(
            run_dir=run_dir,
            run_id=run_id,
            goal=goal,
            candidate_texts=candidate_texts,
            events_path=events_path,
        )

    def trust_score(
        self,
        validation: ArtifactValidation,
        tool_summary: dict[str, Any],
    ) -> dict[str, Any]:
        return site_trust_score(validation, tool_summary)


@dataclass(frozen=True, slots=True)
class DocumentContract:
    kind: str = "document"

    def applies_to(self, goal: str) -> bool:
        return looks_like_document_task(goal)

    def build(
        self,
        *,
        run_dir: Path,
        run_id: str,
        goal: str,
        candidate_texts: list[str],
        events_path: Path,
    ) -> ArtifactBuildResult:
        return build_document_artifact(
            run_dir=run_dir,
            run_id=run_id,
            goal=goal,
            candidate_texts=candidate_texts,
            events_path=events_path,
        )

    def trust_score(
        self,
        validation: ArtifactValidation,
        tool_summary: dict[str, Any],
    ) -> dict[str, Any]:
        return document_trust_score(validation, tool_summary)


@dataclass(frozen=True, slots=True)
class ProgramContract:
    kind: str = "program"

    def applies_to(self, goal: str) -> bool:
        return looks_like_program_task(goal)

    def build(
        self,
        *,
        run_dir: Path,
        run_id: str,
        goal: str,
        candidate_texts: list[str],
        events_path: Path,
    ) -> ArtifactBuildResult:
        return build_program_artifact(
            run_dir=run_dir,
            run_id=run_id,
            goal=goal,
            candidate_texts=candidate_texts,
            events_path=events_path,
        )

    def trust_score(
        self,
        validation: ArtifactValidation,
        tool_summary: dict[str, Any],
    ) -> dict[str, Any]:
        return program_trust_score(validation, tool_summary)


# Order matters: the most specific contract wins. Site is checked first (web apps),
# then program (code deliverables), then document (prose), so "write a python script"
# routes to the program builder and "write a cover letter" to the prose builder.
ARTIFACT_CONTRACTS: tuple[ArtifactContract, ...] = (
    SiteContract(),
    ProgramContract(),
    DocumentContract(),
)


def select_artifact_contract(goal: str) -> ArtifactContract | None:
    """Return the artifact contract that owns this task, if any."""

    for contract in ARTIFACT_CONTRACTS:
        if contract.applies_to(goal):
            return contract
    return None


# Interactive/visual intent -> a single-page web app is the right deliverable.
_APP_TOKENS = (
    *SITE_TOKENS,
    *HARD_APP_TOKENS,
    "candlestick",
    "footprint",
    "game",
    "visualize",
    "visualization",
    "visualisation",
    "play order",
    "place order",
    "canvas",
    "widget",
)

# Explicit "I want runnable code" signals that override the interactive-app reading.
_PROGRAM_FORM_TOKENS = (
    "in python",
    "in javascript",
    "in typescript",
    "in rust",
    "in c++",
    "in go",
    "in java",
    "cli",
    "command-line",
    "command line",
    "script",
    "library",
    "function that",
    "class that",
)

# High-precision document deliverables that outrank an incidental app token (e.g. a
# "cover letter for a quant trading internship" is a document, not a trading app).
_DOC_DELIVERABLE_TOKENS = (
    "cover letter",
    "essay",
    "blog post",
    "poem",
    "screenplay",
    "narrative",
)


def classify_deliverable(task: str) -> str:
    """Best deliverable kind for a task: 'site' | 'program' | 'document' | '' (unknown).

    Precedence: an explicit code form ("in python", a CLI/library/script) is a program; a
    named prose deliverable (cover letter, essay) is a document; otherwise interactive/visual
    work (a charting trading app, a dashboard, a game) is a web app — even when it says
    "simulator". Returns '' when nothing is decisive.
    """

    lowered = task.lower()
    if any(token in lowered for token in _PROGRAM_FORM_TOKENS):
        return "program"
    if any(token in lowered for token in _DOC_DELIVERABLE_TOKENS):
        return "document"
    if any(token in lowered for token in _APP_TOKENS):
        return "site"
    if looks_like_program_task(task):
        return "program"
    if looks_like_document_task(task):
        return "document"
    return ""


def contract_for_kind(kind: str) -> ArtifactContract | None:
    """Return the artifact contract for an explicitly declared deliverable kind."""

    for contract in ARTIFACT_CONTRACTS:
        if contract.kind == kind:
            return contract
    return None


def artifact_trust_score(
    validation: ArtifactValidation,
    tool_summary: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch trust scoring by validated artifact kind."""

    if validation.kind == "document":
        return document_trust_score(validation, tool_summary)
    if validation.kind == "program":
        return program_trust_score(validation, tool_summary)
    return site_trust_score(validation, tool_summary)


def build_acceptance_contract(goal: str) -> dict[str, Any]:
    """Build a deterministic artifact contract from the user-facing task text."""

    hard_app = looks_like_hard_app_task(goal)
    trading = looks_like_trading_task(goal)
    real_data = requests_real_data(goal)
    requirements: list[dict[str, Any]] = [
        {
            "id": "complete_html_artifact",
            "label": "Complete site artifact is written to site/index.html",
            "hard": True,
        },
        {
            "id": "browser_renders_without_console_errors",
            "label": "Browser renders the site with no console or page errors",
            "hard": True,
        },
    ]
    if hard_app:
        requirements.append(
            {
                "id": "no_large_blank_panels",
                "label": "Large app panels contain visible content or a rendered visual",
                "hard": True,
            }
        )
    if trading:
        requirements.extend(
            [
                {
                    "id": "orderbook_rows",
                    "label": "Order book or DOM contains visible bid/ask rows",
                    "hard": True,
                },
                {
                    "id": "trade_ticket_controls",
                    "label": "Trade ticket exposes quantity, price/type, and buy/sell controls",
                    "hard": True,
                },
                {
                    "id": "volume_orderflow_display",
                    "label": "Volume or orderflow panel has real visible data rows/signals",
                    "hard": True,
                },
                {
                    "id": "account_position_panel",
                    "label": "Position/P&L/account state is visible",
                    "hard": True,
                },
                {
                    "id": "ticket_interaction_updates_state",
                    "label": "Buy/sell interactions change visible simulator state",
                    "hard": True,
                },
                {
                    "id": "active_market_ticks",
                    "label": "Market state updates over time",
                    "hard": True,
                },
            ]
        )
    if real_data:
        requirements.append(
            {
                "id": "real_data_provenance",
                "label": "Requested real data is backed by a verified data-source artifact",
                "hard": True,
            }
        )
    profile = "trading_orderflow" if trading else "app" if hard_app else "site"
    return {
        "kind": "site",
        "profile": profile,
        "goal": goal,
        "hard_app": hard_app,
        "trading": trading,
        "data_expectation": {
            "requested_real_data": real_data,
            "requires_verified_source": real_data,
        },
        "requirements": requirements,
        "interaction_expectations": (
            ["buy", "sell", "quantity", "position_update"] if trading else []
        ),
    }


def evaluate_acceptance_contract(
    *,
    html: str,
    goal: str,
    browser: dict[str, Any],
    base_checks: dict[str, bool],
) -> dict[str, Any]:
    """Evaluate prompt-derived requirements against HTML and browser evidence."""

    contract = build_acceptance_contract(goal)
    lowered_html = html.lower()
    body_text = _browser_body_text(browser).lower()
    combined_text = f"{lowered_html}\n{body_text}"
    desktop = dict(browser.get("desktop", {}))
    interactions = dict(browser.get("interactions", {}))
    large_blank_count = int(desktop.get("largeBlankPanels", 0) or 0)
    button_count = int(desktop.get("buttonCount", 0) or 0)
    input_count = int(desktop.get("inputCount", 0) or 0) + int(
        desktop.get("selectCount", 0) or 0
    )
    table_rows = int(desktop.get("tableRowCount", 0) or 0)
    numbers = _number_tokens(combined_text)
    explicit_verified_data = _has_verified_data_marker(lowered_html)

    checks: dict[str, bool] = {
        "complete_html_artifact": base_checks.get("html_complete", False)
        and base_checks.get("artifact_written", False),
        "browser_renders_without_console_errors": base_checks.get("browser_rendered", False)
        and base_checks.get("dom_visible", False)
        and base_checks.get("console_clean", False),
        "no_large_blank_panels": large_blank_count == 0,
        "orderbook_rows": (
            any(token in combined_text for token in ("order book", "orderbook", " dom "))
            and "bid" in combined_text
            and "ask" in combined_text
            and (table_rows >= 8 or len(numbers) >= 18)
        ),
        "trade_ticket_controls": (
            "buy" in combined_text
            and "sell" in combined_text
            and any(token in combined_text for token in ("qty", "quantity"))
            and any(token in combined_text for token in ("price", "limit", "market"))
            and button_count >= 2
            and input_count >= 2
        ),
        "volume_orderflow_display": (
            "volume" in combined_text
            and any(
                token in combined_text
                for token in ("orderflow", "order flow", "footprint", "delta")
            )
            and len(numbers) >= 12
        ),
        "account_position_panel": (
            "position" in combined_text
            and any(token in combined_text for token in ("p&l", "pnl", "profit", "account"))
        ),
        "ticket_interaction_updates_state": bool(interactions.get("tradeStateChanged", False)),
        "active_market_ticks": bool(interactions.get("marketTicksChanged", False))
        or any(token in lowered_html for token in ("setinterval", "requestanimationframe")),
        "real_data_provenance": not contract["data_expectation"]["requested_real_data"]
        or explicit_verified_data,
    }
    requested_real_data = contract["data_expectation"]["requested_real_data"]
    if _mentions_simulated_data(lowered_html) and requested_real_data:
        checks["real_data_provenance"] = False

    requirement_results: list[dict[str, Any]] = []
    for requirement in contract["requirements"]:
        requirement_id = str(requirement["id"])
        passed = bool(checks.get(requirement_id, False))
        requirement_results.append(
            {
                **requirement,
                "passed": passed,
                "evidence": _acceptance_evidence(
                    requirement_id=requirement_id,
                    checks=checks,
                    browser=browser,
                    number_count=len(numbers),
                    table_rows=table_rows,
                    large_blank_count=large_blank_count,
                ),
            }
        )
    failed = [
        str(item["id"])
        for item in requirement_results
        if item.get("hard") and not item.get("passed")
    ]
    return {
        "contract": contract,
        "passed": not failed,
        "failed_requirements": failed,
        "requirements": requirement_results,
        "checks": checks,
        "risk_flags": tuple(_risk_flags_for_failed_requirements(failed)),
    }


def build_site_artifact(
    *,
    run_dir: Path,
    run_id: str,
    goal: str,
    candidate_texts: list[str],
    events_path: Path,
) -> ArtifactBuildResult:
    """Extract, write, and validate one site artifact from candidate text."""

    candidates: list[dict[str, Any]] = []
    for index, text in enumerate(candidate_texts):
        candidate = extract_index_html(text)
        if not candidate:
            continue
        richness = site_richness_score(candidate)["score"]
        candidates.append({"html": candidate, "index": index, "richness": richness})

    if not candidates:
        validation = ArtifactValidation(
            kind="site",
            passed=False,
            summary="No complete HTML artifact found.",
            checks={
                "html_complete": False,
                "artifact_written": False,
                "browser_rendered": False,
                "dom_visible": False,
                "requested_tech_present": False,
                "size_ok": False,
            },
            risk_flags=("missing_complete_site_artifact",),
        )
        _write_validation(run_dir, validation)
        _emit_tool_result(
            events_path,
            run_id,
            tool="extract_site_artifact",
            ok=False,
            result=validation.to_dict(),
            error=validation.summary,
        )
        return ArtifactBuildResult(written=False, validation=validation)

    selected_validation: ArtifactValidation | None = None
    selected_index = -1
    selected_html = ""
    selected_richness = -1
    for candidate in sorted(candidates, key=lambda item: int(item["richness"]), reverse=True):
        html = str(candidate["html"])
        candidate_index = int(candidate["index"])
        candidate_richness = int(candidate["richness"])
        _emit_tool_result(
            events_path,
            run_id,
            tool="extract_site_artifact",
            ok=True,
            result={
                "candidate_index": candidate_index,
                "bytes": len(html.encode("utf-8")),
                "richness": candidate_richness,
            },
        )
        site_dir = run_dir / "site"
        site_dir.mkdir(parents=True, exist_ok=True)
        site_path = site_dir / "index.html"
        start = perf_counter()
        site_path.write_text(html, encoding="utf-8")
        _emit_tool_result(
            events_path,
            run_id,
            tool="write_site_artifact",
            ok=True,
            result={"path": "site/index.html", "bytes": site_path.stat().st_size},
            latency_ms=_elapsed(start),
        )
        validation = validate_site_artifact(
            html=html,
            goal=goal,
            run_dir=run_dir,
            run_id=run_id,
        )
        if selected_validation is None or validation.passed:
            selected_validation = validation
            selected_index = candidate_index
            selected_html = html
            selected_richness = candidate_richness
        if validation.passed:
            break

    assert selected_validation is not None
    if not selected_validation.passed and selected_html:
        site_path = run_dir / "site" / "index.html"
        site_path.write_text(selected_html, encoding="utf-8")
        selected_validation = validate_site_artifact(
            html=selected_html,
            goal=goal,
            run_dir=run_dir,
            run_id=run_id,
        )
    validation = selected_validation
    _write_validation(run_dir, validation)
    _emit_tool_result(
        events_path,
        run_id,
        tool="validate_site_artifact",
        ok=validation.passed,
        result={
            **validation.to_dict(),
            "candidate_index": selected_index,
            "bytes": len(selected_html.encode("utf-8")),
            "richness": selected_richness,
        },
        error="" if validation.passed else validation.summary,
    )
    return ArtifactBuildResult(
        written=validation.passed,
        validation=validation,
        primary_artifact={
            "kind": "site_preview",
            "path": "site/index.html",
            "href": "site/index.html",
            "description": "generated website preview",
        },
    )


def validate_site_artifact(
    *,
    html: str,
    goal: str,
    run_dir: Path,
    run_id: str,
) -> ArtifactValidation:
    acceptance_contract = build_acceptance_contract(goal)
    (run_dir / "acceptance_contract.json").write_text(
        json.dumps(acceptance_contract, indent=2, default=str),
        encoding="utf-8",
    )
    browser = _browser_render_check(run_dir=run_dir, run_id=run_id)
    (run_dir / "browser_checks.json").write_text(
        json.dumps(browser, indent=2, default=str),
        encoding="utf-8",
    )
    interactions = browser.get("interactions", {})
    (run_dir / "interaction_checks.json").write_text(
        json.dumps(interactions, indent=2, default=str),
        encoding="utf-8",
    )
    browser_checks = dict(browser.get("checks", {}))
    browser_risks = tuple(str(item) for item in browser.get("risk_flags", ()))
    richness = site_richness_score(html)
    checks = {
        "html_complete": is_complete_html(html),
        "artifact_written": (run_dir / "site" / "index.html").is_file(),
        "browser_rendered": bool(browser_checks.get("browser_rendered", False)),
        "dom_visible": bool(browser_checks.get("dom_visible", False)),
        "console_clean": bool(browser_checks.get("console_clean", True)),
        "canvas_present": _canvas_requirement_met(html=html, goal=goal),
        "canvas_nonblank": bool(browser_checks.get("canvas_nonblank", True)),
        "requested_tech_present": _requested_tech_present(html=html, goal=goal),
        "size_ok": 300 <= len(html) <= 250_000,
        "rich_enough": richness["score"] >= RICH_SITE_MIN,
    }
    acceptance = evaluate_acceptance_contract(
        html=html,
        goal=goal,
        browser=browser,
        base_checks=checks,
    )
    checks["requirements_passed"] = bool(acceptance["passed"])
    checks["no_large_blank_panels"] = bool(
        acceptance["checks"].get("no_large_blank_panels", True)
    )
    checks["data_provenance_verified"] = bool(
        acceptance["checks"].get("real_data_provenance", True)
    )
    risk_flags = list(browser_risks)
    if not checks["html_complete"]:
        risk_flags.append("incomplete_html")
    if not checks["size_ok"]:
        risk_flags.append("site_size_out_of_bounds")
    if not checks["requested_tech_present"]:
        risk_flags.append("requested_technology_missing")
    if not checks["rich_enough"]:
        risk_flags.append("thin_site")
    if checks["browser_rendered"] and not checks["dom_visible"]:
        risk_flags.append("blank_browser_render")
    if checks["browser_rendered"] and not checks["console_clean"]:
        risk_flags.append("console_errors")
    if _requires_canvas(goal) and checks["browser_rendered"] and not checks["canvas_nonblank"]:
        risk_flags.append("blank_canvas")
    risk_flags.extend(str(item) for item in acceptance.get("risk_flags", ()))

    critical = (
        checks["html_complete"]
        and checks["artifact_written"]
        and checks["requested_tech_present"]
        and checks["size_ok"]
        and checks["requirements_passed"]
    )
    if checks["browser_rendered"]:
        critical = critical and checks["dom_visible"]
        critical = critical and checks["console_clean"]
        if _requires_canvas(goal):
            critical = critical and checks["canvas_present"] and checks["canvas_nonblank"]
    if acceptance_contract.get("hard_app"):
        critical = critical and checks["no_large_blank_panels"]
    artifacts = [{"kind": "site_preview", "path": "site/index.html"}]
    for path in ("screenshots/desktop.png", "screenshots/mobile.png"):
        if (run_dir / path).is_file():
            artifacts.append({"kind": "screenshot", "path": path})
    failed_requirements = list(acceptance.get("failed_requirements", ()))
    if critical:
        summary = "Website artifact validated."
    elif failed_requirements:
        summary = "Website artifact failed: " + ", ".join(failed_requirements[:6])
    else:
        summary = "Website artifact failed validation."
    return ArtifactValidation(
        kind="site",
        passed=critical,
        summary=summary,
        checks=checks,
        risk_flags=tuple(dict.fromkeys(risk_flags)),
        artifacts=tuple(artifacts),
        details={"browser": browser, "richness": richness, "acceptance": acceptance},
    )


def extract_index_html(text: str) -> str:
    candidates: list[str] = []
    marker = "=== index.html ==="
    if marker in text:
        body = text.split(marker, 1)[1].strip()
        next_marker = body.find("\n===")
        if next_marker >= 0:
            body = body[:next_marker].strip()
        candidates.append(body)
    for fenced in re.finditer(
        r"```(?:html)?\s*(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        candidates.append(fenced.group(1).strip())
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered.startswith("<!doctype") or lowered.startswith("<html"):
        candidates.append(stripped)
    for candidate in candidates:
        if is_complete_html(candidate):
            return candidate
    return ""


def is_complete_html(text: str) -> bool:
    lowered = text.lower()
    return (
        ("<!doctype" in lowered or "<html" in lowered)
        and "<body" in lowered
        and "</body>" in lowered
        and "</html>" in lowered
        and "```" not in lowered
    )


def site_richness_score(html: str) -> dict[str, Any]:
    """Objective 0-100 richness score for a site artifact (higher is richer).

    Rewards distinct sections, real interactivity, motion/visuals, library use,
    and content depth. Used to select the best candidate and to flag thin output.
    """

    lowered = html.lower()

    def occurrences(*needles: str) -> int:
        return sum(lowered.count(needle) for needle in needles)

    sections = occurrences("<section", "<article", "<header", "<footer", "<nav") + len(
        re.findall(r"""\sid\s*=\s*["']""", lowered)
    )
    interactivity = occurrences(
        "onclick", "addeventlistener", "<button", "<input", "<form", 'href="#'
    )
    motion = occurrences("@keyframes", "requestanimationframe", "transition", "<canvas", "<svg")
    libraries = len(
        re.findall(
            r"""(?:<script[^>]+src|<link[^>]+href)\s*=\s*["'][^"']*"""
            r"(?:cdn|unpkg|jsdelivr|googleapis|tailwind|three|gsap|lucide)",
            lowered,
        )
    )
    headings = occurrences("<h1", "<h2", "<h3")
    byte_len = len(html)

    score = round(
        min(sections, 8) / 8 * 25
        + min(interactivity, 10) / 10 * 25
        + min(motion, 8) / 8 * 20
        + min(libraries, 4) / 4 * 15
        + min(byte_len / 12000, 1.0) * 8
        + min(headings, 6) / 6 * 7
    )
    score = max(0, min(100, score))
    level = "high" if score >= RICH_SITE_TARGET else "medium" if score >= RICH_SITE_MIN else "low"
    return {
        "score": score,
        "level": level,
        "signals": {
            "sections": sections,
            "interactivity": interactivity,
            "motion": motion,
            "libraries": libraries,
            "headings": headings,
            "bytes": byte_len,
        },
    }


def _browser_body_text(browser: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("desktop", "mobile"):
        details = browser.get(key, {})
        if isinstance(details, dict):
            parts.append(str(details.get("bodyText", "")))
    return "\n".join(parts)


def _number_tokens(text: str) -> list[str]:
    return re.findall(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b", text)


def _has_verified_data_marker(lowered_html: str) -> bool:
    return (
        'data-provenance="verified"' in lowered_html
        or "chorus-data-provenance" in lowered_html
        or "data-source-verified" in lowered_html
    )


def _mentions_simulated_data(lowered_html: str) -> bool:
    return any(token in lowered_html for token in ("simulated", "mock data", "fake data"))


def _acceptance_evidence(
    *,
    requirement_id: str,
    checks: dict[str, bool],
    browser: dict[str, Any],
    number_count: int,
    table_rows: int,
    large_blank_count: int,
) -> dict[str, Any]:
    if requirement_id == "browser_renders_without_console_errors":
        return {
            "console_errors": browser.get("console_errors", []),
            "passed": checks.get(requirement_id, False),
        }
    if requirement_id == "no_large_blank_panels":
        return {"large_blank_panels": large_blank_count}
    if requirement_id in {
        "orderbook_rows",
        "volume_orderflow_display",
        "trade_ticket_controls",
    }:
        desktop = dict(browser.get("desktop", {}))
        return {
            "number_tokens": number_count,
            "table_rows": table_rows,
            "button_count": desktop.get("buttonCount", 0),
            "input_count": desktop.get("inputCount", 0),
            "select_count": desktop.get("selectCount", 0),
        }
    if requirement_id == "ticket_interaction_updates_state":
        return dict(browser.get("interactions", {}))
    if requirement_id == "active_market_ticks":
        return dict(browser.get("interactions", {}))
    if requirement_id == "real_data_provenance":
        return {
            "verified_marker_required": True,
            "note": "real data requires a verified data-source artifact",
        }
    return {"passed": checks.get(requirement_id, False)}


def _risk_flags_for_failed_requirements(failed: list[str]) -> list[str]:
    mapping = {
        "browser_renders_without_console_errors": "console_errors",
        "no_large_blank_panels": "blank_large_panel",
        "orderbook_rows": "missing_orderbook_rows",
        "trade_ticket_controls": "missing_trade_ticket_controls",
        "volume_orderflow_display": "missing_volume_orderflow_display",
        "account_position_panel": "missing_account_position_panel",
        "ticket_interaction_updates_state": "missing_trade_ticket_interaction",
        "active_market_ticks": "missing_active_market_ticks",
        "real_data_provenance": "unproven_real_data",
    }
    flags = ["failed_acceptance_contract"] if failed else []
    flags.extend(mapping.get(item, f"failed_{item}") for item in failed)
    return list(dict.fromkeys(flags))


def site_trust_score(
    validation: ArtifactValidation,
    tool_summary: dict[str, Any],
) -> dict[str, Any]:
    checks = validation.checks
    weights = {
        "html_complete": 15,
        "artifact_written": 10,
        "browser_rendered": 15,
        "dom_visible": 10,
        "console_clean": 10,
        "requested_tech_present": 10,
        "size_ok": 5,
        "requirements_passed": 15,
        "no_large_blank_panels": 5,
        "canvas_nonblank": 5,
    }
    score = sum(weight for key, weight in weights.items() if checks.get(key, False))
    if not checks.get("browser_rendered", False):
        score = min(score + 10, 85)
    richness = int((validation.details or {}).get("richness", {}).get("score", 0))
    if richness >= RICH_SITE_TARGET:
        score = min(score + 5, 100)
    elif richness and richness < RICH_SITE_MIN:
        score = max(score - 10, 0)
    if not validation.passed:
        score = min(score, 49)
    if not tool_summary.get("total", 0):
        score = min(score, 69)
    hard_flags = {
        "console_errors",
        "failed_acceptance_contract",
        "unproven_real_data",
        "missing_trade_ticket_interaction",
        "blank_large_panel",
    }
    if any(flag in hard_flags for flag in validation.risk_flags):
        score = min(score, 64)
    level = "high"
    if score < 70:
        level = "medium"
    if score < 50:
        level = "low"
    return {
        "score": max(0, min(100, score)),
        "level": level,
        "checks": dict(checks),
        "risk_flags": list(validation.risk_flags),
    }


def build_document_artifact(
    *,
    run_dir: Path,
    run_id: str,
    goal: str,
    candidate_texts: list[str],
    events_path: Path,
) -> ArtifactBuildResult:
    """Extract, write, and validate one document artifact from candidate text."""

    del goal  # documents share one validator; goal is kept for interface parity
    document = ""
    selected_index = -1
    for index, text in enumerate(candidate_texts):
        candidate = extract_document(text)
        if candidate:
            document = candidate
            selected_index = index
            break

    if not document:
        validation = ArtifactValidation(
            kind="document",
            passed=False,
            summary="No usable document artifact found.",
            checks={
                "content_present": False,
                "artifact_written": False,
                "fences_balanced": False,
                "min_length": False,
                "not_truncated": False,
            },
            risk_flags=("missing_document_artifact",),
        )
        _write_document_validation(run_dir, validation)
        _emit_tool_result(
            events_path,
            run_id,
            tool="extract_document_artifact",
            ok=False,
            result=validation.to_dict(),
            error=validation.summary,
        )
        return ArtifactBuildResult(written=False, validation=validation)

    _emit_tool_result(
        events_path,
        run_id,
        tool="extract_document_artifact",
        ok=True,
        result={"candidate_index": selected_index, "chars": len(document)},
    )
    document_path = run_dir / "document.md"
    start = perf_counter()
    document_path.write_text(document, encoding="utf-8")
    _emit_tool_result(
        events_path,
        run_id,
        tool="write_document_artifact",
        ok=True,
        result={"path": "document.md", "bytes": document_path.stat().st_size},
        latency_ms=_elapsed(start),
    )

    validation = validate_document_artifact(document=document, run_dir=run_dir)
    _write_document_validation(run_dir, validation)
    _emit_tool_result(
        events_path,
        run_id,
        tool="validate_document_artifact",
        ok=validation.passed,
        result=validation.to_dict(),
        error="" if validation.passed else validation.summary,
    )
    return ArtifactBuildResult(
        written=validation.passed,
        validation=validation,
        primary_artifact={
            "kind": "document",
            "path": "document.md",
            "href": "document.md",
            "description": "generated document",
        },
    )


def validate_document_artifact(*, document: str, run_dir: Path) -> ArtifactValidation:
    text = document.strip()
    content_present = bool(text)
    fences_balanced = text.count("```") % 2 == 0
    min_length = len(text) >= DOCUMENT_MIN_LENGTH
    not_truncated = fences_balanced and not text.endswith((",", "-", "(", "[", "{", "*", "#"))
    checks = {
        "content_present": content_present,
        "artifact_written": (run_dir / "document.md").is_file(),
        "fences_balanced": fences_balanced,
        "min_length": min_length,
        "not_truncated": not_truncated,
    }
    risk_flags: list[str] = []
    if not content_present:
        risk_flags.append("missing_document_artifact")
    if not fences_balanced:
        risk_flags.append("unterminated_code_fence")
    if not min_length:
        risk_flags.append("document_too_short")
    if not not_truncated:
        risk_flags.append("document_truncated")
    critical = (
        content_present
        and checks["artifact_written"]
        and fences_balanced
        and min_length
        and not_truncated
    )
    summary = (
        "Document artifact validated." if critical else "Document artifact failed validation."
    )
    return ArtifactValidation(
        kind="document",
        passed=critical,
        summary=summary,
        checks=checks,
        risk_flags=tuple(dict.fromkeys(risk_flags)),
        artifacts=({"kind": "document", "path": "document.md"},),
        details={"chars": len(text)},
    )


def extract_document(text: str) -> str:
    """Return the document body, unwrapping a single complete markdown fence."""

    stripped = text.strip()
    if not stripped:
        return ""
    fence = re.fullmatch(
        r"```[A-Za-z0-9_-]*\s*(.*?)```",
        stripped,
        flags=re.DOTALL,
    )
    if fence:
        return fence.group(1).strip()
    return stripped


def document_trust_score(
    validation: ArtifactValidation,
    tool_summary: dict[str, Any],
) -> dict[str, Any]:
    checks = validation.checks
    weights = {
        "content_present": 25,
        "artifact_written": 20,
        "fences_balanced": 15,
        "min_length": 20,
        "not_truncated": 20,
    }
    score = sum(weight for key, weight in weights.items() if checks.get(key, False))
    if not validation.passed:
        score = min(score, 49)
    if not tool_summary.get("total", 0):
        score = min(score, 69)
    level = "high"
    if score < 70:
        level = "medium"
    if score < 50:
        level = "low"
    return {
        "score": max(0, min(100, score)),
        "level": level,
        "checks": dict(checks),
        "risk_flags": list(validation.risk_flags),
    }


def build_program_artifact(
    *,
    run_dir: Path,
    run_id: str,
    goal: str,
    candidate_texts: list[str],
    events_path: Path,
) -> ArtifactBuildResult:
    """Extract, write, and validate one source-code artifact."""

    del goal
    source = ""
    extension = ".txt"
    selected_index = -1
    for index, text in enumerate(candidate_texts):
        extracted = extract_program(text)
        if extracted:
            source, extension = extracted
            selected_index = index
            break

    if not source:
        validation = ArtifactValidation(
            kind="program",
            passed=False,
            summary="No usable program artifact found.",
            checks={
                "source_present": False,
                "artifact_written": False,
                "min_length": False,
                "syntax_ok": False,
            },
            risk_flags=("missing_program_artifact",),
        )
        _write_program_validation(run_dir, validation)
        _emit_tool_result(
            events_path,
            run_id,
            tool="extract_program_artifact",
            ok=False,
            result=validation.to_dict(),
            error=validation.summary,
        )
        return ArtifactBuildResult(written=False, validation=validation)

    _emit_tool_result(
        events_path,
        run_id,
        tool="extract_program_artifact",
        ok=True,
        result={"candidate_index": selected_index, "chars": len(source), "extension": extension},
    )
    program_dir = run_dir / "program"
    program_dir.mkdir(parents=True, exist_ok=True)
    program_path = program_dir / f"main{extension}"
    start = perf_counter()
    program_path.write_text(source, encoding="utf-8")
    _emit_tool_result(
        events_path,
        run_id,
        tool="write_program_artifact",
        ok=True,
        result={
            "path": program_path.relative_to(run_dir).as_posix(),
            "bytes": program_path.stat().st_size,
        },
        latency_ms=_elapsed(start),
    )
    validation = validate_program_artifact(source=source, extension=extension, run_dir=run_dir)
    _write_program_validation(run_dir, validation)
    _emit_tool_result(
        events_path,
        run_id,
        tool="validate_program_artifact",
        ok=validation.passed,
        result=validation.to_dict(),
        error="" if validation.passed else validation.summary,
    )
    return ArtifactBuildResult(
        written=validation.passed,
        validation=validation,
        primary_artifact={
            "kind": "program",
            "path": program_path.relative_to(run_dir).as_posix(),
            "href": program_path.relative_to(run_dir).as_posix(),
            "description": "generated source artifact",
        },
    )


def extract_program(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped:
        return None
    marker = "=== main"
    if marker in stripped.lower():
        return stripped.split("===", 2)[-1].strip(), ".txt"
    for fenced in re.finditer(
        r"```([A-Za-z0-9_+#.-]*)\s*(.*?)```",
        stripped,
        flags=re.DOTALL,
    ):
        lang = fenced.group(1).strip().lower()
        extension = _LANG_EXT.get(lang, ".txt")
        body = fenced.group(2).strip()
        if body:
            return body, extension
    if len(stripped) >= PROGRAM_MIN_LENGTH and any(
        token in stripped for token in ("def ", "class ", "function ", "const ", "let ")
    ):
        return stripped, ".txt"
    return None


def validate_program_artifact(
    *,
    source: str,
    extension: str,
    run_dir: Path,
) -> ArtifactValidation:
    source_present = bool(source.strip())
    min_length = len(source.strip()) >= PROGRAM_MIN_LENGTH
    syntax_ok = True
    syntax_error = ""
    if extension == ".py" and source_present:
        try:
            ast.parse(source)
        except SyntaxError as exc:
            syntax_ok = False
            syntax_error = f"{exc.msg} at line {exc.lineno}"
    checks = {
        "source_present": source_present,
        "artifact_written": any((run_dir / "program").glob("main.*")),
        "min_length": min_length,
        "syntax_ok": syntax_ok,
    }
    risk_flags: list[str] = []
    if not source_present:
        risk_flags.append("missing_program_artifact")
    if not min_length:
        risk_flags.append("program_too_short")
    if not syntax_ok:
        risk_flags.append("program_syntax_error")
    passed = all(checks.values())
    return ArtifactValidation(
        kind="program",
        passed=passed,
        summary="Program artifact validated." if passed else "Program artifact failed validation.",
        checks=checks,
        risk_flags=tuple(risk_flags),
        artifacts=({"kind": "program", "path": f"program/main{extension}"},),
        details={"chars": len(source), "extension": extension, "syntax_error": syntax_error},
    )


def program_trust_score(
    validation: ArtifactValidation,
    tool_summary: dict[str, Any],
) -> dict[str, Any]:
    checks = validation.checks
    weights = {
        "source_present": 25,
        "artifact_written": 25,
        "min_length": 20,
        "syntax_ok": 30,
    }
    score = sum(weight for key, weight in weights.items() if checks.get(key, False))
    if not validation.passed:
        score = min(score, 49)
    if not tool_summary.get("total", 0):
        score = min(score, 69)
    level = "high"
    if score < 70:
        level = "medium"
    if score < 50:
        level = "low"
    return {
        "score": max(0, min(100, score)),
        "level": level,
        "checks": dict(checks),
        "risk_flags": list(validation.risk_flags),
    }


def _write_validation(run_dir: Path, validation: ArtifactValidation) -> None:
    (run_dir / "site_validation.json").write_text(
        json.dumps(validation.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


def _write_document_validation(run_dir: Path, validation: ArtifactValidation) -> None:
    (run_dir / "document_validation.json").write_text(
        json.dumps(validation.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


def _write_program_validation(run_dir: Path, validation: ArtifactValidation) -> None:
    (run_dir / "program_validation.json").write_text(
        json.dumps(validation.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


def _browser_render_check(*, run_dir: Path, run_id: str) -> dict[str, Any]:
    site_path = run_dir / "site" / "index.html"
    script = _browser_check_script(run_dir)
    if not script:
        return _skipped_browser_check("playwright_unavailable")
    screenshots = run_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    command = [
        "node",
        str(script),
        str(site_path),
        str(screenshots / "desktop.png"),
        str(screenshots / "mobile.png"),
    ]
    start = perf_counter()
    try:
        proc = subprocess.run(
            command,
            cwd=script.parent,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _skipped_browser_check(type(exc).__name__)
    latency_ms = _elapsed(start)
    if proc.returncode != 0:
        return {
            "checks": {
                "browser_rendered": False,
                "dom_visible": False,
                "console_clean": False,
                "canvas_nonblank": False,
            },
            "risk_flags": ["browser_check_failed"],
            "latency_ms": latency_ms,
            "stderr": proc.stderr[-1000:],
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _skipped_browser_check("browser_json_invalid")
    payload["latency_ms"] = latency_ms
    return payload


def _browser_check_script(run_dir: Path) -> Path | None:
    ui_dir = Path(__file__).resolve().parents[2] / "chorus" / "ui" / "agent-map"
    playwright_dir = ui_dir / "node_modules" / "playwright"
    if not playwright_dir.is_dir():
        return None
    script = run_dir / "browser_check.mjs"
    playwright_import = (playwright_dir / "index.mjs").as_posix()
    script.write_text(
        _BROWSER_CHECK_JS.replace("__PLAYWRIGHT_IMPORT__", playwright_import),
        encoding="utf-8",
    )
    return script


def _skipped_browser_check(reason: str) -> dict[str, Any]:
    return {
        "checks": {
            "browser_rendered": False,
            "dom_visible": False,
            "console_clean": True,
            "canvas_nonblank": True,
        },
        "risk_flags": [reason],
        "skipped": True,
    }


def _canvas_requirement_met(*, html: str, goal: str) -> bool:
    if not _requires_canvas(goal):
        return True
    return "<canvas" in html.lower()


def _requires_canvas(goal: str) -> bool:
    lowered = goal.lower()
    return "three.js" in lowered or "threejs" in lowered or "canvas" in lowered or "3d" in lowered


def _requested_tech_present(*, html: str, goal: str) -> bool:
    lowered_goal = goal.lower()
    lowered_html = html.lower()
    if "three.js" in lowered_goal or "threejs" in lowered_goal:
        return "three" in lowered_html
    if "animation" in lowered_goal:
        return (
            "requestanimationframe" in lowered_html
            or "@keyframes" in lowered_html
            or "animation:" in lowered_html
            or "<canvas" in lowered_html
        )
    return True


def _emit_tool_result(
    events_path: Path,
    run_id: str,
    *,
    tool: str,
    ok: bool,
    result: dict[str, Any],
    error: str = "",
    latency_ms: float = 0.0,
) -> None:
    metadata = {"node_id": "site_artifact"}
    append_run_event(
        events_path,
        run_id,
        "tool_call_requested",
        {"tool": tool, "args": {}, "metadata": metadata},
    )
    append_run_event(
        events_path,
        run_id,
        "policy_decision",
        {"tool": tool, "decision": {"decision": "allow"}, "metadata": metadata},
    )
    append_run_event(
        events_path,
        run_id,
        "tool_result",
        {
            "tool": tool,
            "result": {
                "tool": tool,
                "ok": ok,
                "result": result,
                "error": error,
                "latency_ms": round(latency_ms, 3),
            },
            "metadata": metadata,
        },
    )


def append_run_event(
    events_path: Path,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    seq = _last_seq(events_path) + 1
    row = {
        "event_id": f"evt_{uuid4().hex}",
        "run_id": run_id,
        "seq": seq,
        "timestamp": datetime.now(UTC).isoformat(),
        "type": event_type,
        "payload": payload,
    }
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _last_seq(events_path: Path) -> int:
    if not events_path.is_file():
        return 0
    seq = 0
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        seq = max(seq, int(row.get("seq", 0)))
    return seq


def _elapsed(start: float) -> float:
    return (perf_counter() - start) * 1000


_BROWSER_CHECK_JS = r"""
import { chromium } from 'file:///__PLAYWRIGHT_IMPORT__';

const [htmlPath, desktopPath, mobilePath] = process.argv.slice(2);
const fileUrl = 'file:///' + htmlPath.replace(/\\/g, '/');
const errors = [];

const browser = await chromium.launch({ headless: true });

async function inspect(path, viewport) {
  const page = await browser.newPage({ viewport });
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(fileUrl, { waitUntil: 'domcontentloaded', timeout: 10000 });
  await page.waitForTimeout(700);
  const interactions = await exerciseTradingControls(page);
  const details = await page.evaluate(() => {
    const bodyText = document.body?.innerText?.trim() ?? '';
    const elements = document.body?.querySelectorAll('*').length ?? 0;
    const canvases = Array.from(document.querySelectorAll('canvas'));
    const canvasNonBlank =
      canvases.length === 0 ||
      canvases.some((canvas) => canvas.width > 0 && canvas.height > 0);
    const buttonTexts = Array.from(document.querySelectorAll('button, [role="button"]'))
      .map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim())
      .filter(Boolean)
      .slice(0, 30);
    const largeBlankPanels = Array.from(document.body?.querySelectorAll('*') ?? [])
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width * rect.height < 120000) return false;
        if (rect.width < 220 || rect.height < 160) return false;
        if (el.querySelector('canvas, svg, img, video, table, tr, li')) return false;
        const text = (el.innerText || '').trim();
        return text.length < 24;
      })
      .length;
    return {
      title: document.title,
      bodyText: bodyText.slice(0, 6000),
      bodyTextLength: bodyText.length,
      elementCount: elements,
      canvasCount: canvases.length,
      canvasNonBlank,
      buttonCount: document.querySelectorAll('button, [role="button"]').length,
      inputCount: document.querySelectorAll('input, textarea').length,
      selectCount: document.querySelectorAll('select').length,
      tableRowCount: document.querySelectorAll('tr, [role="row"]').length,
      buttonTexts,
      largeBlankPanels,
    };
  });
  await page.screenshot({ path, fullPage: true });
  await page.close();
  return { ...details, interactions };
}

async function exerciseTradingControls(page) {
  const before = await page.evaluate(() => document.body?.innerText ?? '');
  const firstInput = page.locator('input, textarea').first();
  let quantityChanged = false;
  try {
    if (await firstInput.count()) {
      await firstInput.fill('3', { timeout: 700 });
      quantityChanged = true;
    }
  } catch {
    quantityChanged = false;
  }

  const buy = page.getByRole('button', { name: /buy/i }).first();
  const sell = page.getByRole('button', { name: /sell/i }).first();
  let buyClicked = false;
  let sellClicked = false;
  try {
    if (await buy.count()) {
      await buy.click({ timeout: 900 });
      buyClicked = true;
    }
  } catch {
    buyClicked = false;
  }
  await page.waitForTimeout(300);
  const afterBuy = await page.evaluate(() => document.body?.innerText ?? '');
  try {
    if (await sell.count()) {
      await sell.click({ timeout: 900 });
      sellClicked = true;
    }
  } catch {
    sellClicked = false;
  }
  await page.waitForTimeout(300);
  const afterSell = await page.evaluate(() => document.body?.innerText ?? '');
  await page.waitForTimeout(450);
  const afterTick = await page.evaluate(() => document.body?.innerText ?? '');
  return {
    quantityChanged,
    buyClicked,
    sellClicked,
    tradeStateChanged: before !== afterBuy || afterBuy !== afterSell,
    marketTicksChanged: afterSell !== afterTick,
  };
}

const desktop = await inspect(desktopPath, { width: 1440, height: 1000 });
const mobile = await inspect(mobilePath, { width: 390, height: 844, isMobile: true });
await browser.close();

const domVisible = desktop.elementCount > 3 || desktop.bodyTextLength > 20;
const payload = {
  checks: {
    browser_rendered: true,
    dom_visible: domVisible,
    console_clean: errors.length === 0,
    canvas_nonblank: desktop.canvasNonBlank || mobile.canvasNonBlank,
  },
  risk_flags: errors.length ? ['console_errors'] : [],
  console_errors: errors.slice(0, 10),
  desktop,
  mobile,
  interactions: desktop.interactions,
};

console.log(JSON.stringify(payload));
"""
