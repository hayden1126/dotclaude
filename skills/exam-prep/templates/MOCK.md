# MOCK: the mock exam and key format

Baseline as of 2026-10-20; changes only via `12-retro`.

A hub keeps a copy in `_build/MOCK.md`. Every mock writer follows it exactly: `mockpage.py` reads
the mock line by line and refuses anything outside this format, naming the line, and
`mock_key.py` reads the key's `Answer:` lines.

## The mock: `practice/mock-<slug>.md`

The header, everything before the first `---` line:

```markdown
# GRF101 Mock Exam 1

**Time:** 75 minutes. **Total:** 40 points.

**Rules.** Closed book; one cheat sheet, both sides.

Name: \_\_\_\_\_\_\_\_\_\_\_\_ ID: \_\_\_\_\_\_\_\_

| Question | Topic | Points |
|---|---|---|
| 1 | Graph basics | 10 |
| | **Total** | **40** |

---
```

- The title line comes first; the `**Time:**` line gives the minutes and the total points.
- Underscores in a write-in line are escaped (`\_`), or Markdown reads them as emphasis.
- The points table has a row per question, its number in the first cell and its points in the
  last, and a Total row; the builder checks each against the questions.

Then one block per question, separated by `---` lines:

```markdown
## Question 2: Shortest paths (12 points)

Type: trace
Topic: §2

The graph below has edge weights as shown. <the shared stem>

**(a) (6 pts)** Run Dijkstra from S. Give the order in which vertices are finalized.

_(answer space)_

**(b) (6 pts)** Explain why the result changes if edge (A, B) weighs -3.

Type: justify
Topic: §2, §3

_(answer space)_
```

- `## Question N: <title> (P points)`, numbered from 1 with no gaps; `(1 point)` for one.
- `Type:` and `Topic:` lines right under the heading set the question's tags; the same lines
  inside a part (after its prose) override them for that part. Several values: `Type: trace |
  compute`, `Topic: §2, §3`.
- `Type:` is one of: `trace`, `compute`, `table`, `justify`, `prove`, `classify`, `true-false`,
  `formulate`, `design`. It names the answer's shape, not the topic. Every part ends up with at
  least one type and one topic.
- `Topic:` values are the backbone's section numbers, `§N`.
- A part starts a line with `**(a) (k pts)**` (`(1 pt)` for one), letters in order from `(a)`.
  Every part carries its points, and a question's parts sum to its points. A question with no
  parts is answered whole and carries one implicit part, `(a)`, worth all its points.
- `_(answer space)_` on its own line marks where the student writes.
- The stem (prose before the first part) belongs to every part: the type and topic views show it
  with each part.

Inside a question or part, plain Markdown only:
- paragraphs, `**bold**`, `*italic*`, `` `code` ``;
- lists (`- ` or `1. `), one level;
- pipe tables;
- fenced code blocks (```), for pseudocode or a grid;
- math as `\( ... \)` inline and `\[ ... \]` display, never `$`; no `\href`, `\style`, `\class`,
  `\cssId`, `\data`, `\mmlToken`, `\require` or `\bbox` on any line (they make HTML);
- a figure: an `<svg ...>` block from a line starting `<svg` to a line ending `</svg>`, holding
  only `g`, `line`, `circle`, `ellipse`, `rect`, `path`, `polygon`, `polyline`, `text`, `tspan`,
  `title`, `desc`, `defs` and `marker`, nested strictly, with no event, `href` or `style`
  attribute, no `url()` but `url(#id)` and no `image-set()`, no backslash in an attribute but
  the `aria-label`, no attribute twice on one tag, no comment, no tag inside `title` or `desc`
  and none but `tspan` inside `text`, and no raw `<` in its text (`&lt;`). Draw every tree and
  graph this way, as the notes do (S11); a plain grid can be a code block. Each figure carries
  `role="img"` and an `aria-label` describing it, and its ids (a marker's) are unique in the
  mock and none is one the page uses (`q1`, `q1a`, `main`, `themeBtn`, `MathJax-script`,
  `view-...`, `MJX-...`). A figure defines every marker it uses (`url(#id)` names an id of its
  own figure). The type and topic views copy each figure, adding `-ty1`, `-to2s` and the like to
  its ids, and the build refuses a copy's id the page already has: end no id that way.
  Color comes from `CHASSIS.md`'s figure classes (`.bx`, `.accbx`, `.fill-surf`, `.dash`,
  `.mono`, `.mut`, `.sm`, `.acc`, each on the element it styles), never a fixed color, so the
  figure reads in both themes; an unstyled shape, an arrowhead too, takes the ink color.

No HTML besides the figure block, no links, no images, no headings below `##`, no `TODO-VERIFY`,
no control character.

## The key: `practice/mock-<slug>-key.md`

The page build never opens it (FB-154), and no agent reads it, nor `practice/mock-values-key.md`
or `_build/verify/mock_key.py`, which computes its values: only the main session, which writes
it, and the scripts that check it (`mock_key.py`, `mock_leak.py`).

```markdown
# ANSWER KEY: GRF101 Mock Exam 1

> **STOP. Quarantined key.** Attempt `practice/mock-exam1.md` under exam conditions (75 minutes,
> the mock sheet only) before opening this file. Every computable answer is asserted by
> `_build/verify/mock_key.py`, which prints `KEY OK`.

Conventions: <the tie-break and reporting conventions the answers follow>.

---

## Question 2

**(a)** Answer: S A B C T, dist(T) = 7

The finalization order follows the priority queue; ties break alphabetically ([L2 p.4]).

**(b)** Answer: With S to A 1, S to B 2 and B to A -3, A is finalized at 1 before the path S B A of weight -1 is seen.

<working, citations>

---

## Variants

- Every forest on n vertices with k trees has n - k edges. True: <why, cited>.
- Every connected graph on n vertices with n - 1 edges is a tree. True: <why, cited>.
```

- One bare `## Question N` heading per question (no title: the key checker and the leak check
  refuse an Answer: line under any other heading), and one `**(x)**` per part, the same parts as
  the mock.
- Each part's first line is `**(x)** Answer: <value>` on one line, the short form a student
  writes: a value, an order, a verdict with its witness. Working and citations follow below it.
- A computable answer's value is copied from `practice/mock-values-key.md`, which
  `mock_key.py` writes, never worked by hand (hard rule 3).
- With no sheet (`07-cheatsheet` skipped), the STOP line says "(75 minutes, no notes)". With no
  checker (PLAN.md's Checker line), its last sentence reads "Every answer is cited from its
  source; `_build/verify/mock_key.py` checks the parts and prints `KEY OK`." instead.
- `## Variants`, last, only in the key of the mock taken last (the harder set, or the one mock, as
  in the example): every variant `_build/mock-plan.md` lists that no mock asks, as a bullet with
  its verdict and witness (FB-151). An earlier key never holds one, since the student opens it
  before the later mocks.
