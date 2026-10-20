#!/usr/bin/env python3
"""Write the dry run's synthetic mini-course: original decks, a homework and its solutions as PDFs,
a syllabus, Ed threads in ed-pull's raw form, and the student's intake answers.

  make_minicourse.py OUTDIR [--chrome PATH]

Everything is invented for the dry run: a two-lecture course on graph search, GRF 101, with
something a checker can compute (breadth-first orders, shortest-path distances). The PDFs are
HTML printed by headless Chromium: --chrome, else EXAM_PREP_CHROME, else the newest Playwright
chrome-headless-shell under ~/.cache/ms-playwright. The homework's answers are computed here, so
the official solutions are right by construction.

OUTDIR gets:
  course/lectures/L1-graphs-and-bfs.pdf      10 slides, all on Exam 1
  course/lectures/L2-shortest-paths.pdf      10 slides, Exam 1 ends at slide 9 (PDF p.9)
  course/lectures/L3-spanning-trees.pdf      4 slides, Exam 2 only (reserved)
  course/homework/hw1.pdf, hw1-solutions.pdf
  course/syllabus.pdf
  ed-raw/raw/<id>.json, ed-raw/cursor.json   copy to sources/ed/, then `ed-pull rebuild`
  answers.md                                 the student's answers to the intake questions
  expected.json                              the computed answers, for checking the dry run's checker
Stdlib only, plus the Chromium binary."""
import argparse
import glob
import heapq
import html
import json
import os
import subprocess
import sys
import tempfile

COURSE = "GRF 101"
SLIDE_CSS = """@page{size:10in 5.625in;margin:0}
body{margin:0;font-family:"DejaVu Sans",sans-serif;color:#111}
.s{width:10in;height:5.625in;box-sizing:border-box;padding:.45in .6in;position:relative;
  page-break-after:always;overflow:hidden}
.s h1{font-size:26pt;margin:0 0 .2in}.s h2{font-size:20pt;margin:0 0 .15in;color:#1d3f6e}
.s p,.s li{font-size:14pt;line-height:1.35}.s pre{font-size:12pt;background:#f2f2f2;padding:.1in}
.s table{border-collapse:collapse;font-size:12pt}.s td,.s th{border:1px solid #888;padding:2px 8px}
.foot{position:absolute;bottom:.2in;right:.4in;font-size:10pt;color:#666}
svg text{font-family:"DejaVu Sans",sans-serif;font-size:14px}"""
DOC_CSS = """@page{size:Letter;margin:.8in}
body{font-family:"DejaVu Serif",serif;font-size:11pt;color:#111;line-height:1.4}
h1{font-size:16pt}h2{font-size:13pt;margin-top:.25in}.pb{page-break-before:always}
svg text{font-family:"DejaVu Sans",sans-serif;font-size:13px}"""


# ---- the computable part ------------------------------------------------------------------

def bfs(edges, start):
    """Order and distances, neighbors in alphabetical order, a node marked when enqueued."""
    adj = {}
    for a, b, *_ in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    order, dist, queue, rows = [], {start: 0}, [start], []
    while queue:
        rows.append((queue[0], " ".join(queue)))
        node = queue.pop(0)
        order.append(node)
        for n in sorted(adj[node]):
            if n not in dist:
                dist[n] = dist[node] + 1
                queue.append(n)
    return order, dist, rows


def dijkstra(edges, start):
    """Distances and the order nodes are removed; ties broken alphabetically."""
    adj = {}
    for a, b, w in edges:
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))
    dist, done, order, heap = {start: 0}, set(), [], [(0, start)]
    while heap:
        d, node = heapq.heappop(heap)
        if node in done:
            continue
        done.add(node)
        order.append(node)
        for n, w in adj[node]:
            if n not in done and d + w < dist.get(n, float("inf")):
                dist[n] = d + w
                heapq.heappush(heap, (d + w, n))
    return dist, order


