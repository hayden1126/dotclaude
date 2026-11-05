# dependencies: spec

The public spec for the `dependencies` skill: what it covers, the rule it enforces, how, and the public sources behind it.

## Scope

The skill covers adding, upgrading or replacing a package with a package manager, and the choice of whether a task needs a new dependency. It owns one enforced rule, SEC-64. The commit-time audit rule, SEC-60, stays in the engine and is cited here.

Files:
- `SKILL.md`: the core rule, the gate rule, then the lines nothing enforces.
- `references/lifecycle.md`: recipes a production repo can adopt: a dependency list, admission questions, an audit in PR checks, and update bots.
- `events.toml`: the gate line for the post-compaction digest. It has no events or rules, since an install is a Bash call and the engine's SEC-64 is the trigger.

## The rule: SEC-64

Read a package's install scripts before its first install, or install with scripts off.

Why this one: `npm install x` runs x's lifecycle scripts as part of the install, so a check at commit reads what already ran. In a no-skill eval, Haiku and Sonnet let an install script run unread in 5 of 5 runs each, and Opus inspected first in 5 of 5. Some replies said the script was read first when the install had already run it, so the skill asks the reply to say which.

## Enforcement

| level | what | when |
|---|---|---|
| L0 | The description, which names the install commands | the model's choice |
| Engine | SEC-64 in `hooks/practices_check.py`: denied once per manager and package | PreToolUse(Bash), before the install runs |
| L4 | The gate line after a compaction, when the skill was loaded | SessionStart(compact) |

What the engine reads:
- **Adds:** `npm`, `pnpm`, `yarn` and `bun` `add`, `install`, `i` and npm's other spellings; `yarn workspace <name> add`; `pip`, `pip3`, `pip3.12`, `python3 -m pip`, `python3.12 -m pip` and `uv pip` `install`; `uv`, `poetry`, `cargo` and `bundle` `add`; `gem install`; `composer require`. `go get` runs no code at install, so it isn't read.
- **Restores, never denied:** a bare install, `npm ci`, `pip install -r file`, `uv sync`, `poetry install`, `bundle install`, a local path, `pip install -e .`.
- **Scripts off, never denied:** in the same simple command, `--ignore-scripts` for npm, pnpm, bun and Yarn 1 (`--mode skip-build` for later Yarn), `--only-binary :all:` for pip and uv pip, `--no-build` for uv (`uv add` has no `--only-binary`).
- **Inspected, never denied (npm family only):** `npm view` or `pnpm view` (with `info`, `show` or `v`), `yarn info` or `bun info`, naming `scripts` or with `--json` and no named fields, or `tar` extracting or printing its tarball, in an earlier Bash call whose result isn't an error. `npm pack`, `curl`, `wget`, `tar -t` and `tar -c` show no script and don't count. Neither does a step of the same call or a call in the same assistant message: the model reads that output only after the install has run the script. Neither does output sent away (stdout redirected, `run_in_background`), or a look naming a version spec other than the install's: `npm view x@1.0.0 scripts` then `npm i x` is denied. Named fields print only those, so `npm view <pkg> main --json` doesn't count.
- **Other managers:** no way to inspect was measured for them, so the deny-once alone applies.
- **The deny:** names only the package and, when each matches a strict pattern, its version spec (`npm view x@1.0.0 scripts`), and the check. A word that could be an option's value is never named or stored. The resend passes, and the next new package is denied again.

Notes:
- The rule reads the common spellings and is a prompt to check, not a boundary. A resend passes unread: it costs one round trip and asks for an honest reply.
- `npm view x scripts` shows only x's own scripts. A dependency's install scripts run on `npm i x` too, and only `--ignore-scripts` covers them. A reply must not say "no scripts" as if that were the whole tree.
- `cargo add` runs no code itself; `build.rs` runs at the next build. It is in the rule because the next build runs it unread.
- bun and current pnpm skip a dependency's lifecycle scripts by default, per their documentation. The rule denies once for them anyway: a repo's config can turn the scripts back on, and the engine doesn't read it.

## Measured and unmeasured

Measured with no skill and no hook (5 runs per model): an install script run unread, which fails on Haiku and Sonnet. Also measured, and under the bar on every model that ran them: a dependency for a few lines, a rival to an installed package, a lookalike one letter off a famous package, and a pinned version with a high advisory (Opus didn't run the advisory case).

**Unmeasured:**
- Whether the skill and the deny improve the install-script result: this file ships before that run.
- Every manager but npm. The rule's forms for the others come from their documentation. The `uv`, `pnpm` and `bun` options were read from their `--help`; `yarn` wasn't installed where this was written.
- A plausible made-up name, as opposed to the easy lookalike that was measured.
- The licence line, and the recipes in `references/lifecycle.md`.

The four lines marked "not enforced" in `SKILL.md` have no hook, and only the failures above were measured for them.

## Sources

- [OWASP A03:2025]: OWASP Top 10:2025, A03 Software Supply Chain Failures, https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures
- [OWASP A06:2021]: OWASP Top 10:2021, A06 Vulnerable and Outdated Components, https://top10.owasp.org/2021/A06_2021-Vulnerable_and_Outdated_Components
- [npm scripts]: npm Docs, scripts (life cycle operations and the order they run in), https://docs.npmjs.com/cli/using-npm/scripts
- [npm install]: npm Docs, npm-install (`--ignore-scripts`), https://docs.npmjs.com/cli/commands/npm-install
- [npm view]: npm Docs, npm-view (named fields), https://docs.npmjs.com/cli/commands/npm-view
- [pip install]: pip documentation, pip install (`--only-binary`), https://pip.pypa.io/en/stable/cli/pip_install/
- [PEP 503]: Simple Repository API (name normalization), https://peps.python.org/pep-0503/
