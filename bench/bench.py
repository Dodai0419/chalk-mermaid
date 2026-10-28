"""Time chalk-mermaid on the four examples: parse only (compare with bench/mermaid_parse.mjs), and the whole job.

    python bench/bench.py
"""
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import chalk_mermaid as cm  # noqa: E402

files = sorted((ROOT / "examples").glob("*.mmd"))
texts = [f.read_text(encoding="utf-8") for f in files]


def med(fn, n=50):
    runs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        runs.append((time.perf_counter() - t) * 1000)
    return statistics.median(runs)


print(f"parse {len(files)} flowcharts:                 {med(lambda: [cm.parse(t) for t in texts]):8.2f} ms")
print(f"parse + layout + animated SVG, all {len(files)}:   {med(lambda: [cm.render(cm.layout(cm.parse(t))) for t in texts]):8.2f} ms")
runs = []
with tempfile.TemporaryDirectory() as d:
    for _ in range(5):
        t = time.perf_counter()
        for f in files:
            subprocess.run([sys.executable, str(ROOT / "chalk_mermaid.py"), str(f), "-o", d], check=True, capture_output=True)
        runs.append((time.perf_counter() - t) * 1000)
print(f"CLI, one process per file, all {len(files)}:       {statistics.median(runs):8.0f} ms")
