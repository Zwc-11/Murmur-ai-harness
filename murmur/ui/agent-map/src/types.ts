export type NodeStatus = "idle" | "running" | "pass" | "fail";

export interface MapNodeData {
  id: string;
  kind: "operator" | "agent";
  op: string;
  label: string;
  role: string;
  model: string;
  status: NodeStatus;
  quarantined?: boolean;
  thinking?: string;
  activity?: string;
  liveThought?: string;
  metrics: {
    latency_ms?: number;
    throughput?: number;
    error_rate?: number;
    preview?: string;
  };
  hue: number;
  parent_op?: string;
  scope?: "shared" | "fanout" | "lane" | "combine";
  lane_index?: number;
}

export interface MapEdgeData {
  kind?: string;
  gate?: string;
  active?: boolean;
  callsPerSecond?: number;
  errorRate?: number;
  /** Drop SVG blur filters when many pipelines are active. */
  lowFx?: boolean;
}

export interface PlaybackStep {
  seq: number;
  type: string;
  node_id: string;
  timestamp: string;
  message?: string;
  gate?: string;
}

export interface WorkflowSizeInfo {
  attempts: number;
  max_repairs: number;
  reason: string;
}

export interface LanePreview {
  id: string;
  label: string;
  selected: boolean;
  preview: string;
}

export interface GateLogEntry {
  gate: string;
  type: string;
  message: string;
}

export interface ArtifactLink {
  kind: string;
  path: string;
  href: string;
  description?: string;
}

export interface PreviewResult {
  mode: "preview" | "live";
  status: string;
  run_id?: string;
  run_dir?: string;
  winner_id: string;
  winner_label: string;
  summary: string;
  report: string;
  lane_previews?: LanePreview[];
  gate_log?: GateLogEntry[];
  artifacts?: ArtifactLink[];
  primary_artifact?: ArtifactLink | null;
  document_preview?: string;
  program_preview?: string;
  planner?: {
    mode?: string;
    reason?: string;
    duration_ms?: number;
    model_calls?: number;
    output_tokens?: number;
    cost_usd?: number;
    reasoning?: string;
  };
  timeline?: Array<{
    step: string;
    kind: string;
    status: string;
    duration_ms: number;
    tokens: number;
    cost_usd: number;
    detail?: string;
    thinking?: string;
  }>;
  acceptance_summary?: {
    passed?: boolean;
    failed_requirements?: string[];
    winner_reason?: string;
    repair_count?: number;
  } | null;
  failed_requirements?: string[];
  repair_iterations?: Array<{
    iteration?: number;
    passed?: boolean;
    summary?: string;
    risk_flags?: string[];
    failed_requirements?: string[];
  }>;
  validation_summary?: {
    kind?: string;
    passed?: boolean;
    summary?: string;
    checks?: Record<string, boolean>;
    risk_flags?: string[];
    details?: {
      richness?: {
        score?: number;
        level?: string;
        signals?: Record<string, number>;
      };
    };
  } | null;
  proof?: Record<string, unknown>;
  note?: string;
}

export interface AgentMapPayload {
  workflow: Record<string, unknown>;
  workflow_name?: string;
  workflow_description?: string;
  workflow_size?: WorkflowSizeInfo;
  preview_result?: PreviewResult;
  graph: {
    nodes: Array<MapNodeData & { position: { x: number; y: number } }>;
    edges: Array<{
      id: string;
      source: string;
      target: string;
      kind?: string;
      active?: boolean;
      callsPerSecond?: number;
      gate?: string;
    }>;
  };
  playback: PlaybackStep[];
  operators: string[];
  op_hues: Record<string, number>;
}
