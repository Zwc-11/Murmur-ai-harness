/** Maple-style pipeline hues (perceptual spread). */
const SERVICE_HUES = [
  250, 185, 155, 130, 90, 60, 45, 25, 0, 340, 320, 290, 270, 260, 210, 230,
];

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = value.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash);
}

/** Hex stroke color for a node id (visible on light backgrounds). */
export function pipelineColor(nodeId: string): string {
  const hue = SERVICE_HUES[hashString(nodeId) % SERVICE_HUES.length];
  return `hsl(${hue} 78% 48%)`;
}

export function pipelineGlow(nodeId: string): string {
  const hue = SERVICE_HUES[hashString(nodeId) % SERVICE_HUES.length];
  return `hsl(${hue} 85% 62%)`;
}

export function edgeIntensity(callsPerSecond: number): number {
  if (callsPerSecond <= 0) return 0.35;
  return Math.min(1, 0.35 + (0.65 * Math.log10(1 + callsPerSecond)) / Math.log10(100));
}
