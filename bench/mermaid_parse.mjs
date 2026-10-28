// npm i mermaid@11 jsdom@25 && node bench/mermaid_parse.mjs examples/*.mmd: mermaid's own parse of each flowchart (nodes, edges) + ms
import { JSDOM } from "jsdom";
import fs from "fs";
const dom = new JSDOM("<!doctype html><body></body>");
globalThis.window = dom.window; globalThis.document = dom.window.document;
globalThis.DOMParser = dom.window.DOMParser; globalThis.Element = dom.window.Element;
const { default: mermaid } = await import("mermaid");
mermaid.initialize({ startOnLoad: false });
const out = {};
const t0 = performance.now();
for (const f of process.argv.slice(2)) {
  const d = await mermaid.mermaidAPI.getDiagramFromText(fs.readFileSync(f, "utf8"));
  const v = d.db.getVertices();
  const nodes = [...(v instanceof Map ? v.values() : Object.values(v))].map(n => ({ id: n.id, text: n.text, type: n.type || "square" }));
  const edges = d.db.getEdges().map(e => ({ start: e.start, end: e.end, text: e.text || "", stroke: e.stroke, arrow: e.type }));
  out[f.split(/[\\/]/).pop()] = { dir: d.db.getDirection(), nodes, edges };
}
const ms = performance.now() - t0;
console.log(JSON.stringify({ ms, out }, null, 1));
