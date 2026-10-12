---
name: autopass
description: Turn auto-pass on or off for this tmux tab, or show its status (`/autopass on|off|status`). A hook answers it without a model turn; this body runs only when that hook is missing.
disable-model-invocation: true
---

# autopass

The autopass hook isn't installed; run ./setup.sh in dotclaude.

Say only that line to Hayden, and do nothing else: `/autopass` is answered by `hooks/autopass-toggle.sh` on UserPromptSubmit, which writes the tab's flag and blocks the prompt. Reaching this body means the hook isn't wired in `~/.claude/settings.json` or its script is missing.
