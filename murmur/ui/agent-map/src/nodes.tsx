import { memo, type CSSProperties } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { MapNodeData } from "./types";

function hueColor(hue: number, lightness = 0.55, chroma = 0.15): string {
  return `oklch(${lightness} ${chroma} ${hue})`;
}

function statusDot(status: string): string {
  if (status === "running") return "am-status--running";
  if (status === "pass") return "am-status--pass";
  if (status === "fail") return "am-status--fail";
  return "am-status--idle";
}

function formatLatency(ms?: number): string {
  if (ms == null || ms <= 0) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${ms.toFixed(0)}ms`;
}

export const OperatorNode = memo(function OperatorNode({ data }: NodeProps) {
  const d = data as unknown as MapNodeData;
  const accent = hueColor(d.hue ?? 250);

  return (
    <div
      className={`am-node am-node--operator ${d.quarantined ? "am-node--quarantined" : ""}`}
      style={{ "--node-accent": accent } as CSSProperties}
    >
      <Handle type="target" position={Position.Left} className="am-handle" />
      <div className="am-node__head">
        <span className={`am-status ${statusDot(d.status)}`} />
        <span className="am-node__op">{d.op}</span>
        {d.scope ? <span className="am-node__scope">{d.scope}</span> : null}
        <span className="am-node__label">{d.label}</span>
      </div>
      {d.liveThought || d.thinking || d.role ? (
        <div className="am-node__role">{d.liveThought || d.thinking || d.role}</div>
      ) : null}
      <div className="am-node__metrics">
        <span>{formatLatency(d.metrics?.latency_ms)}</span>
        {d.model ? <span>{d.model}</span> : null}
      </div>
      <Handle type="source" position={Position.Right} className="am-handle" />
    </div>
  );
});

export const AgentNode = memo(function AgentNode({ data }: NodeProps) {
  const d = data as unknown as MapNodeData;
  const accent = hueColor(d.hue ?? 210, 0.62, 0.12);

  return (
    <div
      className={`am-node am-node--agent ${d.quarantined ? "am-node--quarantined" : ""}`}
      style={{ "--node-accent": accent } as CSSProperties}
    >
      <Handle type="target" position={Position.Left} className="am-handle" />
      <div className="am-node__head">
        <span className={`am-status ${statusDot(d.status)}`} />
        <span className="am-node__label">{d.label}</span>
      </div>
      {d.liveThought || d.thinking ? (
        <div className="am-node__preview">{d.liveThought || d.thinking}</div>
      ) : d.metrics?.preview ? (
        <div className="am-node__preview">{d.metrics.preview}</div>
      ) : null}
      <Handle type="source" position={Position.Right} className="am-handle" />
    </div>
  );
});
