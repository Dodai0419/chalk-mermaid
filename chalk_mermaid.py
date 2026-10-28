#!/usr/bin/env python3
"""chalk-mermaid: draw any Mermaid flowchart on a chalkboard, stroke by stroke, as an animated SVG.

    python chalk_mermaid.py flow.mmd -o out             # out/flow.svg (animated) + out/flow.html (replay button)
    python chalk_mermaid.py README.md -o out --light    # every ```mermaid flowchart in a Markdown file, whiteboard look
    python chalk_mermaid.py flow.mmd --png -o out       # also the finished board as PNG (needs Chrome or Edge)

Parsing follows mermaid's flowchart syntax (mermaid-js/mermaid, MIT); the hand-drawn strokes, colours and
draw-then-write pacing are ported from khan-explainer's board (haiderfarooq3/khan-explainer, MIT).
"""
import argparse
import html
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------- parse (mermaid flowchart subset)
SHAPES = [("(((", ")))", "doublecircle"), ("((", "))", "circle"), ("([", "])", "stadium"), ("[[", "]]", "subroutine"),
          ("[(", ")]", "cylinder"), ("[/", "/]", "lean_right"), ("[/", "\\]", "trapezoid"), ("[\\", "\\]", "lean_left"),
          ("[\\", "/]", "inv_trapezoid"), ("{{", "}}", "hexagon"), ("{", "}", "diamond"), ("(", ")", "round"),
          ("[", "]", "square"), (">", "]", "odd")]
NODE_ID = re.compile(r"[A-Za-z0-9_](?:\w|-(?![-.>]))*")  # a dash ends the id when an arrow starts (A-->B)
LABELED = re.compile(r"\s*(--|==|-\.)(?![-=.>])\s*(.+?)\s*(-{2,}[>ox]?|={2,}[>ox]?|\.+-[>ox]?)(?=\s|[A-Za-z0-9_\"])")
PLAIN = re.compile(r"(?:\s*(<)|\s+([ox]))?\s*(-{2,}[>ox]|-{3,}|={2,}[>ox]|={3,}|-\.+-[>ox]?)(?:\s*\|([^|]*)\|)?")
ARROW = {">": "arrow_point", "o": "arrow_circle", "x": "arrow_cross"}
SKIP = re.compile(r"^(%%|classDef\b|class\b|style\b|linkStyle\b|click\b|subgraph\b|end\b|direction\b)")


def _unquote(t):
    t = t.strip()
    return t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t


