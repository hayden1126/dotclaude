# GRF101 Mock Exam 1

**Time:** 50 minutes. **Total:** 24 points.

**Rules.** Closed book; one cheat sheet, both sides.

Name: \_\_\_\_\_\_\_\_\_\_\_\_ ID: \_\_\_\_\_\_\_\_

| Question | Topic | Points |
|---|---|---|
| 1 | Degree sums | 6 |
| 2 | Shortest paths | 12 |
| 3 | Counting walks | 2 |
| 4 | True or false | 4 |
| | **Total** | **24** |

---

## Question 1: Degree sums (6 points)

Type: compute
Topic: §2

**(a) (3 pts)** A simple graph has degree sequence \((3, 3, 2, 2, 2)\). How many edges does it have?

_(answer space)_

**(b) (3 pts)** A graph on 5 vertices has 9 edges, and every vertex has degree 3 or 4. How many vertices have degree 4?

_(answer space)_

---

## Question 2: Shortest paths (12 points)

Type: trace
Topic: §3

The directed graph below has the edge weights shown.

<svg viewBox="0 0 320 140" role="img" aria-label="Directed graph: S to A weight 2, S to B weight 5, A to B weight 1, A to C weight 4, B to C weight 1, B to T weight 6, C to T weight 3">
  <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z"/></marker></defs>
  <g class="bx" marker-end="url(#arrow)">
    <line x1="30" y1="70" x2="100" y2="30"/>
    <line x1="30" y1="70" x2="100" y2="110"/>
    <line x1="110" y1="35" x2="110" y2="100"/>
    <line x1="115" y1="30" x2="200" y2="30"/>
    <line x1="115" y1="110" x2="200" y2="40"/>
    <line x1="115" y1="115" x2="280" y2="75"/>
    <line x1="210" y1="35" x2="280" y2="65"/>
  </g>
  <g><text x="15" y="75">S</text><text x="105" y="25">A</text><text x="105" y="130">B</text><text x="205" y="25">C</text><text x="285" y="75">T</text></g>
  <g><text class="sm" x="55" y="40">2</text><text class="sm" x="55" y="105">5</text><text class="sm" x="115" y="70">1</text><text class="sm" x="155" y="25">4</text><text class="sm" x="160" y="80">1</text><text class="sm" x="200" y="110">6</text><text class="sm" x="250" y="45">3</text></g>
</svg>

**(a) (6 pts)** Run Dijkstra's algorithm from S. Give the order in which the vertices are finalized and the distance to T.

_(answer space)_

**(b) (6 pts)** The relaxation step is:

```
if d[u] + w(u, v) < d[v]:
    d[v] = d[u] + w(u, v)
```

With a directed graph on three vertices, explain why Dijkstra's algorithm can finalize a wrong distance when one edge weighs \(-3\).

Type: justify
Topic: §2, §3

_(answer space)_

---

## Question 3: Counting walks (2 points)

Type: compute | table
Topic: §1, §2

The triangle \(K_3\) has the adjacency matrix *A* below.

| | 1 | 2 | 3 |
|---|---|---|---|
| **1** | 0 | 1 | 1 |
| **2** | 1 | 0 | 1 |
| **3** | 1 | 1 | 0 |

Give the number of closed walks of length 3 that start and end at vertex 1, that is

\[ (A^3)_{11} \]

_(answer space)_

---

## Question 4: True or false (4 points)

Type: true-false
Topic: §2

Mark each statement True or False. For each False, give a counterexample.

**(a) (1 pt)** Every tree on \(n\) vertices has \(n - 1\) edges.

_(answer space)_

**(b) (1 pt)** Every graph on \(n\) vertices with \(n - 1\) edges is a tree.

_(answer space)_

**(c) (1 pt)** A graph in which every vertex has even degree has an Euler circuit.

_(answer space)_

**(d) (1 pt)** With nonnegative weights, a distance Dijkstra has finalized never decreases later.

Topic: §3

_(answer space)_
