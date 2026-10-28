import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import chalk_mermaid as cm  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FILES = sorted((ROOT / "examples").glob("*.mmd")) + [FIX / "syntax.mmd", FIX / "compact.mmd"]


class Parse(unittest.TestCase):
    """Same nodes, labels, shapes and edges as mermaid 11's own parser (fixture from bench/mermaid_parse.mjs)."""

    def test_matches_mermaid(self):
        want = json.loads((FIX / "mermaid_parse.json").read_text(encoding="utf-8"))
        for f in FILES:
            with self.subTest(f.name):
                g = cm.parse(f.read_text(encoding="utf-8"))
                w = want[f.name]
                self.assertEqual(g["dir"], w["dir"])
                self.assertEqual([[n["id"], n["text"], n["type"]] for n in g["nodes"]],
                                 [[n["id"], n["text"], n["type"]] for n in w["nodes"]])
                self.assertEqual([[e["start"], e["end"], e["text"], e["stroke"], e["arrow"]] for e in g["edges"]],
                                 [[e["start"], e["end"], e["text"], e["stroke"], e["arrow"]] for e in w["edges"]])

    def test_rejects_other_diagrams(self):
        with self.assertRaises(ValueError):
            cm.parse("sequenceDiagram\n  A->>B: hi")


class Shapes(unittest.TestCase):
    """Same hand-drawn wobble as khan-explainer's board.html curve(), oval() and box() (fixture from bench/khan_shapes.mjs)."""

    def close(self, got, want):
        self.assertEqual(len(got), len(want))
        self.assertLess(max(max(abs(a - c), abs(b - d)) for (a, b), (c, d) in zip(got, want)), 1e-5)

    def test_curve_oval_box(self):
        k = json.loads((FIX / "khan_shapes.json").read_text())
        for c in k["curve"]:
            self.close(cm.curve(c["a"], c["b"], c["c"], c["n"]), c["pts"])
        for o in k["oval"]:
            self.close(cm.oval(*o["args"]), o["pts"])
        for b in k["box"]:
            self.close(cm.box(*b["args"]), b["pts"])


class Layout(unittest.TestCase):
    def test_no_overlap_and_flow_goes_one_way(self):
        for f in FILES:
            g = cm.layout(cm.parse(f.read_text(encoding="utf-8")))
            boxes = [n["box"] for n in g["nodes"]]
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    self.assertFalse(a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3], f.name)
            axis = 0 if g["dir"] in ("LR", "RL") else 1
            pos = {n["id"]: n["box"][axis] for n in g["nodes"]}
            fwd = [e for e in g["edges"] if not e["back"]]
            self.assertTrue(all(pos[e["start"]] < pos[e["end"]] for e in fwd), f.name)


class Svg(unittest.TestCase):
    def test_svg_is_valid_animated_and_escaped(self):
        svg = cm.render(cm.parse('flowchart TD\n  a["<b>x & y</b>"] --> b{ok?}\n  b -->|yes| c'))
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("&lt;b&gt;x &amp; y&lt;/b&gt;", svg)
        self.assertEqual(svg.count('class="ink"'), 3 + 2)  # three shapes, two edges
        self.assertIn("@keyframes", svg)

    def test_cli_writes_svg_and_html(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
            r = subprocess.run([sys.executable, str(ROOT / "chalk_mermaid.py"), str(ROOT / "examples" / "agent-loop.mmd"), "-o", d],
                               capture_output=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
            self.assertIn("6 nodes, 6 edges", r.stdout.decode("utf-8"))
            ET.fromstring(Path(d, "agent-loop.svg").read_text(encoding="utf-8"))
            self.assertIn("<svg", Path(d, "agent-loop.html").read_text(encoding="utf-8"))

    def test_cli_compact_syntax_from_mermaid_docs(self):
        """F's rev0 failure: 'graph TD;' with 'A-->B;' (no spaces) must draw, not crash."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "f2.mmd")
            f.write_text("graph TD;\n    A-->B;\n    A-->C;\n    B-->D;\n    C-->D;", encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "chalk_mermaid.py"), str(f), "-o", d], capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
            self.assertIn("4 nodes, 4 edges", r.stdout.decode("utf-8"))
            g = cm.parse((FIX / "compact.mmd").read_text(encoding="utf-8"))
            ET.fromstring(cm.render(g))  # double heads and trapezoids render to valid SVG


if __name__ == "__main__":
    unittest.main()