def parse(src):
    lines = [l.strip() for l in src.replace(";", "\n").splitlines() if l.strip() and not l.strip().startswith("%%")]
    m = re.match(r"(flowchart|graph)\b\s*(TB|TD|BT|RL|LR)?", lines[0] if lines else "")
    if not m:
        raise ValueError("not a Mermaid flowchart (first line must be 'flowchart' or 'graph')")
    g = {"dir": {"TD": "TB", None: "TB"}.get(m.group(2), m.group(2)), "nodes": [], "edges": []}  # mermaid says TB for TD
    nodes = {}

    def node(s, i):
        while i < len(s) and s[i] == " ":
            i += 1
        m = NODE_ID.match(s, i)
        if not m:
            raise ValueError(f"expected a node id at: {s[i:]!r}")
        nid, i = m.group(0), m.end()
        if nid not in nodes:
            nodes[nid] = {"id": nid, "text": nid, "type": "square"}
            g["nodes"].append(nodes[nid])
        for op, _, _ in SHAPES:
            if s.startswith(op, i):
                k = i + len(op)
                if s.startswith('"', k):  # quoted text may contain the closing bracket
                    k = s.index('"', k + 1) + 1
                ends = [(s.find(cl, k), cl, kind) for o, cl, kind in SHAPES if o == op and s.find(cl, k) >= 0]
                if not ends:
                    raise ValueError(f"unclosed {op!r} at: {s[i:]!r}")
                j, cl, kind = min(ends)  # '[/' closes as '/]' or '\]': the nearest closer wins
                nodes[nid].update(text=_unquote(s[i + len(op):j]), type=kind)
                i = j + len(cl)
                break
        m = re.match(r":::[\w-]+", s[i:])  # A:::cls is styling only, skipped like classDef
        return nid, i + (m.end() if m else 0)

    def group(s, i):
        ids = []
        while True:
            nid, i = node(s, i)
            ids.append(nid)
            m = re.match(r"\s*&\s*", s[i:])
            if not m:
                return ids, i
            i += m.end()

    for line in lines[1:]:
        if SKIP.match(line):
            continue
        left, i = group(line, 0)
        while i < len(line) and line[i:].strip():
            m = LABELED.match(line, i) or PLAIN.match(line, i)
            if not m:
                raise ValueError(f"cannot read: {line[i:]!r}")
            if m.re is LABELED:
                start, text, end = m.group(1), m.group(2), m.group(3)
            else:
                start = end = m.group(3)
                text = m.group(4) or ""
            stroke = "thick" if start.startswith("=") else "dotted" if "." in start + end else "normal"
            arrow = ARROW.get(end[-1], "arrow_open")
            if m.re is PLAIN and (m.group(1) or m.group(2)):  # <-->, o--o, x--x
                arrow = "double_" + arrow
            right, i = group(line, m.end())
            for a in left:
                for b in right:
                    g["edges"].append({"start": a, "end": b, "text": _unquote(text), "stroke": stroke, "arrow": arrow})
            left = right
    return g


# ---------------------------------------------------------------- hand-drawn strokes (from khan-explainer board.html)
def curve(a, b, ctrl=None, n=40):
    mx, my = ctrl or ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    amp = min(2, math.hypot(b[0] - a[0], b[1] - a[1]) / 80)  # short strokes get less wobble
    pts = []
    for i in range(n + 1):
        u = i / n
        v, w = 1 - u, amp * math.sin(u * 9)
        pts.append([v * v * a[0] + 2 * v * u * mx + u * u * b[0] + w, v * v * a[1] + 2 * v * u * my + u * u * b[1] + w])
    return pts


def oval(cx, cy, rx, ry):
    pts = []
    for i in range(81):
        a = -math.pi / 2 + (i / 80) * math.pi * 2.08
        k = 1 + 0.03 * math.sin(a * 3 + cx) + 0.025 * (i / 80)
        pts.append([cx + math.cos(a) * rx * k, cy + math.sin(a) * ry * k])
    return pts


def box(x, y, w, h):
    return (curve([x, y], [x + w, y + 2], None, 14) + curve([x + w, y + 2], [x + w - 2, y + h], None, 10)
            + curve([x + w - 2, y + h], [x + 1, y + h - 2], None, 14) + curve([x + 1, y + h - 2], [x - 2, y - 5], None, 10))


def poly(points):
    """a closed hand-drawn outline through the corners, overshooting the start a little like box()"""
    out = []
    for p, q in zip(points, points[1:] + points[:1]):
        out += curve(p, q, None, max(6, int(math.dist(p, q) / 10)))
    return out


# ---------------------------------------------------------------- layout
FONT, PAD_X, NODE_H, RANK_GAP, SIDE_GAP, MARGIN = 26, 30, 66, 120, 56, 60


def _size(n):
    w = max(90, len(n["text"]) * FONT * 0.58 + 2 * PAD_X)
    if n["type"] in ("diamond", "hexagon"):
        return w + 50, NODE_H + 34
    if n["type"] in ("circle", "doublecircle"):
        d = max(w * 0.8, NODE_H + 20)
        return d, d
    return w, NODE_H


