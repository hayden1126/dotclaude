---
name: dependencies
description: Use when adding, upgrading or replacing a package, or about to run npm install, pnpm add, yarn add, bun add, pip install, uv add, poetry add, cargo add, bundle add, gem install or composer require, however small the package. Also use when choosing whether a task needs a new dependency at all.
---

# Dependencies

`npm install x` runs x's install script before you see a line of it. A check after the install reads what already ran, so the check comes first.

## Core rule: check before you install, then say so

Do the checks below before the install, by default, and say in your reply what you found. Never offer a check as an option, and never stop to ask permission for it.

Example reply line: "`npm view <pkg> scripts` shows a postinstall that runs `node build.js`, which compiles a native binding. I read `build.js` before installing: it touches no network and no files outside the package."

If `.claude/practices/dependencies.md` exists in the repo, read it first. Its repo rules (allowed licences, the dependency list, the audit command) win over the defaults here.

## Gate rule

- **Gate rule SEC-64: read the install scripts before a first install, or install with scripts off.** Before a first install or an upgrade of a package, run `npm view <pkg> scripts` (or the manager's equivalent: `pnpm view`, `yarn info`, `bun info`), with `@<version>` when you pin one, or install with scripts off (`--ignore-scripts` for npm, pnpm, bun and Yarn 1; `--only-binary :all:` for pip and uv pip; `--no-build` for uv). When a script calls a file, read that file too: `npm pack <pkg>`, then `tar -xOzf <tarball> package/<file>`. `npm view` shows only that package's own scripts. A dependency's install scripts can run too, and only `--ignore-scripts` covers them, so never reply "no scripts" as if that were the whole tree: say the package itself has none and its dependencies weren't checked. In the reply, state what the script does and whether you read it before or after it ran. Don't write "I read it first" when the install already ran it. The engine denies a first install once per package, and the resend passes. For the npm family, reading the scripts first skips the deny.

## Not enforced: do these too

No hook checks these lines. They apply all the same.

- **Reuse first (not enforced).** Use the codebase, then the stdlib or platform, then an installed dependency, then new code. Never add a dependency for a few lines.
- **Check the package (not enforced).** Confirm it exists and is the one intended: exact name, age, maintainers and repository. A name one letter off a famous package, or a week-old package with no repository, is a reason to stop and tell the user.
- **Check the licence (not enforced).** Confirm it is compatible with this repo's licence and how the code ships.
- **Lock and audit (not enforced here; SEC-60 is enforced at commit).** Keep a lockfile and run the ecosystem's audit (`npm audit`, `pip-audit`, `cargo audit`). Fix or flag what it reports, including a version the user pinned: name the advisory and the fixed version, then let the user decide about the pin.

## Production repos

When the repo has a deploy workflow and no dependency list, name [references/lifecycle.md](references/lifecycle.md) once in your reply. Don't build it unasked.

## When the hook stops an install

`[practices:SEC-64]` names each package and its check. Run the check and read the output, then install. If you resend without checking, the call passes, and your reply says what the script does and that you read it after it ran.
