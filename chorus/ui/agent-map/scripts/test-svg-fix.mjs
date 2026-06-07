import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const outDir = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../.chorus/preview/screenshots");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
await page.goto("http://127.0.0.1:8765/agent-map.html", { waitUntil: "networkidle" });
await page.waitForSelector(".react-flow__edge");

const rects = await page.evaluate(() => ({
  edges: document.querySelector(".react-flow__edges")?.getBoundingClientRect(),
  renderer: document.querySelector(".react-flow__renderer")?.getBoundingClientRect(),
}));
console.log("before", rects);

await page.addStyleTag({
  content: `
.react-flow__edges { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; z-index:20; }
.react-flow__edges > svg { position:absolute !important; top:0 !important; left:0 !important; width:100% !important; height:100% !important; overflow:visible !important; }
`,
});

await page.evaluate(() => {
  const svg = document.querySelector(".react-flow__edges svg");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", "50");
  line.setAttribute("y1", "50");
  line.setAttribute("x2", "800");
  line.setAttribute("y2", "400");
  line.setAttribute("stroke", "#ff0000");
  line.setAttribute("stroke-width", "12");
  svg?.prepend(line);
});

await page.waitForTimeout(200);
const after = await page.evaluate(() => ({
  svg: document.querySelector(".react-flow__edges svg")?.getBoundingClientRect(),
  hit: (() => {
    const svg = document.querySelector(".react-flow__edges svg");
    const r = svg?.getBoundingClientRect();
    if (!r) return null;
    const el = document.elementFromPoint(r.left + 200, r.top + 100);
    return el?.tagName + " " + (el?.getAttribute?.("stroke") || "");
  })(),
}));
console.log("after", after);

writeFileSync(resolve(outDir, "agent-map-fix2.png"), await page.locator(".am-canvas").screenshot());
await browser.close();