def layout(g):
    """layered layout: rank = longest path from a source (back edges of cycles ignored), barycentre ordering"""
    ids = [n["id"] for n in g["nodes"]]
    out = {i: [] for i in ids}
    for e in g["edges"]:
        out[e["start"]].append(e["end"])
    state, back = {}, set()

    def dfs(u):  # mark edges that close a cycle
        state[u] = 1
        for v in out[u]:
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2

    for i in ids:
        if i not in state:
            dfs(i)
    rank = {i: 0 for i in ids}
    for _ in ids:  # longest path by relaxation; the graph without back edges is acyclic
        for e in g["edges"]:
            if (e["start"], e["end"]) not in back and e["start"] != e["end"]:
                rank[e["end"]] = max(rank[e["end"]], rank[e["start"]] + 1)
    layers = [[i for i in ids if rank[i] == r] for r in range(max(rank.values(), default=0) + 1)]
    nbr = {i: [] for i in ids}
    for e in g["edges"]:
        nbr[e["start"]].append(e["end"])
        nbr[e["end"]].append(e["start"])
    for sweep in range(4):
        order = {i: k for layer in layers for k, i in enumerate(layer)}
        rng = range(1, len(layers)) if sweep % 2 == 0 else range(len(layers) - 2, -1, -1)
        for r in rng:
            ref = r - 1 if sweep % 2 == 0 else r + 1
            def bary(i):
                ks = [order[j] for j in nbr[i] if rank[j] == ref]
                return sum(ks) / len(ks) if ks else order[i]
            layers[r].sort(key=bary)
    horiz = g["dir"] in ("LR", "RL")
    size = {n["id"]: _size(n) for n in g["nodes"]}
    across = [sum((size[i][1] if horiz else size[i][0]) for i in L) + SIDE_GAP * (len(L) - 1) for L in layers]
    depth = [max((size[i][0] if horiz else size[i][1]) for i in L) for L in layers]
    width = max(across, default=0)
    pos, along = {}, MARGIN
    for L, a, d in zip(layers, across, depth):
        c = MARGIN + (width - a) / 2
        for i in L:
            w, h = size[i]
            pos[i] = (along + (d - w) / 2, c, w, h) if horiz else (c, along + (d - h) / 2, w, h)
            c += (h if horiz else w) + SIDE_GAP
        along += d + RANK_GAP
    if g["dir"] in ("BT", "RL"):  # flip the main axis
        end = along - RANK_GAP + MARGIN
        pos = {i: ((end - x - w, y, w, h) if horiz else (x, end - y - h, w, h)) for i, (x, y, w, h) in pos.items()}
    for n in g["nodes"]:
        n["box"] = pos[n["id"]]
        n["rank"] = rank[n["id"]]
    for e in g["edges"]:
        e["back"] = (e["start"], e["end"]) in back or rank[e["end"]] <= rank[e["start"]]
    g["size"] = ((along - RANK_GAP + MARGIN, width + 2 * MARGIN) if horiz else (width + 2 * MARGIN, along - RANK_GAP + MARGIN))
    g["order"] = [i for L in layers for i in L]
    return g


# ---------------------------------------------------------------- render
THEMES = {  # khan-explainer's chalk (dark) and marker (light) colours
    "dark": dict(bg="#111", ink="#e8e8e8", node="#4fc3f7", decide="#ffe066", ends="#81c784", label="#ffb74d"),
    "light": dict(bg="#fbfbf8", ink="#1c1c1c", node="#1b74d3", decide="#cf8600", ends="#1c9a4a", label="#e6620a"),
}
HAND = '"Bradley Hand","Chalkboard SE","Marker Felt","Segoe Print","Comic Sans MS",cursive'


