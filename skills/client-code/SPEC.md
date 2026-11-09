# client-code: spec

The public spec for the `client-code` skill: what it covers, the two rules it enforces, how, why it stays slim, and the public source behind each rule. The tracker rules are a default for a developer who may have EU or UK users. They are not legal advice.

## Scope

The skill covers third-party trackers and destructive actions in a UI. It owns LEG-01 (with LEG-04) and UX-63, both enforced. Interaction, layout and responsive rules stay in `frontend-ui-discipline`, and motion in `frontend-motion`.

Files:
- `SKILL.md`: the core rule, the gate rules, then what to do when the hook stops an edit.
- `events.toml`: the two rules and the gate lines for the post-compaction digest. It has no event: see the L1 test below.
- Samples for every form the rules read: `tests/setup/practices_samples/client-code.toml`.

## Core rule

Build the safe form by default and say so in the reply. Never offer it as an option.

Why it comes first: the request reads as complete without the guard. "Add analytics" and "a Delete button that calls X" name no consent step and no confirm, the tests pass, and the demo works. In a sweep with no skill loaded, a tracker shipped with no consent gate in every run where the repo didn't say where its users were, and a Delete button deleted on one click in every run, on every model tried.

A repo that says nothing about its audience gets the gate. The gate costs a banner when it wasn't needed. Its absence costs a breach when it was, and only the repo can say which.

## Enforcement

| level | what | when |
|---|---|---|
| L0 | The description, written as "Use when" plus concrete triggers, with no workflow summary | the model's choice |
| L2 | Each rule's `when` against the new text an edit writes, `unless` against the file after the edit, denied once per file | before the edit lands |
| L3s | The same rules on the added lines of a commit, `unless` on the committed file, told to the model | after the commit |
| push | The same scan on what a push would send, denied once per new finding | before the push |
| L4 | The gate lines after a compaction, when the skill was loaded | SessionStart(compact) |

**LEG-01** reads `.js`, `.jsx`, `.ts`, `.tsx`, `.html`, `.vue` and `.svelte`: `googletagmanager.com`, `gtag(`, `static.hotjar.com`, `hj(`, `clarity.ms`, `connect.facebook.net`, `fbq(`, `cdn.segment.com`, `posthog.init`, `Hotjar.init(`, `hotjar.initialize(`, `Clarity.init(`, `ReactGA.initialize(`, `<GoogleAnalytics` and `<GoogleTagManager`. `consent` or a word starting `accept`, in any case, anywhere in the file, excuses it. Cookieless Plausible is left out on purpose.

**UX-63** reads `.tsx`, `.jsx`, `.vue` and `.svelte`: a bare or dotted call whose name starts `delete`, `remove` or `destroy` and an upper-case letter, the same name passed by name as a click or submit handler or a form action, with `.bind(` too, and `method: "DELETE"` in either quote. `.removeItem`, `.removeEventListener`, `.removeChild`, `.removeAttribute` and `.removeProperty` are left out, since they clean up the browser and delete nothing a user owns. `confirm`, `Undo` or `undo` starting a word or a camelCase part (not `undone`, not inside `foundOrder`), `alertdialog`, `<dialog` or `showModal`, in any case, anywhere in the file, excuses it.

Known misses:
- **LEG-01:** a file holding `consent` or `accept` for another reason, Consent Mode included, whose tag has already loaded; a vendor, or a vendor's form, not listed.
- **UX-63:** a bare `.delete(`, since `Map`, `Set` and `URLSearchParams` use it, and with it `axios.delete(`; a delete under another name (`onDelete(id)`, `mutate(id)`); a delete in an `.html`, `.js` or `.ts` file, a `.js` component included, since plain `.js` is mostly server code; a guard word used for something else (`confirmPassword`).

Accepted false matches, each costing one resend: a gate or confirm in another file or in words the pattern misses, a test file (a glob can't exclude), a comment naming a tracker, a function's own definition, and a cart's bare `removeItem(id)`-style call, `removeItemFromCart`, or `removeListener` cleanup.

## Per-repo layer

- `.claude/practices/client-code.md`: prose repo rules the skill reads first, such as where its users are or its dialog component. They win over the defaults.
- `practices-allow: <id> <reason>` in the file passes that rule for the file. Turning a rule off for a dir is `practices-gate`, run by hand.

## Rules

| id | rule | proof | levels | public source |
|---|---|---|---|---|
| LEG-01 | Gate every non-essential tracker behind prior opt-in for EU and UK users. | no tracker request before accept, in a real browser | L2, L3s, push | [ePrivacy 5(3)]; [EDPB consent] |
| LEG-04 | Session replay and heatmaps need the same consent, with inputs masked. | no replay script or global before accept | through LEG-01 | [ePrivacy 5(3)] |
| UX-63 | Give a destructive action a confirm naming what goes, or an undo window. | one click sends nothing, and the confirm or undo path sends it | L2, L3s, push | [NN/g confirmation]; [WCAG 3.3.4] |

## Why it is slim

Two enforced rules, two gate lines, no event. Earlier skills in this suite measured that each extra piece of advice makes weaker models build more and break more, so a client skill that tried to hold every UI rule would do harm. The interaction rules stay in `frontend-ui-discipline`, which loads for the CSS and plain-site work they apply to and also ships to Codex. No sweep measured a failure on them.

## The L1 test

An L1 event denies an edit until the skill is loaded, which costs every session that touches the path a round trip. It is added only when all three hold:
1. A measured failure exists in the eval, on a real case.
2. The bug is an absence that no pattern can see, so an L2 rule can't catch it.
3. The fix needs more than a deny line carries.

Both rules fail the second and third. A missing consent gate or confirm looks like an absence, but the tracker URL and the delete call are text a pattern sees, and `unless` reads the rest of the file for the guard. Each fix fits in the deny line.

What would revisit it: an eval of this skill where the deny arrives and the model still builds a broken gate or confirm, because the line can't carry the fix.

## Unmeasured

- What the denies add on their own. In the eval, the skill took each target from a fail in every no-skill run to 0 fails in 5, on Haiku, Sonnet and Opus 5.5, with and without the hook and after a compaction, and the hook denied nothing.
- LEG-04's input masking: no hook or oracle reads it, and the skill only says to keep it on.
- Every tracker form but Google Analytics and Hotjar. The others come from each vendor's documentation, not from a run.
- Whether "the repo says it has no EU or UK users" is read correctly from a repo's notes.

## Sources

- [ePrivacy 5(3)]: Directive 2002/58/EC, Article 5(3), https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32002L0058
- [EDPB consent]: European Data Protection Board, Guidelines 05/2020 on consent, https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-052020-consent-under-regulation-2016679_en
- [NN/g confirmation]: Nielsen Norman Group, Confirmation Dialogs Can Prevent User Errors, https://www.nngroup.com/articles/confirmation-dialog/
- [WCAG 3.3.4]: WCAG 2.2, Error Prevention (Legal, Financial, Data), https://www.w3.org/WAI/WCAG22/Understanding/error-prevention-legal-financial-data.html
