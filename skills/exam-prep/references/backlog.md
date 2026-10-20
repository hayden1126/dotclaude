# Backlog

Baseline as of 2026-10-20; changes only via `12-retro`.

Improvements found but not applied. The templates and workflows encode the two past runs as they
were. This list holds what a critique of those products, or the harvest, says could be better.
Nothing here is applied during a build. Before a round, the student picks items to try. The round's
retro keeps what worked (moving it into STYLE, CHASSIS or a workflow, and marking it `kept`) and
marks the rest `dropped`, with the reason.

- **Sev:** `high` costs exam points or study time on every use, `medium` is real friction, `low` is
  polish.
- **Evidence:** `K-<axis>.F<n>` is a finding from the critique of the two runs' products, with
  axes `org`, `word`, `struct` and `ui`. Harvest ids work as in `feedback-log.md`. Both are private.
- **Status:** `open`, `trying (round N)`, `kept (round N)` or `dropped (round N: why)`.
- **Conflicts** name an existing rule the item would change. Ask before trying those.

## High

| Id | Item | Axis | Evidence | Status |
|---|---|---|---|---|
| K01 | Keep exam scope as one fact per section and per question, and generate every in/out marker from it: the sidebar, the exam-day map, the mock's totals and time budget, the cheat sheet. A scope cut then reaches every product at once. | org | K-org.F1, K-word (other axes) | open |
| K02 | Build the tiered cram order (points per minute, minute budgets) into the top of the notes, open by default and linked to anchors, from the same weight data as the exam-day map. | org | K-org.F2 | open |
| K03 | Route every mock part to its notes subsection (a link) and to its key entry (behind a reveal). The key ends each answer with a review link and a per-step points split. The points table links to its questions. | org, struct, ui | K-org.F3, K-struct.F6, K-ui.F10 | open |
| K04 | When the exam's answer is a table (a trace), write the worked example and the key answer as that table, one numbered step per row. Prose steps stay for derivations and proofs. | struct | K-struct.F1 | open |
| K05 | Worked-example steps reuse the recipe's step numbers (or tag the recipe step each applies), and the cheat sheet keeps the recipe's step count and numbering. | struct | K-struct.F2, K-struct.F14 | open |
| K06 | Reserve the highlight band for key terms at their first definition. Run-in labels and step leads are bold with no band. A build lint caps bands per subsection. | ui | K-ui.F1 | open |
| K07 | One word per concept and one symbol per meaning, from a per-course glossary and notation table: one name for each event, a fixed label for each sense of an overloaded word, `⇒` only between properties with one primary name on both sides, synonyms listed once at the definition. | word | K-word.F1, K-word.F2, K-word.F4, K-word.F7, K-word.F13, K-word.F15 | open |
| K08 | A definition carries its conditions (for example, the adversary a goal holds against), and every later use states the same condition. | word | K-word.F3 | open |
| K09 | A removed em dash becomes a colon, parentheses or a full stop, never a comma; a lint flags comma appositions in headings and steps. | word | K-word.F5 | open |

## Medium