def _outline(n):
    x, y, w, h = n["box"]
    cx, cy, t = x + w / 2, y + h / 2, n["type"]
    if t in ("circle", "doublecircle"):
        return oval(cx, cy, w / 2, h / 2) + (oval(cx, cy, w / 2 - 7, h / 2 - 7) if t == "doublecircle" else [])
    if t == "stadium":
        return oval(cx, cy, w / 2 + 6, h / 2 + 4)
    if t == "diamond":
        return poly([[cx, y], [x + w, cy], [cx, y + h], [x, cy]])
    if t == "hexagon":
        return poly([[x + 22, y], [x + w - 22, y], [x + w, cy], [x + w - 22, y + h], [x + 22, y + h], [x, cy]])
    if t in ("lean_right", "lean_left"):
        s = 18 if t == "lean_right" else -18
        return poly([[x + s, y], [x + w + s, y], [x + w - s, y + h], [x - s, y + h]])
    if t in ("trapezoid", "inv_trapezoid"):
        s = 18 if t == "trapezoid" else -18
        return poly([[x + s, y], [x + w - s, y], [x + w + s, y + h], [x - s, y + h]])
    if t == "odd":
        return poly([[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x + 20, cy]])
    pts = box(x, y, w, h)
    if t == "subroutine":
        return pts + [None] + curve([x + 10, y], [x + 10, y + h], None, 8) + [None] + curve([x + w - 10, y], [x + w - 10, y + h], None, 8)
    if t == "cylinder":
        return pts + [None] + oval(cx, y + 8, w / 2 - 2, 8)
    return pts


def _edge_end(n, toward):
    """where a line from the node centre toward a point leaves the node's box (an ellipse for round shapes)"""
    x, y, w, h = n["box"]
    cx, cy = x + w / 2, y + h / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if not dx and not dy:
        return [cx, cy]
    if n["type"] in ("circle", "doublecircle", "stadium", "diamond"):
        k = 1 / math.hypot(dx / (w / 2 + 8), dy / (h / 2 + 8))
    else:
        k = min((w / 2 + 8) / abs(dx) if dx else math.inf, (h / 2 + 8) / abs(dy) if dy else math.inf)
    return [cx + dx * k, cy + dy * k]


def _path(pts):
    d, pen = [], "M"
    for p in pts:
        if p is None:
            pen = "M"
            continue
        d.append(f"{pen}{p[0]:.1f} {p[1]:.1f}")
        pen = "L"
    return " ".join(d)


