import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  ReactFlowProvider,
  useReactFlow,
  applyNodeChanges,
  type Node,
  type Edge,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { OperatorNode, AgentNode } from "./nodes";
import { FlowEdge } from "./FlowEdge";
import { graphToFlow } from "./graph";
import { ReducedMotionProvider } from "./hooks/useReducedMotion";
import { RunResultsPanel } from "./RunResultsPanel";
import type { AgentMapPayload, MapEdgeData, MapNodeData, PlaybackStep, PreviewResult } from "./types";

const nodeTypes = { operator: OperatorNode, agent: AgentNode };
const edgeTypes = { flow: FlowEdge };

interface Props {
  payload: Record<string, unknown>;
}

interface RunOptions {
  command: string;
  provider: string;
  model: string;
  budget_usd: number;
  use_model: boolean;
}

function FitOnGraphChange({ graphKey }: { graphKey: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const timer = window.setTimeout(
      () => fitView({ padding: 0.16, maxZoom: 1.05, duration: 250 }),
      120,
    );
    return () => window.clearTimeout(timer);
  }, [graphKey, fitView]);
  return null;
}

function edgeTouchesOpenedGate(edge: Edge, opened: Set<string>): boolean {
  const edgeGate = (edge.data as MapEdgeData)?.gate ?? "";
  return (
    opened.has(edge.source) ||
    opened.has(edge.target) ||
    (edgeGate !== "" && opened.has(edgeGate))
  );
}

function flowEdgesForOpenedGates(
  edges: Edge[],
  opened: Set<string>,
  options?: { surgeGate?: string; opening?: boolean },
): Edge[] {
  const lowFx = opened.size > 5;
  const surgeGate = options?.opening && options.surgeGate ? options.surgeGate : "";
  return edges.map((edge) => {
    const flowing = edgeTouchesOpenedGate(edge, opened);
    const edgeGate = (edge.data as MapEdgeData)?.gate ?? "";
    const surging =
      Boolean(surgeGate) &&
      (edge.source === surgeGate || edge.target === surgeGate || edgeGate === surgeGate);
    return {
      ...edge,
      data: {
        ...(edge.data as object),
        active: flowing,
        callsPerSecond: flowing ? (surging ? 14 : 10) : 0,
        lowFx: flowing && lowFx,
      },
    };
  });
}

function readRunOptions(): RunOptions {
  const commandEl = document.getElementById("am-command") as HTMLInputElement | null;
  const providerEl = document.getElementById("am-provider") as HTMLInputElement | null;
  const modelEl = document.getElementById("am-model") as HTMLInputElement | null;
  const budgetEl = document.getElementById("am-budget") as HTMLInputElement | null;
  const useModelEl = document.getElementById("am-use-model") as HTMLInputElement | null;
  const budget = Number.parseFloat(budgetEl?.value ?? "0.50");
  return {
    command: commandEl?.value.trim() ?? "",
    provider: providerEl?.value.trim() ?? "",
    model: modelEl?.value.trim() ?? "",
    budget_usd: Number.isFinite(budget) ? budget : 0.50,
    use_model: Boolean(useModelEl?.checked),
  };
}

async function planFromTaskText(
  task: string,
  options: RunOptions = readRunOptions(),
): Promise<AgentMapPayload | null> {
  const res = await fetch("/api/agent-map/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, ...options }),
  });
  if (!res.ok) return null;
  return (await res.json()) as AgentMapPayload;
}

async function runTaskBlocking(
  task: string,
  options: RunOptions = readRunOptions(),
): Promise<AgentMapPayload | null> {
  const res = await fetch("/api/agent-map/run-blocking", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, ...options }),
  });
  if (!res.ok) return null;
  return (await res.json()) as AgentMapPayload;
}

interface StreamedEvent {
  type?: string;
  payload?: { node_id?: string };
}

// Start the run in the background and stream its events.jsonl live; resolve with the final
// payload when the run finishes. Falls back to a single blocking request if SSE is unavailable.
async function runTaskStreaming(
  task: string,
  options: RunOptions,
  onProgress: (event: StreamedEvent) => void,
): Promise<AgentMapPayload | null> {
  let started: { run_id?: string } | null = null;
  try {
    const res = await fetch("/api/agent-map/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, ...options }),
    });
    if (res.ok) started = (await res.json()) as { run_id?: string };
  } catch {
    started = null;
  }
  if (!started?.run_id || typeof EventSource === "undefined") {
    return runTaskBlocking(task, options);
  }
  const runId = started.run_id;
  return new Promise((resolve) => {
    const source = new EventSource(`/api/agent-map/stream?run_id=${encodeURIComponent(runId)}`);
    let settled = false;
    const finish = (payload: AgentMapPayload | null) => {
      if (settled) return;
      settled = true;
      source.close();
      resolve(payload);
    };
    source.onmessage = (event) => {
      try {
        onProgress(JSON.parse(event.data) as StreamedEvent);
      } catch {
        /* ignore non-JSON heartbeats */
      }
    };
    source.addEventListener("result", (event) => {
      try {
        finish(JSON.parse((event as MessageEvent).data) as AgentMapPayload);
      } catch {
        finish(null);
      }
    });
    source.addEventListener("run_error", () => finish(null));
    source.addEventListener("done", () => finish(null));
    source.onerror = () => {
      // Connection dropped before a result: fall back to a blocking request.
      if (!settled) {
        settled = true;
        source.close();
        runTaskBlocking(task, options).then(resolve);
      }
    };
  });
}

