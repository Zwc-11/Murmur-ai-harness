import { useCallback, useEffect, useId, useMemo, useState, type KeyboardEvent } from "react";
import type { PreviewResult } from "./types";

interface Props {
  result: PreviewResult | null;
  playbackComplete: boolean;
  planning: boolean;
  revealed?: boolean;
}

type Tab = "summary" | "timeline" | "report" | "lanes" | "gates" | "artifacts";

const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "timeline", label: "Timeline" },
  { id: "report", label: "Full report" },
  { id: "lanes", label: "Lanes" },
  { id: "gates", label: "Gate log" },
  { id: "artifacts", label: "Artifacts" },
];

function formatDuration(ms: number): string {
  if (!ms) return "0ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function RunResultsPanel({ result, playbackComplete, planning, revealed = false }: Props) {
  const [tab, setTab] = useState<Tab>("summary");
  const [open, setOpen] = useState(true);
  const baseId = useId();

  useEffect(() => {
    if (playbackComplete && result) {
      setOpen(true);
      setTab("summary");
    }
  }, [playbackComplete, result]);

  const emptyMessage = useMemo(() => {
    if (planning) return "Planning workflow from your task.";
    if (!playbackComplete) {
      return "Run agents to open gates. The winning output lands here when playback finishes.";
    }
    return "No result payload yet.";
  }, [planning, playbackComplete]);

  const onTabKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const delta = event.key === "ArrowRight" ? 1 : -1;
      const next = (index + delta + TABS.length) % TABS.length;
      const nextId = TABS[next].id;
      setTab(nextId);
      document.getElementById(`${baseId}-tab-${nextId}`)?.focus();
    },
    [baseId],
  );

  if (!open) {
    return (
      <div className="am-results am-results--collapsed">
        <button
          type="button"
          className="am-results__reopen"
          onClick={() => setOpen(true)}
          aria-expanded="false"
        >
          Show run result
        </button>
      </div>
    );
  }

  const panelId = `${baseId}-panel`;
  const hasResult = Boolean(result && playbackComplete);
  const sitePreview =
    result?.primary_artifact?.kind === "site_preview"
      ? result.primary_artifact
      : result?.artifacts?.find((artifact) => artifact.kind === "site_preview");
  const documentArtifact =
    result?.primary_artifact?.kind === "document"
      ? result.primary_artifact
      : result?.artifacts?.find((artifact) => artifact.kind === "document");
  const documentPreview = result?.document_preview ?? "";
  const programArtifact =
    result?.primary_artifact?.kind === "program"
      ? result.primary_artifact
      : result?.artifacts?.find((artifact) => artifact.kind === "program");
  const programPreview = result?.program_preview ?? "";
  const validation = result?.validation_summary;
  const acceptance = result?.acceptance_summary;
  const failedRequirements =
    result?.failed_requirements ?? acceptance?.failed_requirements ?? [];
  const repairIterations = result?.repair_iterations ?? [];
  const validationChecks = validation?.checks
    ? Object.entries(validation.checks).filter(([, value]) => typeof value === "boolean")
    : [];
  const richness = validation?.details?.richness;
  const riskFlags = validation?.risk_flags ?? [];

  return (
    <section
      className={`am-results${revealed ? " am-results--revealed" : ""}`}
      aria-label="Run results"
    >
      <header className="am-results__hd">
        <div>
          <h2 className="am-results__title">Run result</h2>
          <p className="am-results__meta">
            {result?.mode === "preview" ? "Preview playback" : "Live run"}
            {result?.run_id ? ` - ${result.run_id}` : ""}
            {result?.winner_label ? ` - winner ${result.winner_label}` : ""}
          </p>
        </div>
        <button
          type="button"
          className="am-btn am-results__hide"
          onClick={() => setOpen(false)}
          aria-label="Hide run result panel"
        >
          Hide panel
        </button>
      </header>

      {!hasResult ? (
        <p className="am-results__empty" aria-live="polite" aria-busy={planning}>
          {emptyMessage}
        </p>
      ) : (
        <>
          <div className="am-results__tabs" role="tablist" aria-label="Result sections">
            {TABS.map(({ id, label }, index) => {
              const tabId = `${baseId}-tab-${id}`;
              return (
                <button
                  key={id}
                  id={tabId}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  aria-controls={panelId}
                  tabIndex={tab === id ? 0 : -1}
                  className={`am-results__tab${tab === id ? " am-results__tab--active" : ""}`}
                  onClick={() => setTab(id)}
                  onKeyDown={(event) => onTabKeyDown(event, index)}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <div
            className="am-results__body"
            id={panelId}
            role="tabpanel"
            aria-labelledby={`${baseId}-tab-${tab}`}
            tabIndex={0}
          >
            {tab === "summary" && (
              <div className="am-results__summary" aria-live="polite">
                <p className="am-results__lead">{result.summary}</p>
                {acceptance ? (
                  <div className="am-results__validation">
                    <span
                      className={
                        acceptance.passed
                          ? "am-results__validation-status am-results__validation-status--pass"
                          : "am-results__validation-status am-results__validation-status--fail"
                      }
                    >
                      {acceptance.passed ? "acceptance passed" : "acceptance failed"}
                    </span>
                    {acceptance.winner_reason ? <p>{acceptance.winner_reason}</p> : null}
                    {typeof acceptance.repair_count === "number" && acceptance.repair_count > 0 ? (
                      <p>repair iterations: {acceptance.repair_count}</p>
                    ) : null}
                    {failedRequirements.length ? (
                      <ul className="am-results__risks">
                        {failedRequirements.map((requirement) => (
                          <li key={requirement} className="am-results__risk">
                            {requirement.replace(/_/g, " ")}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {repairIterations.length ? (
                      <ul>
                        {repairIterations.map((iteration) => (
                          <li
                            key={iteration.iteration ?? iteration.summary}
                            className={iteration.passed ? "is-pass" : "is-fail"}
                          >
                            repair {iteration.iteration}: {iteration.summary}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
                {sitePreview ? (
                  <div className="am-results__site">
                    <div className="am-results__site-actions">
                      <a
                        className="am-results__site-open"
                        href={sitePreview.href}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open website
                      </a>
                      <span>{sitePreview.path}</span>
                    </div>
                    <iframe
                      className="am-results__site-frame"
                      src={sitePreview.href}
                      title="Generated website preview"
                      loading="lazy"
                    />
                  </div>
                ) : null}
                {!sitePreview && documentArtifact ? (
                  <div className="am-results__document">
                    <div className="am-results__document-actions">
                      <a
                        className="am-results__document-open"
                        href={documentArtifact.href}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open document
                      </a>
                      <span>{documentArtifact.path}</span>
                    </div>
                    {documentPreview ? (
                      <pre className="am-results__document-text">{documentPreview}</pre>
                    ) : null}
                  </div>
                ) : null}
                {!sitePreview && programArtifact ? (
                  <div className="am-results__document">
                    <div className="am-results__document-actions">
                      <a
                        className="am-results__document-open"
                        href={programArtifact.href}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open program
                      </a>
                      <span>{programArtifact.path}</span>
                    </div>
                    {programPreview ? (
                      <pre className="am-results__document-text">{programPreview}</pre>
                    ) : null}
                  </div>
                ) : null}
                {validation ? (
                  <div className="am-results__validation">
                    <span
                      className={
                        validation.passed
                          ? "am-results__validation-status am-results__validation-status--pass"
                          : "am-results__validation-status am-results__validation-status--fail"
                      }
                    >
                      {validation.passed ? "validated" : "failed validation"}
                    </span>
                    {typeof richness?.score === "number" ? (
                      <div className="am-results__richness">
                        <span className="am-results__richness-score">
                          richness {richness.score}/100
                        </span>
                        {richness.level ? (
                          <span className="am-results__richness-level">{richness.level}</span>
                        ) : null}
                      </div>
                    ) : null}
                    {validation.summary ? <p>{validation.summary}</p> : null}
                    {riskFlags.length ? (
                      <ul className="am-results__risks">
                        {riskFlags.map((flag) => (
                          <li key={flag} className="am-results__risk">
                            {flag.replace(/_/g, " ")}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {validationChecks.length ? (
                      <ul>
                        {validationChecks.map(([key, value]) => (
                          <li key={key} className={value ? "is-pass" : "is-fail"}>
                            {key.replace(/_/g, " ")}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
                {result.note ? <p className="am-results__note">{result.note}</p> : null}
              </div>
            )}
            {tab === "timeline" && (
              <ol className="am-results__timeline">
                {(result.timeline ?? []).map((entry, index) => (
                  <li
                    key={`${entry.step}-${index}`}
                    className={
                      entry.status === "pass"
                        ? "am-results__tl am-results__tl--pass"
                        : "am-results__tl am-results__tl--fail"
                    }
                  >
                    <div className="am-results__tl-head">
                      <span className="am-results__tl-step">{entry.step}</span>
                      <span className="am-results__tl-time">{formatDuration(entry.duration_ms)}</span>
                    </div>
                    <div className="am-results__tl-meta">
                      {entry.tokens ? <span>{entry.tokens} tok</span> : null}
                      {entry.cost_usd ? <span>${entry.cost_usd.toFixed(4)}</span> : null}
                      <span>{entry.status}</span>
                    </div>
                    {entry.thinking ? (
                      <details className="am-results__tl-think">
                        <summary>agent thinking</summary>
                        <pre>{entry.thinking}</pre>
                      </details>
                    ) : null}
                    {entry.detail ? (
                      <p className="am-results__tl-detail">{entry.detail}</p>
                    ) : null}
                  </li>
                ))}
                {!result.timeline?.length ? (
                  <li className="am-results__tl">
                    <span className="am-results__tl-step">
                      Timeline appears after a live run finishes.
                    </span>
                  </li>
                ) : null}
              </ol>
            )}
            {tab === "report" && <pre className="am-results__pre">{result.report}</pre>}
            {tab === "lanes" && (
              <ul className="am-results__lanes">
                {(result.lane_previews ?? []).map((lane) => (
                  <li
                    key={lane.id}
                    className={
                      lane.selected
                        ? "am-results__lane am-results__lane--winner"
                        : "am-results__lane"
                    }
                  >
                    <span className="am-results__lane-label">
                      {lane.label}
                      {lane.selected ? " - selected" : ""}
                    </span>
                    <p className="am-results__lane-preview">{lane.preview}</p>
                  </li>
                ))}
                {!result.lane_previews?.length ? (
                  <li className="am-results__lane">
                    <span className="am-results__lane-label">Single-path workflow</span>
                    <p className="am-results__lane-preview">{result.summary}</p>
                  </li>
                ) : null}
              </ul>
            )}
            {tab === "gates" && (
              <ol className="am-results__gates">
                {(result.gate_log ?? []).map((entry, index) => (
                  <li key={`${entry.gate}-${entry.type}-${index}`}>
                    <span className="am-results__gate-type">
                      {entry.type.replace(/_/g, " ")}
                    </span>
                    <span className="am-results__gate-id">{entry.gate}</span>
                    {entry.message ? (
                      <span className="am-results__gate-msg">{entry.message}</span>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
            {tab === "artifacts" && (
              <ul className="am-results__artifacts">
                {(result.artifacts ?? []).map((artifact) => (
                  <li key={`${artifact.kind}-${artifact.path}`}>
                    <a href={artifact.href} target="_blank" rel="noreferrer">
                      {artifact.kind}
                    </a>
                    {artifact.description ? <span>{artifact.description}</span> : null}
                  </li>
                ))}
                {!result.artifacts?.length ? (
                  <li>
                    <span>No artifacts recorded.</span>
                  </li>
                ) : null}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