def render(g, theme="dark", speed=1.0):
    if "size" not in g:
        layout(g)
    c = THEMES[theme]
    W, H = g["size"]
    nodes = {n["id"]: n for n in g["nodes"]}
    ink, words, t = [], [], 0.3
    e_ = html.escape
    horiz, lanes, far = g["dir"] in ("LR", "RL"), 0, [0, 0]

    def draw(pts, color, dur, width=5):
        nonlocal t
        ink.append(f'<path class="ink" pathLength="1" d="{_path(pts)}" stroke="{color}" stroke-width="{width}"'
                   f' style="--d:{t:.2f}s;--t:{dur:.2f}s"/>')
        t += dur

    def write(text, x, y, color, size=FONT):
        nonlocal t
        dur = max(0.25, 0.035 * len(text)) / speed
        words.append(f'<text class="w" x="{x:.1f}" y="{y:.1f}" fill="{color}" font-size="{size}" text-anchor="middle"'
                     f' style="--d:{t:.2f}s;--t:{dur:.2f}s">{e_(text)}</text>')
        t += dur

    done = set()
    for nid in g["order"]:
        n = nodes[nid]
        x, y, w, h = n["box"]
        color = c["decide"] if n["type"] in ("diamond", "hexagon") else c["ends"] if n["type"] in ("stadium", "circle", "doublecircle") else c["node"]
        draw(_outline(n), color, 0.45 / speed)
        write(n["text"], x + w / 2, y + h / 2 + FONT * 0.35, c["ink"])
        done.add(nid)
        for e in g["edges"]:
            if e.get("_drawn") or not {e["start"], e["end"]} <= done:
                continue
            e["_drawn"] = True
            a, b = nodes[e["start"]], nodes[e["end"]]
            ca = [a["box"][0] + a["box"][2] / 2, a["box"][1] + a["box"][3] / 2]
            cb = [b["box"][0] + b["box"][2] / 2, b["box"][1] + b["box"][3] / 2]
            if a is b:
                continue
            if e["back"] or abs(b["rank"] - a["rank"]) > 1:
                # loops and long jumps go round the outside (right of a top-down chart, below a left-right one),
                # each in its own lane, so they never cross a node
                lo, hi = sorted((a["rank"], b["rank"]))
                between = [m["box"] for m in g["nodes"] if lo <= m["rank"] <= hi]
                # leave through the gap after the source's rank, enter through the gap before the target's rank
                (ax, ay, aw, ah), (bx, by, bw, bh) = a["box"], b["box"]
                off = 30 + 8 * lanes
                if horiz:
                    lane = max(y + h for _, y, _, h in between) + 40 + 22 * lanes
                    route = [[ax + aw + 8, ca[1]], [ax + aw + off, ca[1]], [ax + aw + off, lane], [bx - off, lane],
                             [bx - off, cb[1]], [bx - 8, cb[1]]]
                else:
                    lane = max(x + w for x, _, w, _ in between) + 40 + 22 * lanes
                    route = [[ca[0], ay + ah + 8], [ca[0], ay + ah + off], [lane, ay + ah + off], [lane, by - off],
                             [cb[0], by - off], [cb[0], by - 8]]
                lanes += 1
                far[0], far[1] = (far[0], max(far[1], lane + 40)) if horiz else (max(far[0], lane + 40), far[1])
                pts = []
                for p, q in zip(route, route[1:]):
                    pts += curve(p, q, None, max(4, int(math.dist(p, q) / 12)))
                k0, k1 = route[2], route[3]
                label_at = [(k0[0] + k1[0]) / 2 + (0 if horiz else 14), (k0[1] + k1[1]) / 2 + (18 if horiz else 0)]
            else:
                p0, p1 = _edge_end(a, cb), _edge_end(b, ca)
                pts = curve(p0, p1)
                label_at = pts[20]
            kind = e["arrow"].replace("double_", "")
            ends = [(pts[-1], pts[-5])] + ([(pts[0], pts[4])] if e["arrow"].startswith("double_") else [])
            for tip, q in ends if kind != "arrow_open" else []:
                ang = math.atan2(tip[1] - q[1], tip[0] - q[0])
                if kind == "arrow_point":
                    for d in (2.6, -2.6):
                        pts += [None, tip, [tip[0] + math.cos(ang + d) * 22, tip[1] + math.sin(ang + d) * 22]]
                elif kind == "arrow_cross":
                    for d in (0.8, -0.8):
                        pts += [None, [tip[0] + math.cos(ang + d) * 12, tip[1] + math.sin(ang + d) * 12],
                                [tip[0] - math.cos(ang + d) * 12, tip[1] - math.sin(ang + d) * 12]]
                else:
                    pts += [None] + oval(tip[0], tip[1], 7, 7)
            draw(pts, c["ink"], 0.35 / speed, width=8 if e["stroke"] == "thick" else 4)
            if e["stroke"] == "dotted":  # dots cannot be drawn on with a dash offset, so they appear at their beat
                ink[-1] = ink[-1].replace('class="ink"', 'class="ink dot"')
            if e["text"]:
                write(e["text"], label_at[0], label_at[1] - 10, c["label"], size=22)
    W, H = max(W, far[0]), max(H, far[1])
    g["size"] = (W, H)  # outside lanes can widen the board
    css = (f"text{{font-family:{HAND};font-weight:700}}"
           ".ink{fill:none;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1;"
           "animation:draw var(--t) linear var(--d) forwards}"
           ".dot{stroke-dasharray:.012 .02;stroke-dashoffset:0;opacity:0;animation:show .01s linear var(--d) forwards}"
           ".w{clip-path:inset(-20% 100% -20% 0);animation:write var(--t) linear var(--d) forwards}"
           "@keyframes draw{to{stroke-dashoffset:0}}@keyframes write{to{clip-path:inset(-20% 0 -20% 0)}}"
           "@keyframes show{to{opacity:1}}"
           ".still .ink,.still .w,.still .dot{animation:none;stroke-dashoffset:0;clip-path:none;opacity:1}"
           "@media (prefers-reduced-motion:reduce){.ink,.w,.dot{animation:none;stroke-dashoffset:0;clip-path:none;opacity:1}}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
            f'role="img"><title>{e_(", ".join(n["text"] for n in g["nodes"]))}</title><style>{css}</style>'
            '<filter id="chalk"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="1" seed="4"/>'
            '<feDisplacementMap in="SourceGraphic" scale="2.2"/></filter>'
            f'<rect width="100%" height="100%" fill="{c["bg"]}" rx="14"/>'
            f'<g filter="url(#chalk)">{"".join(ink)}{"".join(words)}</g></svg>\n')


