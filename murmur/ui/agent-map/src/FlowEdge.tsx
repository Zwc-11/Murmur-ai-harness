import { memo } from "react";
import { getSmoothStepPath, type EdgeProps } from "@xyflow/react";
import { edgeIntensity, pipelineColor, pipelineGlow } from "./colors";
import { useReducedMotion } from "./hooks/useReducedMotion";
import type { MapEdgeData } from "./types";

const TRAVERSE_TIME = 2;
const IDLE_TRAVERSE_TIME = 8;
const MAX_DUR = 20;
const MAX_PARTICLES = 5;
const MAX_PARTICLES_LOW_FX = 2;
const ACTIVE_CPS = 8;

function getStrokeWidth(cps: number, active: boolean): number {
  if (!active) return 3;
  return Math.min(8, Math.max(4, 4 + Math.log10(1 + cps) * 1.2));
}

function simpleHash(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) | 0;
  }
  return (Math.abs(h) % 1000) / 1000;
}

export const FlowEdge = memo(function FlowEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const reducedMotion = useReducedMotion();
  const edgeData = (data ?? {}) as MapEdgeData;
  const active = Boolean(edgeData.active);
  const lowFx = Boolean(edgeData.lowFx);
  const cps = active ? Math.max(edgeData.callsPerSecond ?? 0, ACTIVE_CPS) : 0;
  const intensity = active ? edgeIntensity(cps) : 0.15;
  const sw = getStrokeWidth(cps, active);

  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 14,
  });

  const sourceColor = pipelineColor(source);
  const targetColor = pipelineColor(target);
  const sourceGlow = pipelineGlow(source);

  let particleCount = 0;
  let traversalDuration = TRAVERSE_TIME;
  const particleCap = lowFx ? MAX_PARTICLES_LOW_FX : MAX_PARTICLES;

  if (!reducedMotion) {
    if (active && cps > 0) {
      const interArrival = 1 / cps;
      if (interArrival > TRAVERSE_TIME) {
        particleCount = 1;
        traversalDuration = Math.min(interArrival, MAX_DUR);
      } else {
        traversalDuration = TRAVERSE_TIME;
        particleCount = Math.min(particleCap, Math.max(2, Math.round(cps * TRAVERSE_TIME)));
      }
    } else if (!lowFx) {
      particleCount = 1;
      traversalDuration = IDLE_TRAVERSE_TIME + simpleHash(`${id}:idle`) * 3;
    }
  }

  const stagger = traversalDuration / Math.max(particleCount, 1);
  const edgeOffset = simpleHash(id) * Math.min(stagger, 1);
  const particleRadius = Math.max(3.5, sw * 0.5);

  const safeId = id.replace(/[^a-zA-Z0-9-_]/g, "_");
  const pathId = `path-${safeId}`;
  const gradientId = `grad-${safeId}`;

  const bodyOpacity = active ? 0.78 + intensity * 0.2 : 0.42;
  const glowOpacity = active ? (lowFx ? 0.28 + intensity * 0.15 : 0.35 + intensity * 0.25) : 0.18;
  const showDash = !reducedMotion && !lowFx;
  const packetOpacity = active ? (lowFx ? 0.55 : 0.78) : 0.36;
  const packetScale = active ? 1 : 0.72;

  return (
    <g
      className={[
        "am-pipeline-edge",
        `am-pipeline-edge--${edgeData.kind ?? "flow"}`,
        active ? "am-pipeline-edge--hot" : "am-pipeline-edge--idle",
      ].join(" ")}
    >
      <defs>
        <linearGradient
          id={gradientId}
          gradientUnits="userSpaceOnUse"
          x1={sourceX}
          y1={sourceY}
          x2={targetX}
          y2={targetY}
        >
          <stop offset="0%" stopColor={sourceColor} />
          <stop offset="100%" stopColor={targetColor} />
        </linearGradient>
      </defs>

      <path
        d={edgePath}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth={sw * 4 + (lowFx ? 5 : 11)}
        strokeOpacity={glowOpacity * 0.8}
        strokeLinecap="round"
      />
      <path
        d={edgePath}
        fill="none"
        stroke="#0f172a"
        strokeWidth={sw * 2.05 + 5}
        strokeOpacity={active ? 0.24 : 0.12}
        strokeLinecap="round"
      />
      <path
        d={edgePath}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth={sw + 5}
        strokeOpacity={bodyOpacity}
        strokeLinecap="round"
      />
      <path
        id={pathId}
        d={edgePath}
        fill="none"
        stroke="#1e293b"
        strokeWidth={Math.max(2, sw * 0.35)}
        strokeOpacity={active ? 0.5 : 0.2}
        strokeLinecap="round"
      />
      {showDash ? (
        <path
          d={edgePath}
          fill="none"
          stroke="#ffffff"
          strokeWidth={active ? sw * 0.45 : Math.max(1.5, sw * 0.32)}
          strokeOpacity={active ? 0.88 : 0.5}
          strokeDasharray={active ? "6 18" : "3 24"}
          strokeLinecap="round"
          className={active ? "am-pipeline-dash" : "am-pipeline-dash am-pipeline-dash--idle"}
        />
      ) : null}

      {particleCount > 0 &&
        !reducedMotion &&
        Array.from({ length: particleCount }).map((_, idx) => (
          <g key={idx}>
            <ellipse
              rx={particleRadius * packetScale * (lowFx ? 1.6 : 2.2)}
              ry={particleRadius * packetScale * 0.85}
              fill={sourceGlow}
              opacity={packetOpacity}
            >
              <animateMotion
                dur={`${traversalDuration}s`}
                repeatCount="indefinite"
                begin={`${edgeOffset + idx * stagger}s`}
                rotate="auto"
              >
                <mpath href={`#${pathId}`} />
              </animateMotion>
            </ellipse>
            <circle
              r={particleRadius * packetScale * 0.65}
              fill="#ffffff"
              stroke={sourceColor}
              strokeWidth={active ? 1.5 : 1}
              opacity={active ? 1 : 0.76}
            >
              <animateMotion
                dur={`${traversalDuration}s`}
                repeatCount="indefinite"
                begin={`${edgeOffset + idx * stagger}s`}
                rotate="auto"
              >
                <mpath href={`#${pathId}`} />
              </animateMotion>
            </circle>
          </g>
        ))}
    </g>
  );
});
