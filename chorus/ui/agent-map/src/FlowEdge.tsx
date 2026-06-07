import { memo } from "react";
import { getSmoothStepPath, type EdgeProps } from "@xyflow/react";
import { edgeIntensity, pipelineColor, pipelineGlow } from "./colors";
import { useReducedMotion } from "./hooks/useReducedMotion";
import type { MapEdgeData } from "./types";

const TRAVERSE_TIME = 2;
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

  if (active && cps > 0 && !reducedMotion) {
    const interArrival = 1 / cps;
    if (interArrival > TRAVERSE_TIME) {
      particleCount = 1;
      traversalDuration = Math.min(interArrival, MAX_DUR);
    } else {
      traversalDuration = TRAVERSE_TIME;
      particleCount = Math.min(particleCap, Math.max(2, Math.round(cps * TRAVERSE_TIME)));
    }
  }

  const stagger = traversalDuration / Math.max(particleCount, 1);
  const edgeOffset = simpleHash(id) * Math.min(stagger, 1);
  const particleRadius = Math.max(3.5, sw * 0.5);

  const safeId = id.replace(/[^a-zA-Z0-9-_]/g, "_");
  const pathId = `path-${safeId}`;
  const gradientId = `grad-${safeId}`;

  const bodyOpacity = active ? 0.78 + intensity * 0.2 : 0.22;
  const glowOpacity = active ? (lowFx ? 0.28 + intensity * 0.15 : 0.35 + intensity * 0.25) : 0.08;
  const showDash = active && !reducedMotion && !lowFx;

  return (
    <g className={`am-pipeline-edge ${active ? "am-pipeline-edge--hot" : "am-pipeline-edge--idle"}`}>
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
        strokeWidth={sw * 2.4 + (lowFx ? 4 : 8)}
        strokeOpacity={glowOpacity}
        strokeLinecap="round"
      />
      <path
        d={edgePath}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth={sw + 2}
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
          strokeWidth={sw * 0.4}
          strokeOpacity={0.9}
          strokeDasharray="5 18"
          strokeLinecap="round"
          className="am-pipeline-dash"
        />
      ) : null}

      {active &&
        !reducedMotion &&
        Array.from({ length: particleCount }).map((_, idx) => (
          <g key={idx}>
            <ellipse
              rx={particleRadius * (lowFx ? 1.6 : 2.2)}
              ry={particleRadius * 0.85}
              fill={sourceGlow}
              opacity={lowFx ? 0.55 : 0.75}
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
            <circle r={particleRadius * 0.65} fill="#ffffff" stroke={sourceColor} strokeWidth={1.5}>
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
