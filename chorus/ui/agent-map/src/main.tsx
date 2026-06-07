import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AgentMapApp } from "./AgentMapApp";
import "./agent-map.css";

declare global {
  interface Window {
    CHORUS_AGENT_MAP?: Record<string, unknown>;
    chorusOpenModal?: (title: string, html: string) => void;
  }
}

function mountAgentMap() {
  const mount = document.getElementById("agent-map-root");
  if (!mount || !window.CHORUS_AGENT_MAP) {
    return;
  }
  createRoot(mount).render(
    <StrictMode>
      <AgentMapApp payload={window.CHORUS_AGENT_MAP} />
    </StrictMode>,
  );
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAgentMap);
} else {
  mountAgentMap();
}