PAGE = """<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:{bg};font:16px system-ui}}
svg{{max-width:96vw;height:auto}}button{{margin:14px auto;display:block;padding:9px 20px;border:0;border-radius:9px;background:#ffb74d;font:inherit;cursor:pointer}}</style>
<div><div id="b">{svg}</div><button onclick="const s=b.querySelector('svg');s.replaceWith(s.cloneNode(true))">Draw it again</button></div>
"""


def find_chrome():
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser", "msedge"):
        if p := shutil.which(name):
            return p
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if Path(p).exists():
            return p
    return None


def png(svg_path, png_path, size, chrome):
    """the finished board: the SVG with animations switched off, screenshotted at its own size"""
    still = Path(svg_path).read_text(encoding="utf-8").replace('role="img">', 'role="img" class="still">', 1)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d, "still.svg")
        f.write_text(still, encoding="utf-8")
        subprocess.run([chrome, "--headless=new", f"--user-data-dir={d}", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={size[0]:.0f},{size[1]:.0f}", f"--screenshot={png_path}", f.as_uri()],
                       capture_output=True, timeout=120)
    return Path(png_path).exists()


def sources(path):
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() in (".md", ".markdown"):
        blocks = re.findall(r"^```mermaid[ \t]*\n(.*?)^```", text, flags=re.S | re.M)
        return [b for b in blocks if re.match(r"\s*(flowchart|graph)\b", b)]
    return [text]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", help=".mmd file, or a Markdown file with ```mermaid flowchart blocks")
    ap.add_argument("-o", "--out", default="chalk-out")
    ap.add_argument("--light", action="store_true", help="marker on a whiteboard instead of chalk")
    ap.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast")
    ap.add_argument("--png", action="store_true", help="also save the finished board as PNG (Chrome or Edge)")
    a = ap.parse_args(argv)
    src = Path(a.file)
    if not src.is_file():
        sys.exit(f"chalk-mermaid: no such file: {src}")
    blocks = sources(src)
    if not blocks:
        sys.exit(f"chalk-mermaid: no flowchart found in {src}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    theme = "light" if a.light else "dark"
    chrome = find_chrome() if a.png else None
    for k, text in enumerate(blocks, 1):
        try:
            g = layout(parse(text))
        except ValueError as err:
            sys.exit(f"chalk-mermaid: {src.name} block {k}: {err}")
        name = src.stem + (f"-{k}" if len(blocks) > 1 else "")
        svg = render(g, theme, a.speed)
        (out / f"{name}.svg").write_text(svg, encoding="utf-8")
        (out / f"{name}.html").write_text(PAGE.format(title=html.escape(name), bg=THEMES[theme]["bg"], svg=svg), encoding="utf-8")
        secs = max(float(x) + float(y) for x, y in re.findall(r"--d:([\d.]+)s;--t:([\d.]+)s", svg))
        print(f"chalk-mermaid: {name}: {len(g['nodes'])} nodes, {len(g['edges'])} edges, drawn in {secs:.1f} s -> {out / (name + '.svg')}")
        if a.png:
            if chrome and png(out / f"{name}.svg", str((out / f"{name}.png").resolve()), g["size"], chrome):
                print(f"  {out / (name + '.png')}")
            else:
                print("  no PNG: Chrome or Edge not found")


if __name__ == "__main__":
    main()
