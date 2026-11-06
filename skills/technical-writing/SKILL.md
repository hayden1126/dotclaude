---
name: technical-writing
description: How to write or edit commit messages, PR descriptions, GitHub issues and comments, code review comments, READMEs, docs and reports, cited reports included. Enforces literal prose, a direct stance, brevity, no em dashes, and an iterate-until-clean loop. Not for chat with Hayden, messages or emails to people (formal-voice, casual-voice), or the essays, academic papers and other prose a sourced project drafts (its commits and PRs stay here).
---

# Technical writing

The reader has no context from the session and wants the facts. Write what happened, what it does and how we know.

## Core rule
Every word fights to stay. If a sentence adds nothing, cut it. If two sentences say the same thing, merge them into one shorter sentence.

**Iteration loop.** After a draft, reread every sentence and ask: does it add something new? does it repeat? does it sound AI-generated? does the section flow start to finish? If any answer is wrong, rewrite or cut, then reread again. Stop when a full reread surfaces nothing.

## Stance
State views clearly. Acknowledge real uncertainty, but don't hedge for safety.

## Say it literally
Apply these to what you write now. Don't sweep old docs for them.
- **No abstract metaphor nouns.** Substrate, wedge, vector, locus, nexus, paradigm, and "surface" or "harness" as metaphors. Name the thing or the mechanism.
- **No flourish where a literal phrase exists.** No aphorisms, personified code ("the plan holds it"), figurative verbs ("rides along") or stock framing phrases.
- **No over-compression.** Keep articles and verbs, and spell out arrows. "Parser rejects bad date → exit 2" becomes "The parser rejects a bad date and exits with code 2."

## Brevity
- 3 to 5 sentences per paragraph at most. Each paragraph has one job.
- Cut weak adverbs: really, very, quite, somewhat, basically, actually, honestly.
- Ground claims with numbers or comparisons, not vague qualifiers.
- Show the example first, then the principle.

## Punctuation and form
- Never use em dashes. Use parentheses, commas or colons.
- Start with substance, never a preamble.
- Bold for emphasis (not caps). Bullets where the content is a list.

## PR body
Use these headings, in this order. Why and Verification are always there. The others appear only when they say something, so a small PR stays small.
- **Why:** the problem, and who hit it.
- **What changed:** the behavior, not a file list.
- **Scope:** what this deliberately leaves out.
- **Tradeoffs:** what was given up, and the option not taken.
- **Blast radius:** what else this can break, and for whom.
- **Verification:** the commands run and their results.

<!-- The literal-prose rules adapt pstack-claude's unslop skill, rules 26, 32 and 33
(github.com/michael-denyer/pstack-claude, MIT, Copyright (c) 2026 Lauren Tan and Michael Denyer,
text in LICENSE-pstack-claude). -->