def weights(edges, path):
    """Each edge weight along path, in order."""
    w = {frozenset((a, b)): c for a, b, c in edges}
    return [w[frozenset(step)] for step in zip(path, path[1:])]


G1 = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"), ("D", "E")]
G2 = [("S", "A", 2), ("S", "B", 5), ("A", "B", 1), ("A", "C", 4), ("B", "C", 1), ("C", "T", 3),
      ("B", "T", 6)]
H = [("S", "A"), ("S", "B"), ("A", "C"), ("B", "C"), ("B", "D"), ("C", "E"), ("D", "E")]
K = [("S", "A", 4), ("S", "B", 1), ("B", "A", 2), ("A", "C", 1), ("B", "C", 5), ("C", "T", 3),
     ("B", "T", 8)]
POS = {"G1": {"A": (40, 90), "B": (130, 30), "C": (130, 150), "D": (220, 90), "E": (310, 90)},
       "G2": {"S": (40, 100), "A": (140, 30), "B": (140, 170), "C": (250, 100), "T": (360, 100)},
       "H": {"S": (40, 100), "A": (130, 40), "B": (130, 160), "C": (220, 40), "D": (220, 160),
             "E": (310, 100)},
       "K": {"S": (40, 100), "A": (150, 30), "B": (150, 170), "C": (260, 30), "T": (330, 140)}}


def graph_svg(name, edges):
    pos = POS[name]
    parts = ['<svg width="400" height="200" viewBox="0 0 400 200">']
    for a, b, *w in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#333"/>')
        if w:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            parts.append(f'<text x="{mx + 6}" y="{my - 6}" fill="#a0301c">{w[0]}</text>')
    for n, (x, y) in pos.items():
        parts.append(f'<circle cx="{x}" cy="{y}" r="16" fill="#fff" stroke="#333"/>'
                     f'<text x="{x}" y="{y + 5}" text-anchor="middle">{n}</text>')
    return "".join(parts) + "</svg>"


# ---- the documents ------------------------------------------------------------------------

def slides(title, body):
    out = []
    for i, (head, inner) in enumerate(body, 1):
        out.append(f'<div class="s"><h{1 if i == 1 else 2}>{head}</h{1 if i == 1 else 2}>{inner}'
                   f'<div class="foot">{COURSE} · {html.escape(title)} · {i}</div></div>')
    return out