function liveStatusLabel(event: StreamedEvent): string {
  const type = (event.type ?? "").replace(/_/g, " ");
  const node = event.payload?.node_id;
  if (!type) return "running agents";
  return node ? `${type}: ${node}` : type;
}

function AgentMapCanvas({ data }: { data: AgentMapPayload }) {
  const { setCenter, getNode } = useReactFlow();
  const [playbackIndex, setPlaybackIndex] = useState(-1);
  const [status, setStatus] = useState("gates closed");
  const [playbackSteps, setPlaybackSteps] = useState(data.playback ?? []);
  const [graphKey, setGraphKey] = useState("initial");
  const playbackTimer = useRef<number | null>(null);
  const openedGatesRef = useRef<Set<string>>(new Set());
  const lastPannedGateRef = useRef("");
  const [openGateCount, setOpenGateCount] = useState(0);
  const [workflowMeta, setWorkflowMeta] = useState({
    name: data.workflow_name ?? "workflow",
    description: data.workflow_description ?? "",
  });
  const [workflowSize, setWorkflowSize] = useState(data.workflow_size?.reason ?? "");
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(
    data.preview_result ?? null,
  );
  const [playbackComplete, setPlaybackComplete] = useState(false);
  const [planning, setPlanning] = useState(false);
  const plannedOnce = useRef(false);

  const baseFlow = useMemo(() => graphToFlow(data.graph), [data.graph]);
  const [nodes, setNodes] = useState(baseFlow.nodes);
  const [edges, setEdges] = useState(baseFlow.edges);

  const applyGraph = useCallback(
    (
      graph: AgentMapPayload["graph"],
      steps: PlaybackStep[],
      meta?: { name?: string; description?: string },
    ) => {
      const flow = graphToFlow(graph);
      openedGatesRef.current = new Set();
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setPlaybackSteps(steps.length ? steps : []);
      setPlaybackIndex(-1);
      setStatus("gates closed · press Play run");
      setGraphKey(`${meta?.name ?? "workflow"}-${flow.nodes.length}-${Date.now()}`);
      if (meta?.name) {
        setWorkflowMeta({ name: meta.name, description: meta.description ?? "" });
      }
      setWorkflowSize("");
      setPreviewResult(null);
      setPlaybackComplete(false);
    },
    [],
  );

  const loadFromPlan = useCallback(
    (planned: AgentMapPayload) => {
      const flow = graphToFlow(planned.graph);
      openedGatesRef.current = new Set();
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setPlaybackSteps(planned.playback ?? []);
      setPlaybackIndex(-1);
      setStatus("gates closed · press Play run");
      setGraphKey(
        `${planned.workflow_name ?? "workflow"}-${flow.nodes.length}-${Date.now()}`,
      );
      setWorkflowMeta({
        name: planned.workflow_name ?? "workflow",
        description: planned.workflow_description ?? "",
      });
      setWorkflowSize(planned.workflow_size?.reason ?? "");
      setPreviewResult(planned.preview_result ?? null);
      setPlaybackComplete(false);
    },
    [],
  );

  useEffect(() => {
    applyGraph(data.graph, data.playback ?? [], {
      name: data.workflow_name,
      description: data.workflow_description,
    });
    setPreviewResult(data.preview_result ?? null);
  }, [data.graph, data.playback, data.workflow_name, data.workflow_description, data.preview_result, applyGraph]);

  useEffect(() => {
    if (plannedOnce.current) return;
    const taskEl = document.getElementById("am-task") as HTMLTextAreaElement | null;
    const task = taskEl?.value.trim() ?? "";
    if (!task) return;
    plannedOnce.current = true;
    setPlanning(true);
    void planFromTaskText(task, readRunOptions())
      .then((planned) => {
        if (planned?.graph) loadFromPlan(planned);
      })
      .catch(() => {
        setStatus("plan API unavailable · showing embedded graph");
      })
      .finally(() => setPlanning(false));
  }, [loadFromPlan]);

  useEffect(() => {
    const onLoad = (event: Event) => {
      const detail = (event as CustomEvent<AgentMapPayload>).detail;
      if (!detail?.graph) return;
      applyGraph(detail.graph, detail.playback ?? [], {
        name: detail.workflow_name,
        description: detail.workflow_description,
      });
    };
    const onHighlight = (event: Event) => {
      const op = (event as CustomEvent<string>).detail;
      setNodes((prev) =>
        prev.map((node) => ({
          ...node,
          className: (node.data as MapNodeData).op === op ? "am-node-highlight" : "",
        })),
      );
    };
    window.addEventListener("murmur-agent-map-load", onLoad);
    window.addEventListener("murmur-agent-map-highlight", onHighlight);
    return () => {
      window.removeEventListener("murmur-agent-map-load", onLoad);
      window.removeEventListener("murmur-agent-map-highlight", onHighlight);
    };
  }, [applyGraph]);

  useEffect(() => {
    return () => {
      if (playbackTimer.current != null) window.clearInterval(playbackTimer.current);
    };
  }, []);

  useEffect(() => {
    if (playbackIndex < 0) return;
    const step = playbackSteps[playbackIndex];
    if (!step) return;

    const gateId = step.gate || step.node_id;
    const opening = step.type === "gate_opened" || step.type === "workflow_node_started";
    const closing = step.type === "gate_closed" || step.type === "workflow_node_finished";

    setStatus(
      gateId
        ? `${step.type.replace(/_/g, " ")} · ${gateId}`
        : step.message || step.type,
    );

    if (gateId && opening) {
      openedGatesRef.current.add(gateId);
    }
    setOpenGateCount(openedGatesRef.current.size);

    setNodes((prev) =>
      prev.map((node) => {
        const d = node.data as MapNodeData;
        const isGate = node.id === gateId;
        let nodeStatus = d.status;

        if (isGate) {
          if (opening || step.type === "model_call_finished") nodeStatus = "running";
          if (closing) nodeStatus = "pass";
          if (step.type === "workflow_node_failed" || step.type === "workflow_node_quarantined") {
            nodeStatus = "fail";
          }
        }

        const liveThought =
          isGate && step.message ? step.message : d.liveThought ?? d.thinking;

        const classes = [
          openedGatesRef.current.has(node.id) ? "am-node--gate-open" : "",
          isGate && opening ? "am-node--gate-surge" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return {
          ...node,
          className: classes,
          data: { ...d, status: nodeStatus, liveThought },
        };
      }),
    );

    setEdges((prev) =>
      flowEdgesForOpenedGates(prev, openedGatesRef.current, {
        surgeGate: gateId,
        opening,
      }),
    );

    if (gateId && opening && gateId !== lastPannedGateRef.current) {
      lastPannedGateRef.current = gateId;
      const rfNode = getNode(gateId);
      if (rfNode) {
        setCenter(rfNode.position.x + 110, rfNode.position.y + 36, {
          zoom: 0.92,
          duration: 420,
        });
      }
    }
  }, [playbackIndex, playbackSteps, getNode, setCenter]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((prev) => applyNodeChanges(changes, prev));
  }, []);

  const onNodeClick = useCallback((_e: MouseEvent, node: Node) => {
    const d = node.data as MapNodeData;
    const thought = d.liveThought || d.thinking || d.role || "No activity recorded yet.";
    const scopeLine = d.scope
      ? `<div class="modal-kv"><span class="k">scope</span><span>${escapeHtml(d.scope)}</span></div>`
      : "";
    const html = [
      `<p class="lead">${escapeHtml(d.label)} · ${escapeHtml(d.op)}</p>`,
      scopeLine,
      `<div class="modal-kv"><span class="k">status</span><span>${escapeHtml(d.status)}</span></div>`,
      `<div class="modal-kv"><span class="k">thinking</span><span>${escapeHtml(thought)}</span></div>`,
      d.role
        ? `<div class="modal-kv"><span class="k">role</span><span>${escapeHtml(d.role)}</span></div>`
        : "",
      d.activity
        ? `<p class="am-modal-section">activity</p><pre class="proof-pre">${escapeHtml(d.activity)}</pre>`
        : "",
    ].join("");
    window.murmurOpenModal?.(`module · ${d.label}`, html);
  }, []);

  const runPlayback = useCallback(async () => {
    if (playbackTimer.current != null) {
      window.clearInterval(playbackTimer.current);
      playbackTimer.current = null;
    }

    const taskEl = document.getElementById("am-task") as HTMLTextAreaElement | null;
    const task = taskEl?.value.trim() ?? "";
    let steps = playbackSteps;
    let flowNodes = nodes;
    let flowEdges = edges;

    setPlaybackComplete(false);
    if (task) {
      setPlanning(true);
      setStatus("planning workflow");
      const runStart = Date.now();
      try {
        const planned = await runTaskStreaming(task, readRunOptions(), (event) => {
          const elapsed = Math.round((Date.now() - runStart) / 1000);
          setStatus(`${liveStatusLabel(event)} - ${elapsed}s`);
        });
        if (planned?.graph) {
          const flow = graphToFlow(planned.graph);
          flowNodes = flow.nodes;
          flowEdges = flow.edges;
          steps = planned.playback ?? [];
          setPlaybackSteps(steps);
          setGraphKey(
            `${planned.workflow_name ?? "workflow"}-${flow.nodes.length}-${Date.now()}`,
          );
          setWorkflowMeta({
            name: planned.workflow_name ?? "workflow",
            description: planned.workflow_description ?? "",
          });
          setWorkflowSize(planned.workflow_size?.reason ?? "");
          setPreviewResult(planned.preview_result ?? null);
        } else {
          setStatus("run failed - using current graph");
        }
      } catch {
        setStatus("run API unavailable - using current graph");
      } finally {
        setPlanning(false);
      }
    }

    if (!steps.length) {
      setStatus("no gate sequence to play");
      return;
    }

    openedGatesRef.current = new Set();
    lastPannedGateRef.current = "";
    setOpenGateCount(0);
    setNodes(
      flowNodes.map((node) => ({
        ...node,
        className: "",
        data: {
          ...(node.data as MapNodeData),
          status: "idle" as const,
          liveThought: (node.data as MapNodeData).thinking,
        },
      })),
    );
    setEdges(
      flowEdges.map((edge) => ({
        ...edge,
        data: { ...(edge.data as object), active: false, callsPerSecond: 0 },
      })),
    );
    setPlaybackIndex(0);
    setStatus("playing");

    let idx = 0;
    playbackTimer.current = window.setInterval(() => {
      idx += 1;
      if (idx >= steps.length) {
        if (playbackTimer.current != null) window.clearInterval(playbackTimer.current);
        playbackTimer.current = null;
        setStatus("playback complete · gates open");
        setPlaybackComplete(true);
        return;
      }
      setPlaybackIndex(idx);
    }, 700);
  }, [playbackSteps, nodes, edges]);

  const highlightOp = useCallback((op: string) => {
    setNodes((prev) =>
      prev.map((node) => ({
        ...node,
        className: (node.data as MapNodeData).op === op ? "am-node-highlight" : "",
      })),
    );
  }, []);

  return (
    <div className="am-map am-shell">
      <div className="am-toolbar">
        <div className="am-toolbar__meta">
          <span className="am-workflow-name">{workflowMeta.name}</span>
          {workflowMeta.description ? (
            <span className="am-workflow-desc">{workflowMeta.description}</span>
          ) : null}
          {workflowSize ? (
            <span className="am-workflow-desc">auto-size · {workflowSize}</span>
          ) : null}
          <span className="am-status-line" role="status" aria-live="polite">
            {nodes.length} modules · {edges.length} flows · {playbackSteps.length} gates
            {openGateCount > 0 ? ` · ${openGateCount} flowing` : ""} · {status}
          </span>
        </div>
        <button
          type="button"
          className="am-btn am-btn--accent"
          onClick={() => void runPlayback()}
          disabled={planning}
          aria-busy={planning || status === "playing"}
        >
          {planning ? "Running..." : status === "playing" ? "Playing..." : "Run agents"}
        </button>
      </div>
      <div className="am-ops">
        {(data.operators ?? []).map((op) => (
          <button key={op} type="button" className="am-op-chip" onClick={() => highlightOp(op)}>
            {op}
          </button>
        ))}
      </div>
      <div className="am-stage">
        <div className="am-canvas dot-grid-bg">
          <ReducedMotionProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={onNodeClick}
            nodesDraggable
            nodesConnectable={false}
            elementsSelectable
            zoomOnScroll
            zoomOnPinch
            zoomOnDoubleClick
            panOnDrag
            panOnScroll={false}
            preventScrolling
            minZoom={0.35}
            maxZoom={2}
            style={{ width: "100%", height: "100%" }}
            proOptions={{ hideAttribution: true }}
          >
            <FitOnGraphChange graphKey={graphKey} />
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#cacac4" />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
          </ReducedMotionProvider>
        </div>
        <RunResultsPanel
          result={previewResult}
          playbackComplete={playbackComplete}
          planning={planning}
          revealed={playbackComplete && Boolean(previewResult)}
        />
      </div>
    </div>
  );
}

export function AgentMapApp({ payload }: Props) {
  const data = payload as unknown as AgentMapPayload;
  return (
    <ReactFlowProvider>
      <AgentMapCanvas data={data} />
    </ReactFlowProvider>
  );
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
