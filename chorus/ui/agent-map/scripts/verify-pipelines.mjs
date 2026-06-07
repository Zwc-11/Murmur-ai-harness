import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(__dirname, "../../../../.chorus/preview/screenshots");
mkdirSync(outDir, { recursive: true });

const url = "http://127.0.0.1:8765/agent-map.html";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForSelector(".react-flow", { timeout: 15000 });
await page.waitForTimeout(1500);

const stats = await page.evaluate(() => {
  const edgeGroups = document.querySelectorAll(".react-flow__edge");
  const pipelinePaths = document.querySelectorAll(".am-pipeline-edge path");
  const allEdgePaths = document.querySelectorAll(".react-flow__edges path");
  const svg = document.querySelector(".react-flow__edges svg");
  return {
    edgeGroups: edgeGroups.length,
    pipelinePaths: pipelinePaths.length,
    allEdgePaths: allEdgePaths.length,
    svgHtml: svg ? svg.innerHTML.slice(0, 500) : "NO SVG",
    root: !!document.getElementById("agent-map-root"),
  };
});

const shot = resolve(outDir, "agent-map-verify.png");
await page.locator(".am-canvas").screenshot({ path: shot });

const visible = await page.evaluate(() => {
  const svg = document.querySelector(".react-flow__edges > svg");
  const paths = document.querySelectorAll(".am-pipeline-edge path");
  const svgRect = svg?.getBoundingClientRect();
  return {
    ok: Boolean(svgRect && svgRect.width > 100 && paths.length >= 9),
    svgWidth: svgRect?.width ?? 0,
    pathCount: paths.length,
  };
});
const pipelinesVisible = visible.ok;

await browser.close();

console.log(JSON.stringify({ url, shot, stats, visible, pipelinesVisible }, null, 2));
process.exit(stats.pipelinePaths > 0 && pipelinesVisible ? 0 : 1);
