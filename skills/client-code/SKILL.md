---
name: client-code
description: Use when adding analytics, a tracking pixel, session replay or any third-party tracker, when adding a delete, remove or destroy action to a UI, or when building or changing client components, forms and interaction handlers, however small the change. Applies to React, Next.js, Vue, Svelte and similar.
---

# Client code

A tracker that loads on page view and a Delete button that deletes on one click both pass every test, and nothing in the diff shows the missing guard. So the guard is built by default.

## Core rule: build the safe form by default and say so in your reply

Never offer it as an option, and never leave it as a risk for the user to decide on.

**A tracker** (analytics, a pixel, session replay, any third-party tracker):
- Nothing loads and no cookie is set until the visitor accepts. Consent Mode alone isn't this: its tag has already loaded.
- The choice is stored, so a return visit doesn't ask again.
- No choice and a reject both leave it off.
- Accept and Reject are equally easy: two buttons, same size, same step.
- Session replay also masks every input (LEG-04).

The one exception: the repo says it has no EU or UK users, in its notes or in `.claude/practices/client-code.md`. A repo that says nothing gets the gate. The reply says the gate was built and how to drop it if the audience is elsewhere.

**A destructive action** (delete, remove, destroy): a confirm naming what goes, or an undo window. This holds when the request says only "a Delete button that calls X".

Example reply line: "Analytics load only after a visitor clicks Accept, and the choice is stored. Nothing here says where your users are, so I built the gate; if none are in the EU or UK, remove `ConsentBanner` and render the script directly. Delete asks 'Delete Northwind Studio?' before it calls `deleteClient`."

If `.claude/practices/client-code.md` exists in the repo, read it first. Its repo rules (where its users are, its dialog component) win over the defaults here.

## Gate rule

- **Gate rule LEG-01 (covers LEG-04): a tracker loads only after a stored accept.**
- **Gate rule UX-63: a destructive action never runs on one click.**

The engine denies each at the edit, once per file, tells you at the commit, and denies the push.

## Not enforced: do these too

No hook checks these lines. They apply all the same.

- **Gate `:hover` in `@media (hover: hover)` (not enforced).** On touch it latches after a tap until the next tap elsewhere.
- **UX-51: `font-size: 16px` on every text input (not enforced).** Below that, iOS zooms the page on focus.
- **UX-51: tap targets of at least 44px (not enforced).** Small padding on a 13px button is not tappable.
- **An off-canvas drawer traps focus (not enforced).** Escape and a backdrop click close it, the body stops scrolling, and focus returns to the opener.
- **UX-03: filtering never leaves a blank void (not enforced).** Show an inline empty state, and exempt always-on sections from hide-when-empty logic.
- **UX-44: never encode meaning by colour alone (not enforced).** Pair it with a glyph or a word.
- **Keyboard parity (not enforced).** What hover reveals, focus reveals too: `tabindex="0"` on a non-interactive card, with `:focus-within`.

## When the hook stops a tracker or a delete

`[practices:L2:client-code:LEG-01:<path>]` stopped an edit that adds a tracker to a file with no `consent` or `accept` in it. Build the gate and say so. `[practices:L2:client-code:UX-63:<path>]` stopped an edit that adds a delete call to a component with no confirm or undo in it. Add one and say so. When the flow already has the guard (in another file, or in words the pattern misses), when the repo says it has no EU or UK users (LEG-01), or when the call deletes nothing a user would miss (UX-63), resend, or add `practices-allow: <id> <reason>` to the file.
