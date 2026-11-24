"""Render a provenance graph as an SVG timeline.

Layout, left to right in time:
  * one box per turn, and under it one box per tool call the turn issued;
  * one horizontal lane per file. A call that reads a file puts an open circle
    on the file's lane, a call that writes it puts a filled square there, and
    the lane changes color where the file stops being original content.

The result of a call is read by the following turn; this is drawn as a thin
line from the call into the arrow that links the two turns, so result nodes
need no boxes of their own.

No external tools are needed. Colors are the first three slots of a palette
checked for color-vision-deficiency separation, and every color-coded item
also carries a text label.

Usage:
    python3 provenance/render.py graphs/run-030.json figures/run-030.svg
    python3 provenance/render.py graphs/run-031.json figures/run-031-slice.svg \\
        --ancestors-of "O:file:tests/test_expense_summary.py@v1" --highlight C:2 C:9
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#8a897f"
BOX = "#eceae5"
RULE = "#dddbd4"
TRUST_COLOR = {"skill": "#2a78d6", "workspace": "#eb6834", "derived": "#1baf7a"}
TRUST_TEXT = {
    "skill": "skill files (installed by the user)",
    "workspace": "workspace files (present before the run)",
    "derived": "files created during the run",
}
FONT = "font-family=\"Helvetica, Arial, sans-serif\""

COL = 52            # width of one tool-call column
BOX_W = 44
TURN_H = 22
CALL_H = 30
LANE_GAP = 22
GROUP_GAP = 30


def ancestors(graph: dict[str, Any], target: str) -> set[str]:
    """The target and every node with a path to it."""
    parents: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        parents.setdefault(edge["dst"], []).append(edge["src"])
    seen, stack = {target}, [target]
    while stack:
        for parent in parents.get(stack.pop(), []):
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def call_summary(node: dict[str, Any]) -> str:
    for key in ("filePath", "command", "pattern", "name"):
        if key in node["input"]:
            text = " ".join(str(node["input"][key]).split())
            return text if len(text) <= 110 else text[:107] + "..."
    return ""


class Renderer:
    def __init__(self, graph: dict[str, Any], keep: set[str] | None, highlight: set[str]):
        self.graph = graph
        self.nodes = {n["id"]: n for n in graph["nodes"]}
        self.keep = keep if keep is not None else set(self.nodes)
        self.highlight = highlight
        self.out: list[str] = []

    def kept(self, node_id: str) -> bool:
        return node_id in self.keep

    # -- layout --------------------------------------------------------------

    def layout(self) -> None:
        turns = [n for n in self.graph["nodes"] if n["kind"] == "turn" and self.kept(n["id"])]
        self.turns = sorted(turns, key=lambda n: n["index"])
        self.call_x: dict[int, float] = {}
        self.turn_span: dict[int, tuple[float, float]] = {}

        files = [n for n in self.graph["nodes"] if n["kind"] == "file" and self.kept(n["id"])]
        paths = sorted({n["path"] for n in files})
        first_trust = {p: min((n for n in files if n["path"] == p), key=lambda n: n["version"])["trust"]
                       for p in paths}
        self.lane_paths = [p for trust in ("skill", "workspace", "derived")
                           for p in paths if first_trust[p] == trust]
        self.lane_trust = first_trust
        longest = max([len(p) for p in paths] + [len(text) for text in TRUST_TEXT.values()] + [10])
        self.left = max(210.0, longest * 6.2 + 44)

        column = 0
        for turn in self.turns:
            calls = [k for k in turn["calls"] if self.kept(f"C:{k}")]
            first = column
            for k in calls:
                self.call_x[k] = self.left + column * COL + COL / 2
                column += 1
            if not calls:
                column += 1
            x0 = self.left + first * COL + (COL - BOX_W) / 2
            x1 = self.left + column * COL - (COL - BOX_W) / 2
            self.turn_span[turn["index"]] = (x0, x1)
        self.columns = max(column, 1)
        self.right = self.left + self.columns * COL

        self.y_turn = 92.0
        self.y_call = self.y_turn + TURN_H + 20
        y = self.y_call + CALL_H + 26
        self.lane_y: dict[str, float] = {}
        self.group_y: dict[str, float] = {}
        previous = None
        for path in self.lane_paths:
            trust = self.lane_trust[path]
            if trust != previous:
                y += GROUP_GAP if previous else 12
                self.group_y[trust] = y - 6
                y += 14
                previous = trust
            self.lane_y[path] = y
            y += LANE_GAP
        self.lanes_bottom = y
        self.height = y + 140
        self.width = self.right + 36

    # -- drawing helpers -----------------------------------------------------

    def add(self, text: str) -> None:
        self.out.append(text)

    def text(self, x: float, y: float, content: str, *, size: float = 11, fill: str = INK,
             anchor: str = "start", weight: str = "normal") -> None:
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" fill="{fill}" '
                 f'text-anchor="{anchor}" font-weight="{weight}">{escape(content)}</text>')

    # -- drawing -------------------------------------------------------------

    def render(self, title: str, subtitle: str) -> str:
        self.layout()
        self.width=max(self.width,len(subtitle)*6.1+40)
        self.add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" height="{self.height:.0f}" '
                 f'viewBox="0 0 {self.width:.0f} {self.height:.0f}" role="img" aria-label="{escape(title)}">')
        self.add(f'<rect width="100%" height="100%" fill="{SURFACE}"/>')
        self.add('<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" '
                 f'markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{INK_2}"/></marker></defs>')
        self.text(20, 28, title, size=15, weight="bold")
        self.text(20, 46, subtitle, size=11, fill=INK_2)
        self.text(20, self.y_turn + 15, "model turns", size=10.5, fill=INK_2)
        self.text(20, self.y_call + 19, "tool calls", size=10.5, fill=INK_2)
        self.draw_lanes()
        self.draw_calls_and_edges()
        self.draw_turns()
        self.draw_legend()
        self.add("</svg>")
        return "\n".join(self.out) + "\n"

    def file_edges(self) -> list[dict[str, Any]]:
        edges = []
        for edge in self.graph["edges"]:
            if not (self.kept(edge["src"]) and self.kept(edge["dst"])):
                continue
            src, dst = self.nodes[edge["src"]], self.nodes[edge["dst"]]
            if src["kind"] == "file" and dst["kind"] == "call":
                edges.append({"call": dst["index"], "file": src, "op": "read", "edge": edge})
            elif src["kind"] == "call" and dst["kind"] == "file":
                edges.append({"call": src["index"], "file": dst,
                              "op": "delete" if dst["deleted"] else "write", "edge": edge})
        return [e for e in edges if e["call"] in self.call_x]

    def draw_lanes(self) -> None:
        edges = self.file_edges()
        for trust, y in self.group_y.items():
            self.add(f'<line x1="20" y1="{y - 4:.1f}" x2="42" y2="{y - 4:.1f}" stroke="{TRUST_COLOR[trust]}" '
                     'stroke-width="3" stroke-linecap="round"/>')
            self.text(50, y, TRUST_TEXT[trust], size=10.5, fill=INK_2)
        for path in self.lane_paths:
            y = self.lane_y[path]
            self.text(self.left - 16, y + 4, path, size=11, anchor="end")
            writes = sorted((e for e in edges if e["file"]["path"] == path and e["op"] != "read"),
                            key=lambda e: e["call"])
            base = self.lane_trust[path]
            start = self.left + 4 if base != "derived" else None
            # A lane is drawn in the color of the version that exists at that time.
            points: list[tuple[float, str | None]] = []
            if start is not None:
                points.append((start, TRUST_COLOR[base]))
            for write in writes:
                x = self.call_x[write["call"]]
                points.append((x, None if write["op"] == "delete" else TRUST_COLOR["derived"]))
            if base == "derived" and not writes:
                points.append((self.left + 4, TRUST_COLOR["derived"]))
            for (x0, color), (x1, _) in zip(points, points[1:] + [(self.right - 4, None)]):
                if color and x1 > x0:
                    self.add(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="{color}" '
                             f'stroke-width="2" stroke-linecap="round"><title>{escape(path)}</title></line>')

    def draw_calls_and_edges(self) -> None:
        edges = self.file_edges()
        by_call: dict[int, list[dict[str, Any]]] = {}
        for item in edges:
            by_call.setdefault(item["call"], []).append(item)

        # Vertical connector from each call down to the lanes it touches.
        for k, items in by_call.items():
            x = self.call_x[k]
            lowest = max(self.lane_y[item["file"]["path"]] for item in items)
            inferred = any(item["edge"]["basis"] == "inferred" for item in items)
            dash = ' stroke-dasharray="3 3"' if inferred else ""
            strong = f"C:{k}" in self.highlight
            self.add(f'<line x1="{x:.1f}" y1="{self.y_call + CALL_H:.1f}" x2="{x:.1f}" y2="{lowest:.1f}" '
                     f'stroke="{INK if strong else INK_MUTED}" stroke-width="{1.6 if strong else 1}"{dash}/>')

        # Result of a call, read by the next turn: joins the arrow between turns.
        kept_turns = [turn["index"] for turn in self.turns]
        for turn in self.turns:
            following = turn["index"] + 1
            if following not in kept_turns:
                continue
            gutter = self.turn_span[following][0] - (COL - BOX_W) / 2
            y_join = self.y_turn + TURN_H / 2
            for k in turn["calls"]:
                if k not in self.call_x:
                    continue
                x = self.call_x[k] + 15
                y0 = self.y_call + CALL_H
                self.add(f'<path d="M{x:.1f},{y0:.1f} v6 H{gutter:.1f} V{y_join:.1f}" fill="none" '
                         f'stroke="{INK_MUTED}" stroke-width="1"><title>result of call {k}, read by turn '
                         f'{following}</title></path>')
            if any(k in self.call_x for k in turn["calls"]):
                self.add(f'<circle cx="{gutter:.1f}" cy="{y_join:.1f}" r="2.2" fill="{INK_2}"/>')

        # Call boxes.
        for k, x in self.call_x.items():
            node = self.nodes[f"C:{k}"]
            failed = node["status"] != "completed"
            strong = node["id"] in self.highlight
            x0 = x - BOX_W / 2
            self.add(f'<line x1="{x:.1f}" y1="{self.y_turn + TURN_H:.1f}" x2="{x:.1f}" y2="{self.y_call:.1f}" '
                     f'stroke="{INK_2}" stroke-width="1" marker-end="url(#arrow)"/>')
            fill = SURFACE if failed else BOX
            stroke = INK if strong else (INK_MUTED if failed else "none")
            width = 2.2 if strong else 1
            tip = f'call {k}: {node["tool"]} ({node["status"]}) {call_summary(node)}'
            self.add(f'<rect x="{x0:.1f}" y="{self.y_call:.1f}" width="{BOX_W}" height="{CALL_H}" rx="4" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="{width}"><title>{escape(tip)}</title></rect>')
            self.text(x, self.y_call + 12.5, f"C{k}", size=10, anchor="middle",
                      weight="bold" if strong else "normal", fill=INK_2 if failed else INK)
            label = node["tool"] if len(node["tool"]) <= 8 else node["tool"][:7] + "."
            self.text(x, self.y_call + 24, label, size=9, anchor="middle", fill=INK_2)

        # Markers on the lanes.
        for k, items in by_call.items():
            x = self.call_x[k]
            written = {item["file"]["path"] for item in items if item["op"] != "read"}
            for item in items:
                path, node, edge = item["file"]["path"], item["file"], item["edge"]
                y = self.lane_y[path]
                basis = edge["basis"] + (f', rule {edge["rule"]}' if edge.get("rule") else "")
                tip = f'call {k} {item["op"]}s {node["id"]} ({basis})'
                ring = node["id"] in self.highlight
                if item["op"] == "read":
                    # An edit reads the old version and writes the next one:
                    # the read sits just before the write on the same lane.
                    cx = x - 15 if path in written else x
                    self.add(f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="4.5" fill="{SURFACE}" stroke="{INK}" '
                             f'stroke-width="1.6"><title>{escape(tip)}</title></circle>')
                elif item["op"] == "write":
                    if ring:
                        self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="none" stroke="{INK}" '
                                 'stroke-width="1.6"/>')
                    self.add(f'<rect x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" rx="2" fill="{INK}" '
                             f'stroke="{SURFACE}" stroke-width="2"><title>{escape(tip)}</title></rect>')
                    self.text(x + (12 if ring else 8), y - (9 if ring else 6), f'v{node["version"]}',
                              size=9, fill=INK_2)
                else:
                    self.add(f'<path d="M{x - 4.5:.1f},{y - 4.5:.1f} l9,9 M{x - 4.5:.1f},{y + 4.5:.1f} l9,-9" '
                             f'stroke="{INK}" stroke-width="2" stroke-linecap="round">'
                             f'<title>{escape(tip)}</title></path>')

    def draw_turns(self) -> None:
        first = self.turns[0]["index"] if self.turns else None
        for turn in self.turns:
            x0, x1 = self.turn_span[turn["index"]]
            tip = f'turn {turn["index"]}: issued calls {turn["calls"] or "none"}'
            self.add(f'<rect x="{x0:.1f}" y="{self.y_turn:.1f}" width="{x1 - x0:.1f}" height="{TURN_H}" rx="4" '
                     f'fill="{BOX}"><title>{escape(tip)}</title></rect>')
            self.text((x0 + x1) / 2, self.y_turn + 15, f'T{turn["index"]}', size=10.5, anchor="middle")
            if turn["index"] != first and (turn["index"] - 1) in self.turn_span:
                px1 = self.turn_span[turn["index"] - 1][1]
                y = self.y_turn + TURN_H / 2
                self.add(f'<line x1="{px1:.1f}" y1="{y:.1f}" x2="{x0:.1f}" y2="{y:.1f}" stroke="{INK_2}" '
                         'stroke-width="1" marker-end="url(#arrow)"/>')
        if first == 1 and self.kept("O:prompt"):
            x0 = self.turn_span[1][0]
            y = self.y_turn + TURN_H / 2
            self.add(f'<rect x="{x0 - 92:.1f}" y="{self.y_turn:.1f}" width="74" height="{TURN_H}" rx="11" '
                     f'fill="{SURFACE}" stroke="{INK}" stroke-width="1.4"><title>O:prompt: the user\'s task '
                     'instruction (trust: user)</title></rect>')
            self.text(x0 - 55, self.y_turn + 15, "user prompt", size=10, anchor="middle")
            self.add(f'<line x1="{x0 - 18:.1f}" y1="{y:.1f}" x2="{x0:.1f}" y2="{y:.1f}" stroke="{INK_2}" '
                     'stroke-width="1" marker-end="url(#arrow)"/>')
        for node in self.graph['nodes']:
            if node['kind']!='prompt' or 'before_turn' not in node or not self.kept(node['id']):
                continue
            if node['before_turn'] not in self.turn_span:
                continue
            x0,x1=self.turn_span[node['before_turn']]
            x=(x0+x1)/2
            tip=f"{node['id']}: user message arrives before T{node['before_turn']}; {node['content']}"
            self.text(x,self.y_turn-22,f"user {node['user_index']}",size=10,anchor='middle')
            self.add(f'<path d="M{x:.1f},{self.y_turn-18:.1f} L{x:.1f},{self.y_turn-2:.1f}" stroke="{INK}" marker-end="url(#arrow)"><title>{escape(tip)}</title></path>')

    def draw_legend(self) -> None:
        y = self.lanes_bottom + 26
        self.add(f'<line x1="20" y1="{y - 18:.1f}" x2="{self.width - 20:.1f}" y2="{y - 18:.1f}" stroke="{RULE}" '
                 'stroke-width="1"/>')
        x = 20.0
        items = [
            ("read", "call reads the file"),
            ("write", "call writes a new version"),
            ("delete", "call removes the file"),
            ("solid", "recorded in the trajectory"),
            ("dashed", "inferred: command or child evidence"),
            ("failed", "failed call"),
        ]
        if self.highlight:
            items.append(("highlight", "discussed in the text"))
        for kind, label in items:
            if x + 34 + len(label) * 5.9 > self.width - 20:
                x, y = 20.0, y + 20
            if kind == "read":
                self.add(f'<circle cx="{x + 6:.1f}" cy="{y - 4:.1f}" r="4.5" fill="{SURFACE}" stroke="{INK}" '
                         'stroke-width="1.6"/>')
            elif kind == "write":
                self.add(f'<rect x="{x + 1:.1f}" y="{y - 9:.1f}" width="10" height="10" rx="2" fill="{INK}"/>')
            elif kind == "delete":
                self.add(f'<path d="M{x + 1.5:.1f},{y - 8.5:.1f} l9,9 M{x + 1.5:.1f},{y + 0.5:.1f} l9,-9" '
                         f'stroke="{INK}" stroke-width="2" stroke-linecap="round"/>')
            elif kind in ("solid", "dashed"):
                dash = ' stroke-dasharray="3 3"' if kind == "dashed" else ""
                self.add(f'<line x1="{x + 6:.1f}" y1="{y - 12:.1f}" x2="{x + 6:.1f}" y2="{y + 4:.1f}" '
                         f'stroke="{INK_2}" stroke-width="1.2"{dash}/>')
            elif kind == "failed":
                self.add(f'<rect x="{x:.1f}" y="{y - 11:.1f}" width="14" height="13" rx="3" fill="{SURFACE}" '
                         f'stroke="{INK_MUTED}"/>')
            else:
                self.add(f'<rect x="{x:.1f}" y="{y - 11:.1f}" width="14" height="13" rx="3" fill="{BOX}" '
                         f'stroke="{INK}" stroke-width="2.2"/>')
            self.text(x + 20, y, label, size=10.5, fill=INK_2)
            x += 34 + len(label) * 5.9
        self.text(20, y + 22, "Tool results feed the next turn; thin connectors represent this history.", size=10, fill=INK_2)
        self.text(20, y + 38, "Lane color marks file origin. Dashed edges are inferences, not causal proof.", size=10, fill=INK_2)


def render_graph(graph: dict[str, Any], *, ancestors_of: str | None = None,
                 highlight: list[str] | None = None, title: str | None = None) -> str:
    keep = None
    total = len(graph["nodes"])
    subtitle = (f'{graph["source"]["model"]} · {sum(1 for n in graph["nodes"] if n["kind"] == "turn")} turns, '
                f'{sum(1 for n in graph["nodes"] if n["kind"] == "call")} tool calls')
    if ancestors_of:
        ids = {n["id"] for n in graph["nodes"]}
        if ancestors_of not in ids:
            raise ValueError(f"{ancestors_of} is not a node of {graph['run']}")
        keep = ancestors(graph, ancestors_of)
        subtitle = (f'Ancestors of {ancestors_of}: {len(keep) - 1}/{total - 1} other nodes '
                    f'· {graph["source"]["model"]}')
    for node_id in highlight or []:
        if node_id not in {n["id"] for n in graph["nodes"]}:
            raise ValueError(f"{node_id} is not a node of {graph['run']}")
    renderer = Renderer(graph, keep, set(highlight or []))
    return renderer.render(title or f'{graph["run"]}: provenance graph', subtitle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a provenance graph as an SVG timeline.")
    parser.add_argument("graph", type=Path, help="graph JSON, e.g. graphs/run-031.json")
    parser.add_argument("output", type=Path, help="output SVG file")
    parser.add_argument("--ancestors-of", metavar="NODE",
                        help="draw only the nodes that have a path to NODE (a backward slice)")
    parser.add_argument("--highlight", metavar="NODE", nargs="*", default=[],
                        help="node ids to emphasize, e.g. C:12")
    parser.add_argument("--title", help="figure title")
    args = parser.parse_args()

    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    try:
        svg = render_graph(graph, ancestors_of=args.ancestors_of, highlight=args.highlight, title=args.title)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