| Id | Item | Axis | Evidence | Status |
|---|---|---|---|---|
| K10 | The notes are the superset: anything added to the cheat sheet or the key lands in a notes subsection first, and a check maps every sheet item to a notes anchor. | org | K-org.F4 | open |
| K11 | Question type means answer shape only, from a closed list checked at build, assigned per part; the question header lists its parts' types. Type and topic groups sort by points and count a multi-tag part once. | org, struct, word, ui | K-org.F5, K-org.F14, K-struct.F5, K-word.F17, K-ui.F19 | open |
| K12 | Generate the exam-day map's rows from the same shape taxonomy used to tag the mock, so every tagged shape has a row; where the exam reuses known questions, key the rows to them. | org | K-org.F6 | open |
| K13 | One generated N.M numbering for every heading, the sidebar, the maps and link text. | org, struct, ui | K-org.F7, K-struct.F7, K-ui.F13 | open |
| K14 | A worked example sits in the subsection whose procedure it applies; a check flags misplaced ones. | org | K-org.F8 | open |
| K15 | A fixed order inside each subsection: definition, summary or decision table, procedure, worked example, how it's tested, pitfall, then proofs (collapsible). | org | K-org.F9 | open |
| K16 | Generate the Must-know and cheat-sheet copies of a canonical block from that block (or make them link-only), so lettered sets stay identical in every product. | org, word | K-org.F10, K-word.F19 | open |
| K17 | On the cheat sheet each item has one home; answer templates point to blocks by name instead of restating them. | org, struct | K-org.F11, K-struct.F9 | open |
| K18 | Every course gets a practice page shaped like the exam's source, even when no cheat sheet is allowed. | org | K-org.F12 | open |
| K19 | One "all Must know" view (a page or a toggle). | org | K-org.F13 | open |
| K20 | One place owns each idea: a figure's caption doesn't give away the result its step-through drills, and a caveat is written once and linked. **Conflicts:** S30 (a caveat where the plain number first appears). | struct, word | K-struct.F3, K-word.F16 | open |
| K21 | Put each pitfall at the step or claim it guards ("Trap:" inside the step); at most one cross-cutting pitfall closes a subsection. | struct | K-struct.F4 | open |
| K22 | A fixed set of block types: worked example (fresh numbers, collapsed, right after its procedure), slide trace (open, labeled), proof (inline, numbered, ending in a QED mark). | struct | K-struct.F8 | open |
| K23 | Inside a cheat-sheet block, one claim per line in a fixed order (rule, example, trap), or a small table. | struct | K-struct.F10 | open |
| K24 | Never place a figure between a colon and what it introduces; a map figure that organizes a subsection comes first. | struct | K-struct.F11 | open |
| K25 | Inline math stays plain inline with no overflow (a scroll box's baseline floats the math and orphans punctuation); only display math scrolls; glue trailing punctuation to the math. **Conflicts:** L12 (the current fix for the stray inline scrollbar). | ui | K-ui.F2 | open |
| K26 | Give every section accent its own dark-mode highlight band; check each section in both schemes. | ui | K-ui.F3 | open |
| K27 | Ship the cheat sheet's font with it (or a universal one) and print from one pinned renderer, so a wider fallback font can't push the last column off the page. | ui | K-ui.F4 | open |
| K28 | A 6 pt floor that includes superscripts, subscripts and figure text. **Conflicts:** FB-131 (the student picked a 5 pt floor). | ui | K-ui.F5 | open |
| K29 | Phone wayfinding: show the active section in the top bar, make drawer rows at least 44 px, label the theme button. | ui | K-ui.F6 | open |
| K30 | Design figures for a 340 px column (or a stacked variant) with a minimum rendered label size and tap to zoom. | ui | K-ui.F7 | open |
| K31 | Give clipped overflow boxes a scroll cue, and break long display equations at phone width. | ui | K-ui.F8 | open |
| K32 | The mock's paper view hides type chips (the real exam has none); printed answer space scales with points. | ui | K-ui.F9 | open |
| K33 | Work offline: vendor MathJax (or pre-render the math) and self-host the fonts in every product, the mock included. | ui | K-ui.F11 | open |
| K34 | A recipe's first step defines every symbol it uses, with its start value; every bound names its quantity. | word | K-word.F6 | open |
| K35 | One Conclusion per construction, at most two sentences: the result, then the property it rests on. Variants come before the Result. | word, struct | K-word.F8, K-struct.F17 | open |
| K36 | No internal ids or authoring labels in rendered text; the build fails on id-like strings and empty "Practice: (none)" lines. **Conflicts:** S9 (every subsection's line names its practice, "none" included). | word, struct | K-word.F9, K-struct.F20 | open |
| K37 | Number only actions; a premise goes in a "Why it works" line. A coined term is defined once. | word | K-word.F10 | open |
| K38 | Check every rule's wording at its boundary input ("next multiple after" versus "smallest multiple at least"). | word | K-word.F11 | open |
| K39 | A causal "so" or "because" names the same property everywhere it recurs; review causal claims across sections, not only within one. | word | K-word.F12 | open |
| K40 | Inequality chains run one way; a compressed line keeps its subject, condition and result. | word | K-word.F14 | open |
| K41 | Build the site from the markdown automatically, so a notes edit is made once instead of in the markdown and again in a hand-ported fragment. | harvest | B3.G13, B4 (section 5d) | open |
| K42 | Ship a content-free chassis with explicit insertion markers, instead of slicing a full page by line patterns. | harvest | B4 (section 5d) | open |
| K43 | The page checker reads section and figure ids from the backbone registry instead of hard-coding them. | harvest | B4 (section 5d) | open |
| K44 | Generate the key-leak markers from the key itself. | harvest | B4 (section 5a) | open |

## Low

| Id | Item | Axis | Evidence | Status |
|---|---|---|---|---|
| K50 | Every h4 gets a stable id so maps and the cram order can link to it. | org | K-org.F16 | open |
| K51 | Put the section-dependency map at the top, next to the exam-day map. | org | K-org.F17 | open |
| K52 | Each read-first item names its prerequisites. | org | K-org.F15 | open |
| K53 | At most three heading levels; no one-item lists. | struct | K-struct.F12 | open |
| K54 | Letters only for canonical sets, numbers only for steps, (i) and (ii) inside an exam part, in the mock as in the notes. | struct | K-struct.F13, K-struct.F18 | open |
| K55 | Number figures in sequence by subsection, letters only for panels, and link to an existing figure instead of redrawing it. | struct, word | K-struct.F15, K-word.F20 | open |
| K56 | Close each subsection with one generated "Next: [linked title]" line. | struct | K-struct.F16 | open |
| K57 | A shared code-block style (surface background, padding) for pseudocode in the notes and the mock. | ui | K-ui.F12 | open |
| K58 | Generate the accent palette from the section count with a minimum hue distance. | ui | K-ui.F14 | open |
| K59 | Emphasis keeps full ink color; the italic carries it. | ui | K-ui.F15 | open |
| K60 | Pressed buttons and faint text meet AA contrast (4.5:1). | ui | K-ui.F16 | open |
| K61 | Phone polish: drawer shadow only when open, no-wrap example labels, smaller section gaps under 600 px, a one-row mock bar. | ui | K-ui.F17 | open |
| K62 | Lint rendered HTML for paragraphs whose lines start with "- " (a list that didn't convert). | ui | K-ui.F18 | open |
| K63 | Center the active sidebar item and tint group headings with their section accent. | ui | K-ui.F20 | open |
| K64 | Apply the saved theme from an inline script in the head, before any blocking script. | ui | K-ui.F21 | open |
| K65 | One label per callout, and one callout vocabulary across products. | word, struct | K-word.F21, K-struct (other axes) | open |
| K66 | State quantities and causes plainly; no unanchored metaphors. | word | K-word.F18 | open |

## Keep (strengths the critique says must not regress)

These are recorded so a backlog item never trades one away by accident.

- The exam-day map as a question-to-section index with practice citations, keyed to known question
  ids when the exam reuses them.
- One canonical lettered set with anchors, linked back from every use.
- "How it's tested" per subsection with practice citations, and Pitfall callouts that quote the
  wrong belief before fixing it.
- A Must-know checklist per section; the cram order's tiers with minute budgets.
- The mock's three views, each part's setup repeated in a collapsible context block, and print CSS
  that hides the switcher.
- Traces state their conventions first, in the notes, the mock and the key.
- Section intros that link back, and the "which step needs which assumption" list after a proof.
- A 72-character reading column (Literata 17 px, line height 1.62), the sidebar with scroll-spy, the
  per-section accents, four callout types with their own wash in both schemes, collapsed worked
  examples, and the step-through figures.
- The cheat sheet's topic color bars, five landscape columns, white paper in dark mode, the write-in
  name box and a one-column phone fallback.
- A standing "how to read every claim" callout where direction matters, and Conclusions that name
  what holds and what doesn't.
