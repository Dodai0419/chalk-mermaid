// node khan.mjs path/to/board.html: run khan-explainer's own curve/oval/box on fixed inputs, print the points
import fs from "fs";
const src = fs.readFileSync(process.argv[2], "utf8");
const grab = (start, end) => src.slice(src.indexOf(start), src.indexOf(end, src.indexOf(start)));
const code = grab("function curve(", "const around") + "\nreturn { curve, oval, box };";
const { curve, oval, box } = new Function(code)();
const r = (pts) => pts.map(([x, y]) => [Math.round(x * 1e6) / 1e6, Math.round(y * 1e6) / 1e6]);
console.log(JSON.stringify({
  curve: [[[10, 20], [300, 80], null, 40], [[0, 0], [30, 5], [15, 40], 12]].map(([a, b, c, n]) => ({ a, b, c, n, pts: r(curve(a, b, c, n)) })),
  oval: [[200, 120, 90, 40], [50, 60, 20, 20]].map((a) => ({ args: a, pts: r(oval(...a)) })),
  box: [[100, 50, 180, 70], [0, 0, 40, 30]].map((a) => ({ args: a, pts: r(box(...a)) })),
}));
