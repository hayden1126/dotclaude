# Brief: a durable session-handoff mechanism (hook and/or skill) in dotclaude

> RESOLVED 2026-06-17. v1 is implemented as a skill: `skills/handoff/SKILL.md` (skill-only and
> advisory, the direction Hayden picked). The design rationale and the full plan are in
> `~/.claude/plans/read-docs-durable-handoff-brief-md-and-p-precious-cherny.md`. Two pieces are
> deliberately deferred, not forgotten: (1) any hook (a PreCompact safety-net or Stop-gate), revisit
> only after empirically testing the `SessionStart` `compact`-matcher re-inject path (open bug #15174);
> (2) the autonomous loop-engineering handoff (a Python orchestrator step that refreshes the RESUME
> block).
>
> UPDATE 2026-06-19: the lightweight-trigger half of the seed recommendation shipped as
> `hooks/handoff-reminder.sh`, a `UserPromptSubmit` advisory hook that nudges toward `/handoff` on
> wrap-up signals (PR #2). It only reminds, it does not perform the handoff, so the skill-only
> decision stands; deferral (1) now refers specifically to the deterministic PreCompact/Stop
> safety-net, which is still open.
>
> The sections below are kept as historical design context, do not re-run the brainstorming.

> ORIGINAL BRIEF (historical). It was a pre-design BRIEF, not a spec. The job was: explore the dotclaude
> setup, then run `superpowers:brainstorming` with Hayden to turn this into a design, then
> `writing-plans`, then implement. Written 2026-06-17 by a prior session that was handed off because its
> context was too full.

## The problem (why we are doing this)

Session handoffs are not durable. They depend on the model remembering, by discipline alone, to: update
the living status doc, scan for and fix doc drift, curate memory, commit cleanly, and note next steps.
When any step is forgotten, the next session resumes from a stale or incomplete picture. This is a
recurring, structural failure, not a one-off.

**Concrete evidence from the session that triggered this** (work in `~/loop-engineering`, where a
plan -> governor-approve -> execute phase was just built and shipped):
- After the feature merged, `SPEC.md` and `outer-loop/README.md` still described the OLD pipeline
  (they omitted the new phase). `EFFICIENCY.md` framing had drifted too. None of this was caught by any
  process; it surfaced only because Hayden explicitly asked "do we have stale docs?".
- Memory was never reviewed or updated during the session, even though a durable lesson emerged (see
  below), because nothing prompted it.
- The handoff and doc-fix commits stalled on an infrastructure outage and Hayden had to run them
  manually; there was no checklist ensuring the tree ended clean.

The durable lesson that session learned (worth encoding somewhere the handoff process would catch): the
loop's LLM gates (governor, reviewer) and makers default to FAITHFULNESS (did it match the spec?) over
SOUNDNESS (is the spec correct?); prompts had to be rewritten to make soundness the bar. That lesson
lives in `~/loop-engineering/STATUS.md` but was never promoted to memory.

## The goal

A mechanism that makes a COMPLETE handoff happen every time, with as little reliance on model discipline
as possible. It lives in `~/dotclaude/` (the shared Claude setup; `setup.sh` symlinks its skills, the
danger-guard hook, CLAUDE.md, and templates into `~/.claude/`, and copies `settings.json`). Because
`~/.claude` is the config every Claude Code session on the machine loads, a capability built here is
shared by Hayden's interactive sessions AND the loop-engineering inner-loop sessions. IMPORTANT nuance
(verified, see "Inner-loop inheritance mechanics" below): a SKILL is inherited by the inner loop for
free; a HOOK is not (the inner loop runs its own minimal hooks block). That shared reach is a core
reason to build it here rather than per-project.

## What a complete handoff must cover (the checklist this mechanism enforces or performs)

These are the candidate steps; brainstorming should confirm/trim them (YAGNI):
1. Update the living status/handoff doc (the `STATUS.md` RESUME-block convention loop-engineering uses)
   with current state + next steps.
2. Doc-drift scan: do the durable docs (SPEC/README/CLAUDE.md/etc.) still match the code and the
   changes just made? Fix or flag. This is the exact failure above.
3. Memory curation: add genuinely reusable lessons, prune stale ones, keep a good signal/noise balance
   WITHOUT over-recall that biases future sessions. (Hayden flagged "memory management, a good balance
   to not lead to bias" as a standing concern.)
4. Clean git state: everything intended is committed; uncommitted work is noted; tests green; nothing
   silently dropped.
5. Open items / next-session pointers captured.

## The design space (inputs for brainstorming; do not pre-decide, discuss with Hayden)

This is a genuine design fork. Hayden's rule: present options and pick a direction WITH him before
implementing.

- **Hook vs skill vs both.**
  - A SKILL is model-driven and can do JUDGMENT (detect drift, curate memory, decide what is stale). It
    does the actual work, but only if invoked. Could be `/handoff` plus a description that auto-triggers
    on "hand off"/"wrap up".
  - A HOOK is deterministic, event-driven (Stop / SessionEnd / PreCompact), a shell script with no LLM
    judgment. It cannot DO the semantic handoff, but it can ENSURE IT HAPPENS: e.g., a PreCompact or
    Stop hook that injects a reminder to run the handoff skill, or that refuses a clean Stop until the
    status doc has been touched this session.
  - SEED RECOMMENDATION (not a decision): a skill for the procedure + a lightweight hook as the trigger,
    with PreCompact as the most valuable trigger point (it fires exactly when context is about to be
    lost, which is when an unsaved handoff hurts most). Validate against the real hook events available.
- **Trigger(s):** explicit (`/handoff`, "hand off", "wrap up"); a context-threshold signal (Hayden
  wants sessions kept under ~40% of context, with handoff before they fill); SessionEnd; PreCompact.
- **Drift detection mechanism:** how does step 2 actually work? A skill step that compares the diff/
  recent commits against the docs and lists stale claims (the prior session did this by hand and via a
  read-only sub-agent audit, which worked well and is a good model). Decide how heavy this should be.
- **Enforcement strength:** purely advisory (remind), vs blocking (hard-gate the Stop), vs auto-perform.
  Stronger enforcement is more durable but more intrusive; pick deliberately.
- **Inner-loop inheritance mechanics (VERIFIED 2026-06-17):** a dotclaude SKILL reaches the inner loop
  for free; a HOOK does not. Authored skills live in `dotclaude/skills/` -> symlinked to
  `~/.claude/skills/` -> loaded by any session, including the inner puppet (skills are NOT gated by the
  per-session `enabledPlugins` toggles, and the inner session does load the global `~/.claude` env: its
  settings reference the global `danger-guard.sh` and enable the `superpowers` plugin). HOOKS do NOT
  inherit: the inner loop runs its own minimal hooks block (Stop = stop-notify + PreToolUse(Bash) =
  danger-guard only) in `~/loop-engineering/outer-loop/inner-interactive-settings.json` with most
  plugins OFF, so a new global hook must be added to that file explicitly. The headless maker
  (`maker-settings.json`) strips plugins entirely and inherits neither. CONSEQUENCE: if "the inner loop
  gets it for free" matters, prefer the SKILL path; a hook trigger needs a one-line opt-in in the inner
  settings file (and would still never reach the headless maker).

## Constraints and how to work

- Creative work: go through `superpowers:brainstorming` -> design spec
  (`docs/superpowers/specs/YYYY-MM-DD-*.md`) -> `superpowers:writing-plans` -> implement. The prior
  session invoked brainstorming but was interrupted before any design; start it cleanly.
- Follow existing dotclaude conventions: explore `skills/`, `hooks/`, `templates/`, `docs/`, and how
  existing skills/hooks are structured BEFORE designing. Do not reinvent. In particular this should
  COMPOSE with, not duplicate, existing capability: the `claude-md-management` skills
  (`revise-claude-md`, `claude-md-improver`), the file-based memory system (per-project memory files
  with frontmatter + a `MEMORY.md` index under `~/.claude/projects/<cwd-slug>/memory/`; the harness
  injects the format each session, and `~/.claude/CLAUDE.md` holds only a short Memory rule, not the
  full system), and the `templates/` (the STATUS/SPEC/PLAN templates Hayden seeds durable state from). NOTE: dotclaude vendors ONLY
  Hayden-authored content; plugin-owned skills/hooks install from marketplaces. A handoff skill/hook
  authored here is the right kind of thing to vendor.
- Hayden's global rules (`~/.claude/CLAUDE.md`): be an adversarial sparring partner, not a yes-man; ask
  before implementing on a design fork; no em dashes in prose/docs/commit messages (writing-voice);
  propose and confirm before any deletion; never `git push` or `git checkout`/reset without explicit
  approval; branch-first if committing on a default branch.
- Heads-up: during the originating session the Bash auto-safety classifier had repeated transient
  outages. If it recurs, Read/Grep/Edit/Write still work intermittently; `git` commits may need Hayden
  to run them via the `!` prefix. Do not let that block progress on the design itself.

## First steps for the fresh session
1. Read this brief, then explore `~/dotclaude/` structure (skills/, hooks/, templates/, settings.json,
   CLAUDE.md, README.md, setup.sh, sync.sh) and a couple of existing skills/hooks for the conventions.
2. Skim `~/loop-engineering/STATUS.md` for a concrete example of a good handoff doc and its RESUME-block
   convention, and its "Future capabilities to consider" section (context/memory/effort/model
   self-governance) which is adjacent to this work.
3. Re-invoke `superpowers:brainstorming` and work the design fork above with Hayden, one question at a
   time. Then spec, plan, implement.

## Pointer back
Originating work: the plan -> governor-approve -> execute phase in `~/loop-engineering` (master, merged
+ pushed). This brief was first committed in dotclaude as `c1feb8a`; this revision de-duplicates a
paste artifact and folds in the verified inner-loop inheritance finding.
