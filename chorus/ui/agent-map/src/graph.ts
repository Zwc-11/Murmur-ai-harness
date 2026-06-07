import type { Edge, Node } from "@xyflow/react";
import type { AgentMapPayload, MapNodeData } from "./types";

export function graphToFlow(graph: AgentMapPayload["graph"]): {
  nodes: Node[];
  edges: Edge[];
} {
  const nodes: Node[] = (graph?.nodes ?? []).map((n) => ({
    id: n.id,
    type: n.kind === "agent" ? "agent" : "operator",
    position: n.position ?? { x: 0, y: 0 },
    data: { ...n } satisfies MapNodeData,
  }));
  const edges: Edge[] = (graph?.edges ?? []).map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: "flow",
    zIndex: 1000,
    data: {
      kind: e.kind,
      active: Boolean(e.active),
      callsPerSecond: e.callsPerSecond ?? 0,
      gate: e.gate,
    },
  }));
  return { nodes, edges };
}
