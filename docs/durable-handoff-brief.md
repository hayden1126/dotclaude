# Brief: a durable session-handoff mechanism (hook and/or skill) in dotclaude

> READ THIS FIRST if you are a fresh session picking up this work. It is a pre-design BRIEF, not a
> spec. Your job: explore the dotclaude setup, then run `superpowers:brainstorming` with Hayden to turn
> this into a design, then `writing-plans`, then implement. Do not skip brainstorming. Written
> 2026-06-17 by a prior session that was handed off because its context was too full.

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
as possible. It lives in `~/dotclaude/` (the shared Claude setup, synced to `~/.claude` via `sync.sh` /
`setup.sh`). Because dotclaude is also the setup the loop-engineering INNER LOOP runs under, a
hook/skill here is inherited by the machine's own autonomous sessions, which need clean handoffs even
more than interactive ones do. That dual benefit (interactive + inner-loop) is a core reason to build it
here rather than per-project.

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
! mkdir -p ~/dotclaude/docs && cat > ~/dotclaude/docs/durable-handoff-brief.md <<'EOF'
# Brief: a durable session-handoff mechanism (hook and/or skill) in dotclaude

> READ THIS FIRST if you are a fresh session picking up this work. It is a pre-design BRIEF, not a
> spec. Your job: explore the dotclaude setup, then run `superpowers:brainstorming` with Hayden to turn
> this into a design, then `writing-plans`, then implement. Do not skip brainstorming. Written
> 2026-06-17 by a prior session that was handed off because its context was too full.

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
as possible. It lives in `~/dotclaude/` (the shared Claude setup, synced to `~/.claude` via `sync.sh` /
`setup.sh`). Because dotclaude is also the setup the loop-engineering INNER LOOP runs under, a
hook/skill here is inherited by the machine's own autonomous sessions, which need clean handoffs even
more than interactive ones do. That dual benefit (interactive + inner-loop) is a core reason to build it
here rather than per-project.

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
- **Inner-loop inheritance mechanics:** CONFIRM the inner loop actually loads dotclaude skills/hooks.
  The loop-engineering inner sessions run with a specific settings file
  (`~/loop-engineering/outer-loop/inner-interactive-settings.json`, superpowers ON, chrome-devtools
  OFF, a Stop hook + a danger-guard PreToolUse hook). Check whether global dotclaude skills/hooks reach
  that session or whether the settings file must opt in. This determines whether "build it in dotclaude"
  truly gives the inner loop the capability for free.

## Constraints and how to work

- Creative work: go through `superpowers:brainstorming` -> design spec
  (`docs/superpowers/specs/YYYY-MM-DD-*.md`) -> `superpowers:writing-plans` -> implement. The prior
  session invoked brainstorming but was interrupted before any design; start it cleanly.
- Follow existing dotclaude conventions: explore `skills/`, `hooks/`, `templates/`, `docs/`, and how
  existing skills/hooks are structured BEFORE designing. Do not reinvent. In particular this should
  COMPOSE with, not duplicate, existing capability: the `claude-md-management` skills
  (`revise-claude-md`, `claude-md-improver`), the file-based memory system (memory files with
  frontmatter + a `MEMORY.md` index, described in `~/.claude/CLAUDE.md`), and the `templates/` (the
  STATUS/SPEC/PLAN templates Hayden seeds durable state from).
- Hayden's global rules (`~/.claude/CLAUDE.md`): be an adversarial sparring partner, not a yes-man; ask
  before implementing on a design fork; no em dashes in prose/docs/commit messages (writing-voice);
  propose and confirm before any deletion; never `git push` or `git checkout`/reset without explicit
  approval; branch-first if committing on a default branch.
- Heads-up: during the originating session the Bash auto-safety classifier had repeated transient
  outages. If it recurs, Read/Grep/Edit/Write still work intermittently; `git` commits may need Hayden
  to run them via the `!` prefix. Do not let that block progress on the design itself.

## First steps for the fresh session
1. Read this brief, then explore `~/dotclaude/` structure (skills/, hooks/, templates/, settings.json,
   CLAUDE.md, README.md, sync.sh) and a couple of existing skills/hooks for the conventions.
2. Skim `~/loop-engineering/STATUS.md` for a concrete example of a good handoff doc and its RESUME-block
   convention, and its "Future capabilities to consider" section (context/memory/effort/model
   self-governance) which is adjacent to this work.
3. Re-invoke `superpowers:brainstorming` and work the design fork above with Hayden, one question at a
   time. Then spec, plan, implement.

## Pointer back
Originating work: the plan -> governor-approve -> execute phase in `~/loop-engineering` (master, merged
+ pushed). This brief is uncommitted as written; commit it in dotclaude.