def table(rows, head):
    return ("<table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            + "</table>")


def lecture1():
    order, dist, rows = bfs(G1, "A")
    return slides("Lecture 1", [
        ("Lecture 1: Graphs and Breadth-First Search", f"<p>{COURSE}, Fall 2026</p>"),
        ("What a graph is", "<ul><li>A graph is a set of <b>nodes</b> V and a set of <b>edges</b> "
         "E, each edge joining two nodes.</li><li>Undirected: an edge has no direction.</li>"
         "<li>Two nodes joined by an edge are <b>neighbors</b>.</li></ul>"),
        ("Counting edges", "<p>An undirected graph with no loops and no repeated edges on n "
         "nodes has at most n(n-1)/2 edges: each of the n(n-1)/2 pairs is joined at most once."
         "</p><p>Example: n = 5 gives at most 10 edges.</p>"),
        ("Adjacency lists", graph_svg("G1", G1) + "<p>G1: A: B, C · B: A, D · C: A, D · "
         "D: B, C, E · E: D</p>"),
        ("The idea of breadth-first search", "<ul><li>Visit the start, then every node one edge "
         "away, then two edges away, and so on.</li><li>A first-in, first-out queue holds the "
         "nodes waiting to be visited.</li></ul>"),
        ("Breadth-first search", "<pre>BFS(G, s):\n  mark s; queue = [s]\n  while queue:\n"
         "    u = queue.pop_front()\n    visit u\n    for v in neighbors(u), in order:\n"
         "      if v not marked: mark v; queue.push_back(v)</pre>"),
        ("Conventions in this course", "<ul><li>Neighbors are taken in <b>alphabetical "
         "order</b>.</li><li>A node is marked when it is <b>enqueued</b>, not when it is "
         "visited.</li></ul>"),
        ("Example: BFS on G1 from A", table(rows, ["Visit", "Queue before the visit"])
         + f"<p>Order: {', '.join(order)}</p>"),
        ("BFS finds fewest-edge paths", "<p>The layer a node is first reached in is its "
         "distance in edges from the start.</p><p>From A in G1: "
         + ", ".join(f"{n} {d}" for n, d in sorted(dist.items())) + "</p>"),
        ("Summary", "<ul><li>At most n(n-1)/2 edges.</li><li>BFS: a FIFO queue, layer by layer."
         "</li><li>It gives distances in edges.</li></ul>"),
    ]), {"G1_bfs_order": order, "G1_bfs_dist": dist}


def lecture2():
    dist, order = dijkstra(G2, "S")
    few, cheap = ["S", "B", "T"], ["S", "A", "B", "C", "T"]
    fw, cw = weights(G2, few), weights(G2, cheap)
    # The two paths the slide names are the fewest-edge one and the cheapest one.
    assert bfs([e[:2] for e in G2], "S")[1]["T"] == len(few) - 1 and sum(cw) == dist["T"]
    return slides("Lecture 2", [
        ("Lecture 2: Shortest Paths", f"<p>{COURSE}, Fall 2026</p>"),
        ("Weighted graphs", "<p>Each edge carries a non-negative <b>weight</b>; a path's "
         "<b>cost</b> is the sum of its weights.</p>"),
        ("Fewest edges is not cheapest", f"<p>In the example graph G2 (slide 7), S-B-T uses the "
         f"fewest edges, {len(few) - 1}, and costs {' + '.join(map(str, fw))} = {sum(fw)}. "
         f"S-A-B-C-T uses {len(cheap) - 1} edges and costs {' + '.join(map(str, cw))} = "
         f"{sum(cw)}. BFS picks the first, which costs more.</p>"),
        ("Dijkstra's algorithm", "<ul><li>Keep a tentative distance for each node, starting at "
         "0 for the start.</li><li>Repeatedly remove the node with the smallest tentative "
         "distance and relax its edges.</li></ul>"),
        ("Pseudocode", "<pre>DIJKSTRA(G, s):\n  d[s] = 0; others infinity; PQ = {s}\n"
         "  while PQ:\n    u = remove the smallest d[u]  (ties: alphabetical)\n"
         "    for each edge (u, v, w):\n      if d[u] + w &lt; d[v]: d[v] = d[u] + w</pre>"),
        ("Conventions in this course", "<ul><li>Ties in the queue are broken "
         "<b>alphabetically</b>.</li><li>A node is final when it is removed.</li></ul>"),
        ("Example graph G2", graph_svg("G2", G2)),
        ("Example: Dijkstra on G2 from S", table([(n, dist[n]) for n in order],
                                                 ["Removed", "Final distance"])),
        ("Dijkstra's invariant", "<p>When a node is removed, its distance is final. This needs "
         "every weight to be non-negative: a later edge can only add cost.</p>"),
        ("Negative weights", "<p>With a negative edge, a node removed early can later be "
         "reached more cheaply, so the invariant fails. (Not on Exam 1.)</p>"),
    ]), {"G2_dijkstra_dist": dist, "G2_dijkstra_order": order}


def lecture3():
    return slides("Lecture 3", [
        ("Lecture 3: Spanning Trees", f"<p>{COURSE}, Fall 2026</p>"),
        ("Spanning trees", "<p>A spanning tree joins every node with n - 1 edges and no cycle.</p>"),
        ("Minimum spanning trees", "<p>Among spanning trees, one of least total weight.</p>"),
        ("Summary", "<p>Exam 2 material.</p>"),
    ]), {}


def homework():
    order, dist, _ = bfs(H, "S")
    kd, korder = dijkstra(K, "S")
    q = (f"<h1>{COURSE} Homework 1</h1><p>Due Friday. Show your work.</p>"
         "<h2>Q1 (10 points)</h2><p>(a) At most how many edges can an undirected graph on 6 "
         "nodes have, with no loops or repeated edges? (b) Give the adjacency lists of the graph "
         "H below.</p>" + graph_svg("H", H)
         + "<h2>Q2 (10 points)</h2><p>Run BFS on H from S, with this course's conventions. "
         "(a) Give the order nodes are visited. (b) Give each node's distance in edges.</p>"
         '<h2 class="pb">Q3 (15 points)</h2><p>Run Dijkstra on the graph K below from S. '
         "(a) Give the final distances. (b) Give the order nodes are removed. (c) Explain why the "
         "algorithm needs non-negative weights.</p>" + graph_svg("K", K))
    adj = {}
    for a, b in H:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    lists = " · ".join(f"{n}: {', '.join(sorted(v))}" for n, v in sorted(adj.items()))
    s = (f"<h1>{COURSE} Homework 1: Solutions</h1>"
         f"<h2>Q1</h2><p>(a) 6 · 5 / 2 = 15. (b) {lists}</p>"
         f"<h2>Q2</h2><p>(a) {', '.join(order)}. (b) "
         + ", ".join(f"{n} {d}" for n, d in sorted(dist.items())) + "</p>"
         f'<h2 class="pb">Q3</h2><p>(a) ' + ", ".join(f"{n} {d}" for n, d in sorted(kd.items()))
         + f". (b) {', '.join(korder)}. (c) Removing a node fixes its distance; with a negative "
         "edge, a cheaper path through a node removed later could still exist.</p>")
    return q, s, {"hw1_q1a": 15, "hw1_q1b": {n: sorted(v) for n, v in adj.items()},
                  "hw1_q2a": order, "hw1_q2b": dist, "hw1_q3a": kd, "hw1_q3b": korder}


SYLLABUS = (f"<h1>{COURSE}: Graph Search, Fall 2026</h1>"
            "<h2>Exams</h2><p>Exam 1 is in class on Monday of week 6, 75 minutes. It covers "
            "Lecture 1 and Lecture 2 up to Dijkstra's invariant. Closed book, no calculator. You "
            "may bring one letter-size sheet of notes, both sides, handwritten or printed. Write "
            "your name on it.</p><p>Exam 2 covers Lecture 3 onward.</p>"
            "<h2>Homework</h2><p>Homework 1 practices Lectures 1 and 2. Solutions are posted "
            "after the due date.</p>")

USERS = [{"id": 1, "name": "Prof Example", "course_role": "admin"},
         {"id": 2, "name": "TA Example", "course_role": "tutor"},
         {"id": 3, "name": "Student One", "course_role": "student"},
         {"id": 4, "name": "Student Two", "course_role": "student"}]


def ed_threads():
    def thread(tid, number, title, body, user=1, created="2026-10-01T10:00:00Z", **extra):
        t = {"id": tid, "number": number, "course_id": 4242, "title": title, "document": body,
             "type": "post", "category": "General", "subcategory": "", "is_pinned": False,
             "user_id": user, "created_at": created, "updated_at": created, "answers": [],
             "comments": []}
        t.update(extra)
        return t
    return [
        thread(501, 1, "Exam 1 scope", "Exam 1 covers Lecture 1 and Lecture 2 through the "
               "slide on Dijkstra's invariant. Negative weights are not on Exam 1.",
               type="announcement", created="2026-10-10T09:00:00Z", is_pinned=True),
        thread(502, 2, "Tie-breaking", "On the exam, break ties alphabetically, as in "
               "lecture.", user=2, created="2026-10-11T09:00:00Z", category="Exams"),
        thread(503, 3, "Is Lecture 3 on Exam 1?", "Someone said spanning trees are on it.",
               user=3, created="2026-10-12T09:00:00Z", category="Exams",
               answers=[{"user_id": 4, "document": "I think Lecture 3 is on Exam 1 too.",
                         "created_at": "2026-10-12T10:00:00Z", "is_endorsed": False,
                         "comments": []}]),
        thread(504, 4, "Cheat sheet", "One letter-size sheet, both sides. Put your name on it.",
               type="announcement", created="2026-10-13T09:00:00Z"),
    ]


ANSWERS = """# The student's intake answers (dry run)

- Course: GRF 101, Graph Search. Exam: Exam 1, in class, Monday of week 6, 75 minutes.
- Files: the folder `course/` holds everything. This exam: L1, L2 up to slide 9 ("Dijkstra's
  invariant", PDF page 9, which is also its printed number), HW1 and its solutions, the syllabus.
  L3 is for Exam 2: keep it, don't open it.
- Answers: `hw1-solutions.pdf` answers HW1. I have attempted HW1.
- Allowed: closed book, no calculator, one letter-size sheet of notes, both sides. The exam asks
  for a name on the sheet.
- Ed: the course's Ed threads are in `ed-raw/` (offline: copy to `sources/ed/`, then
  `ed-pull rebuild`).
- I'll read the notes on the published page. Defaults are fine for everything else.
"""


def find_chrome(arg):
    for c in (arg, os.environ.get("EXAM_PREP_CHROME")):
        if c:
            return c
    found = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/"
        "chrome-headless-shell")))
    if not found:
        raise SystemExit("make_minicourse: no Chromium: pass --chrome or set EXAM_PREP_CHROME")
    return found[-1]


