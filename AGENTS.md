# AGENTS.md

Use this tool when the user wants a flowchart drawn by hand, animated, or turned into an explainer.


Draws the flowchart the way a teacher would on a board: one shape, then its label written left to right, then the
arrows into it, in the order of the flow. The output is a single SVG that animates by itself (also inside a GitHub
README) and an HTML page with a replay button.

## Run

From the repository root of this skill (Python 3.8+, nothing to install):

```bash
python chalk_mermaid.py flow.mmd -o chalk-out                # chalk on a blackboard
python chalk_mermaid.py flow.mmd --light -o chalk-out        # marker on a whiteboard
python chalk_mermaid.py README.md -o chalk-out               # every ```mermaid flowchart block in the file
python chalk_mermaid.py flow.mmd --speed 2 --png -o chalk-out  # twice as fast, plus a PNG of the finished board
```

## Supported Mermaid
`flowchart` / `graph` with TB, TD, BT, LR, RL. Shapes: `[box]`, `(round)`, `([stadium])`, `[[subroutine]]`,
`[(database)]`, `((circle))`, `(((double)))`, `{diamond}`, `{{hexagon}}`, `[/lean/]`, `>flag]`, quoted labels.
Edges: `-->`, `---`, `-.->`, `==>`, `--o`, `--x`, labels as `-->|text|` or `-- text -->`, chains `a --> b --> c`
and `a --> b & c`. `subgraph`, `style`, `classDef` and `click` lines are skipped.

## How to use it for the user
1. If they describe a process in words, write the flowchart in Mermaid first and show it to them.
2. Run the command and give them the `.svg` (drop it into a README with `![](flow.svg)`) and the `.html`.
3. The terminal line says how long the drawing takes; use `--speed` to fit a video or slide.
