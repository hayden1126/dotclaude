# STYLE: how the notes are written

Baseline as of 2026-10-20; changes only via `12-retro`.

Content only: pedagogy, wording and structure. The look (layout, palette, components, how figures
are drawn) is `CHASSIS.md`'s, since the two change at different speeds. A hub keeps a copy in
`_build/STYLE.md`; `11-next-exam` reconciles that copy with this one.

Ids are stable. S1 to S13 are the two past runs' rules, numbered as hubs cite them; S14 on came
from later corrections. A retired rule is struck through and keeps its number. An example labeled
"(a search course)" illustrates a rule; it is not part of it. Each rule's evidence is in
`references/feedback-log.md` (FB-070 for S1 to S13).

## Structure and pedagogy

- **S1. Pedagogy.** Each section opens with a one-to-three sentence prose intro that frames the
  concept and links back to what it builds on ("Recall from §4 that ..."). A concept is introduced
  before its first use, and each subsection says how it connects to the next.
- **S2. Structure over prose.** Short prose mixed with well-enumerated points. A tight hierarchy,
  nested at most three levels, in few words, with each key term bold at its first definition, so a
  reader can map how the ideas relate.
- **S3. Numbers for recipes, letters for sets.** An executable procedure is numbered steps
  (Step 1, Step 2, ...). A fixed set that other text refers to gets letters, a) b) c), lettered
  once, in the section the backbone's registry names, with an anchor per member that the section's
  writer adds; every other mention links to it. Example
  (a search course): the four evaluation criteria; the environment properties.
- **S4. Conclusion lines.** Every construction and every worked example ends with an explicit
  `Conclusion:` line.
- **S5. Direction and causation.** Say which condition guarantees which result, and which proof
  needs which property. Never leave an implication arrow ambiguous. Example (a search course):
  "consistent ⇒ f never decreases along a path ⇒ graph-search A* is optimal"; "admissible is
  enough for tree search only".
- **S6. No redundancy.** The text states the rule, the figure shows the mechanism, the example
  applies it; none re-explains the others. Back-links and recalls stay: they aren't redundancy.
- **S7. Worked examples** use fresh numbers, never a homework's or a recitation's, with numbered
  steps and a bold **Result**. Their data and traces come from the checker (in a course with
  none, from the cited sources). On the page they are collapsible and closed by default. The
  notes quote an answer only from a set the student has attempted (MANIFEST's `yes, attempted`);
  the mock's key lives in its own quarantined file.
- **S8. Conventions.** Every convention an answer depends on is stated once, in the subsection the
  backbone names, and every use says which convention applies, with a link there. Example (a
  search course): the tie-break order; goal test at expansion or at generation; an explored set or
  none; successor order and the push order.
- **S9. How it's tested.** Each subsection has a "How it's tested" line: the answer shape the
  exam asks for and the practice questions that drill it ("Practice: [HW1 Q2c], [Rec5 Q6]").
  Pitfall callouts mark the classic mistakes.
- **S10. Citations and notation.** Cite as `[D5 p.23]`, `[D2 #/14]` or `[HW1 Q2c]`; no external
  slide links (the sources are local). A section of another document is cited in brackets too
  (`[W1 §2.1]`), so it can't be mistaken for one of the notes' own sections. No em dashes. Math
  in LaTeX: `\( \)` inline, `\[ \]` display. When the student reads in a plain-text tool instead
  of the page, write for that tool: no LaTeX, pipe tables, cross-references as text.
- **S11. Figures** only where a cold reader would otherwise assemble a mechanism from prose. A tree
  or graph example always gets a drawn figure, never ASCII art, and prose that only re-describes a
  figure goes. How a figure is drawn is `CHASSIS.md`'s and `CONVERT.md`'s.
- **S12. Cross-references are clickable links, never bare text.** Every mention of an earlier or
  later concept, worked example, figure, step or lettered set member links to it, such as (a search
  course) `[§5.2 Admissible vs consistent](#sec-5-admissible-vs-consistent)`. Every target has a
  stable id fixed in the backbone before writing starts (`sec-N-<slug>`, `ex-N-<slug>`,
  `fig-N-<slug>`, `set-<name>-a`). A step links only when the backbone gives it an id; otherwise the
  link goes to its procedure's subsection. Link text names the target ("Worked example 4.3", "Fig
  5.1", "property (b)"), never "here". Recalls ("Recall from §4") and forward pointers ("used again
  in §7.3") are both links. In notes read in a plain-text tool (S10), a cross-reference is text
  naming the section instead.
- **S13. The look.** Keep the approved chassis and don't regress it; `CHASSIS.md` holds its rules.
  Writers and converters add content only, into the chassis's own classes: no inline styles and no
  new CSS. Any CSS change is the main session's, checked against the chassis screenshots.

## Wording

- **S14. The reader may have skipped the lectures.** Assume no prior exposure.
- **S15. Define every symbol and acronym at its first use.** Gloss logic symbols and unusual
  notation in plain words where they appear.
- **S16. No exam-writer jargon** in text the student reads.
- **S17. Never coin labels for examples** (T1, Tree A). Name an example by its source page or its
  shape ("the tree on D7 p.34", "the four-node graph"). A label the course's own sources use is
  the course's term (S25), not a coined one.
- **S18. Unpacked over compressed.** Prefer a three-sentence explanation or a tiny worked instance
  to a compressed argument. A proof goes step by step on a small instance.
- **S19. Start from what it replaces.** Open a concept with how it compares to the one it replaces:
  what is the same, what differs, and why it exists.
- **S20. Background marked as background.** A derivation that only the slides carry and no
  practice question asks for is marked as background, with that evidence.
- **S21. Must know.** Every section ends with a "Must know" checklist: one line per point, each
  linked into the notes (in plain-text notes, S10, each names its subsection), as many points as
  the exam needs.
- **S22. Proof techniques.** When the exam asks for proofs, the notes carry a proof-techniques
  block (and so does the cheat sheet).
- **S23. A pitfall states its exact conditions.**
- **S24. Every step a reader would ask "why" about is explained** in plain words, in a bound or a
  derivation alike.
- **S25. The course's own terms.** Use the course's words, and list the aliases the course uses.
- **S26. Roles in a construction.** In a construction or a counter-example, label each object's
  role: the real input, the trusted component, the thing under test.
- **S27. What it provides, and what it doesn't.** Each mechanism's section says both.
- **S28. Both cases of a condition.** A conditional claim ("needs X only if Y") shows the normal
  case and the edge case.
- **S29. No compressed aphorisms.** Give the concrete situation instead: who holds what, which
  channel is trusted.
- **S30. Forward caveats.** When a later section qualifies a number, put a short caveat where the
  plain number first appears.
- **S31. Confusable pairs** get an explicit comparison table.
- **S32. One reconciliation.** Where the slides' convention and the answer keys' convention differ,
  reconcile them in one place and link there.