def to_pdf(chrome, css, body, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}'
                f"</style></head><body>{body}</body></html>")
    try:
        # --no-sandbox: Chromium's own sandbox can't nest inside the Bash sandbox, and the page
        # is this script's own HTML (Playwright launches it the same way).
        r = subprocess.run([chrome, "--headless", "--no-sandbox", "--no-pdf-header-footer",
                            f"--print-to-pdf={out}", f"file://{f.name}"], capture_output=True,
                           text=True, timeout=120)
    finally:
        os.unlink(f.name)
    if r.returncode or not os.path.isfile(out):
        raise SystemExit(f"make_minicourse: printing {out} failed:\n{r.stderr[-2000:]}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Write the dry run's synthetic mini-course.")
    p.add_argument("outdir")
    p.add_argument("--chrome", help="a headless Chromium binary")
    args = p.parse_args(argv)
    chrome = find_chrome(args.chrome)
    out = os.path.abspath(args.outdir)
    expected = {}
    for name, (pages, facts) in (("L1-graphs-and-bfs", lecture1()),
                                 ("L2-shortest-paths", lecture2()),
                                 ("L3-spanning-trees", lecture3())):
        to_pdf(chrome, SLIDE_CSS, "".join(pages), f"{out}/course/lectures/{name}.pdf")
        expected.update(facts)
    q, s, facts = homework()
    to_pdf(chrome, DOC_CSS, q, f"{out}/course/homework/hw1.pdf")
    to_pdf(chrome, DOC_CSS, s, f"{out}/course/homework/hw1-solutions.pdf")
    to_pdf(chrome, DOC_CSS, SYLLABUS, f"{out}/course/syllabus.pdf")
    expected.update(facts)
    threads = ed_threads()
    os.makedirs(f"{out}/ed-raw/raw", exist_ok=True)
    for t in threads:
        with open(f"{out}/ed-raw/raw/{t['id']}.json", "w", encoding="utf-8") as f:
            json.dump({"thread": t, "users": USERS}, f, indent=1)
    with open(f"{out}/ed-raw/cursor.json", "w", encoding="utf-8") as f:
        json.dump({"course_id": 4242, "course": f"{COURSE} 2026 Fall",
                   "pulled_at": "2026-10-14T09:00:00Z",
                   "threads": {str(t["id"]): "fixture" for t in threads}}, f, indent=1)
    with open(f"{out}/answers.md", "w", encoding="utf-8") as f:
        f.write(ANSWERS)
    with open(f"{out}/expected.json", "w", encoding="utf-8") as f:
        json.dump(expected, f, indent=1, sort_keys=True)
    print(f"wrote the mini-course to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
