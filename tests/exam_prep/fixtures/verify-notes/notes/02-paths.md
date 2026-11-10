# §2 Paths

Breadth-first search finds a path with the fewest edges. It counts edges, as [§1.2 Three counting rules](#sec-1-rules) counts choices.

## 2.1 Breadth-first search {#sec-2-bfs}

BFS expands the shallowest node first [D2 p.7]. Ties go alphabetically [D2 p.8].

Step 1: Put the start on the frontier.
Step 2: Expand the frontier's first node and add its new neighbours.
Step 3: Stop when the goal is expanded.

<!-- FIG fig-2-graph: the graph S to A, S to B, A to G, B to G -->

> **Worked example 2.1: BFS from `S` to `G`** {#ex-2-bfs}
> Setup: edges `S`-`A`, `S`-`B`, `A`-`G`, `B`-`G`; ties alphabetical.
> Step 1: expand `S`; the frontier is `A`, `B`.
> Step 2: expand `A`; the frontier is `B`, `G`.
> Step 3: expand `B`; `G` is on the frontier already.
> Step 4: expand `G`, the goal.
>
> | Step | Expanded | Depth |
> | --- | --- | --- |
> | 1 | `S` | 0 |
> | 2 | `A` | 1 |
> | 3 | `B` | 1 |
> | 4 | `G` | 2 |
>
> **Result:** visit order `S`, `A`, `B`, `G`; distance 2.
> **Conclusion:** BFS reaches `G` at distance 2, the fewest edges.

**How it's tested:** trace BFS and give the visit order. Practice: [HW2 Q3b].

> **Not on Exam 1:** bidirectional search, past the scope cut [D2 p.20].

## 2.2 Must know {#sec-2-must-know}

1. **Order:** shallowest first ([§2.1](#sec-2-bfs))
2. **Ties:** alphabetical ([§2.1](#sec-2-bfs))
