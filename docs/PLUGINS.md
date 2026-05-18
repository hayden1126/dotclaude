# Plugins

Quick reference for the plugins this setup enables. Authoritative source: each plugin's own marketplace.

## `superpowers@claude-plugins-official`

A skills framework. Ships rigid process skills (TDD, debugging, brainstorming, plan execution, parallel subagent dispatch, verification-before-completion) and meta-skills for writing new skills. Skills override default behavior — the `using-superpowers` skill auto-invokes on every session start to enforce the discipline.

- Repo: https://github.com/anthropics/claude-plugins-official
- Key skills: `using-superpowers`, `brainstorming`, `test-driven-development`, `systematic-debugging`, `writing-plans`, `executing-plans`, `subagent-driven-development`, `dispatching-parallel-agents`, `frontend-design`, `requesting-code-review`, `receiving-code-review`, `verification-before-completion`, `using-git-worktrees`, `writing-skills`, `finishing-a-development-branch`.

## `context7@claude-plugins-official`

Live, version-accurate library documentation lookup. Use whenever the user asks about React, Next.js, Prisma, Django, etc. — even well-known ones — to avoid stale training data.

- MCP tools: `resolve-library-id`, `query-docs`.
- Paired rule: `rules/context7.md` makes lookup automatic.

## `frontend-design@claude-plugins-official`

Production-grade frontend design skill — generates polished React/HTML/CSS without the generic-AI look. Use for web components, pages, and apps.

## `chrome-devtools-mcp@claude-plugins-official`

Drive a real Chrome instance via DevTools Protocol from inside Claude Code — click, type, screenshot, network requests, console messages, performance traces, a11y audits, Lighthouse, memory snapshots. Requires Chrome running with `--remote-debugging-port=9222`; configured in `settings.json` `pluginConfigs`.

## `context-mode@context-mode`

Context window protection. Sandboxes large command output and web fetches into an FTS5-indexed knowledge base; only summaries enter the main context. Tools: `ctx_batch_execute` (primary research), `ctx_search`, `ctx_execute`, `ctx_fetch_and_index`, `ctx_stats`. Survives `/clear` and `/compact`.

- Repo: https://github.com/mksglu/context-mode

## `claude-mem@thedotmack`

Cross-session persistent memory layered on top of the project. Builds corpora of observations from each session and injects relevant context into new sessions automatically. Skills: `mem-search`, `babysit`, `make-plan`, `smart-explore`, `learn-codebase`, `pathfinder`, `timeline-report`.

- Repo: https://github.com/thedotmack/claude-mem

## `ecc@ecc` (Everything Claude Code)

A large, opinionated agent + skill + command library covering coding standards, language-specific reviewers/builders/test runners (Python, Rust, Go, Kotlin, Swift, C++, Flutter, Java, etc.), domain skills (security review, accessibility, SEO, healthcare, finance), and orchestration (GSD-style multi-agent workflows, audit pipelines, model routing). The `/audit` and `/audit-fix` slash commands and many `ecc:*` skills come from here.

- Repo: https://github.com/affaan-m/everything-claude-code
- Note: ECC also ships GSD-style hooks. If you install ECC, the hook references in `settings.json` to `$HOME/.claude/hooks/gsd-*.{js,sh}` should resolve.

## Standalone CLI tools (see `tools.json`)

These are not Claude Code plugins — they're CLIs installed alongside Claude Code that drop assets into `~/.claude/`. `setup.sh` installs them from `tools.json`.

### `gsd` — get-shit-done

The workflow toolkit referenced by every `gsd-*` hook in `settings.json`. Ships ~50 skills (`gsd-plan-phase`, `gsd-execute-phase`, `gsd-verify-work`, `gsd-ship`, etc.), the agents that back them (`gsd-planner`, `gsd-executor`, `gsd-verifier`…), the hook scripts under `~/.claude/hooks/gsd-*.{js,sh}`, and the runtime at `~/.claude/get-shit-done/`.

- npm: `get-shit-done-cc` (https://github.com/gsd-build/get-shit-done)
- Install: `npx -y get-shit-done-cc` (idempotent — re-runs upgrade)

### `sourced` — academic-writing framework

Powers the four user-authored agents in `agents/` (`voice-extractor`, `prose-drafter`, `source-finder`, `sourced-helper`). Ships voice + style libraries at `~/.claude/voice/` and `~/.claude/style/` plus the `sourced` Python CLI for project setup.

- Marked `installer: manual` in `tools.json` (private editable repo).
- If you don't write academic papers in Claude Code, ignore it — delete the four `agents/` files.
