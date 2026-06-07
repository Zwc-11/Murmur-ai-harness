import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
await page.goto("http://127.0.0.1:8765/agent-map.html", { waitUntil: "networkidle" });
await page.waitForSelector(".am-pipeline-edge path", { timeout: 15000 });

const info = await page.evaluate(() => {
  const path = document.querySelector(".am-pipeline-edge path");
  const edgesSvg = document.querySelector(".react-flow__edges");
  const viewport = document.querySelector(".react-flow__viewport");
  const rect = path?.getBoundingClientRect();
  const style = path ? getComputedStyle(path) : null;
  return {
    pathD: path?.getAttribute("d")?.slice(0, 120),
    stroke: path?.getAttribute("stroke"),
    strokeOpacity: path?.getAttribute("stroke-opacity"),
    strokeWidth: path?.getAttribute("stroke-width"),
    rect,
    edgesSvgStyle: edgesSvg ? {
      transform: getComputedStyle(edgesSvg).transform,
      opacity: getComputedStyle(edgesSvg).opacity,
      zIndex: getComputedStyle(edgesSvg).zIndex,
      overflow: getComputedStyle(edgesSvg).overflow,
    } : null,
    viewportTransform: viewport?.getAttribute("style"),
  };
});

console.log(JSON.stringify(info, null, 2));
await browser.close();
