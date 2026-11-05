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
- **Adds:** `npm`, `pnpm`, `yarn` and `bun` `add`, `install`, `i` and npm's other spellings; `pip`, `pip3`, `python3 -m pip` and `uv pip` `install`; `uv`, `poetry`, `cargo` and `bundle` `add`; `gem install`; `composer require`. `go get` runs no code at install, so it isn't read.
- **Restores, never denied:** a bare install, `npm ci`, `pip install -r file`, `uv sync`, `poetry install`, `bundle install`, a local path, `pip install -e .`.
- **Scripts off, never denied:** `--ignore-scripts` in the same simple command for the npm family, `--only-binary :all:` for pip and uv.
- **Inspected, never denied (npm family only):** `npm view <pkg>` naming `scripts` or with `--json` and no named fields, `npm pack <pkg>`, or `tar`, `curl` or `wget` naming its tarball, in an earlier Bash call whose result isn't an error. A step of the same call doesn't count: `npm view x scripts && npm i x` runs the script before anyone reads the output. Named fields print only those, so `npm view <pkg> main --json` doesn't count.
- **Other managers:** no way to inspect was measured for them, so the deny-once alone applies.
- **The deny:** names only the package, when it matches a strict name pattern, and the check. The resend passes, and the next new package is denied again.
- **What passes, logged as `install-skipped`:** a word no pattern fits (an expansion, a URL, a git shorthand) and an install inside a launcher (`xargs`, `find -exec`, `sh -c` with an expansion).

Accepted limits:
- A resend passes unread. The rule costs one round trip and asks for an honest reply; it doesn't block.
- `cargo add` runs no code itself; `build.rs` runs at the next build. It is in the rule because the next build runs it unread.
- bun and current pnpm skip a dependency's lifecycle scripts by default, per their documentation. The rule denies once for them anyway: a repo's config can turn the scripts back on, and the engine doesn't read it.

## Measured and unmeasured

Measured with no skill and no hook (5 runs per model): an install script run unread, which fails on Haiku and Sonnet. Also measured, and under the bar on every model that ran them: a dependency for a few lines, a rival to an installed package, a lookalike one letter off a famous package, and a pinned version with a high advisory (Opus didn't run the advisory case).

**Unmeasured:**
- Whether the skill and the deny improve the install-script result: this file ships before that run.
- Every manager but npm. The rule's forms for the others come from their documentation.
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
