# ANSWER KEY: GRF101 Mock Exam 1

> **STOP. Quarantined key.** Attempt `practice/mock-exam1.md` under exam conditions (50 minutes,
> the mock sheet only) before opening this file. Every computable answer is asserted by
> `_build/verify/mock_key.py`, which prints `KEY OK`.

Conventions: Dijkstra breaks ties alphabetically; a vertex order is written space-separated.

---

## Question 1

**(a)** Answer: 6

The degrees sum to 12, and each edge adds 2 to the sum ([L2 p.3]).

**(b)** Answer: 3

With x vertices of degree 3 and y of degree 4: x + y = 5 and 3x + 4y = 18, so y = 3.

---

## Question 2

**(a)** Answer: S A B C T, dist(T) = 7

S 0; A 2; B 3 through A; C 4 through B; T 7 through C ([L3 p.5]).

**(b)** Answer: With S to A 1, S to B 2 and B to A -3, A is finalized at 1 before the path S B A of weight -1 is seen.

Dijkstra finalizes the smallest tentative distance and never revisits it; a negative edge into a
finalized vertex can still shorten its distance.

---

## Question 3

**(a)** Answer: 2

The closed 3-walks from vertex 1 are 1 2 3 1 and 1 3 2 1.

---

## Question 4

**(a)** Answer: True

**(b)** Answer: False: a triangle plus an isolated vertex

**(c)** Answer: False: two disjoint triangles

**(d)** Answer: True

---

## Variants

- Every forest on n vertices with k trees has n - k edges. True: sum n - 1 over the k trees.
- Every connected graph on n vertices with n - 1 edges is a tree. True: connected with n - 1 edges has no cycle.
- A connected graph in which every vertex has even degree has an Euler circuit. True: Euler's theorem.
