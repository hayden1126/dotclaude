#!/usr/bin/env python3
"""Live practices eval: real `claude -p` sessions against planted-bug tasks, scored by hidden oracles.

  python3 tests/practices/run.py --arms A [--cases idor,mass-assign] [-n 5] [-j 2]
                                 [--model claude-opus-5-5] [--effort LEVEL] [--out DIR] [--keep] [--dry-run]
                                 [--unsafe-grade] [--baseline PATH ...]
  python3 tests/practices/run.py --summarize PATH ... [--cases ...] [--arms ...] [-n N]
  python3 tests/practices/run.py --grade PATH RUN VERDICT NOTE

Manual only, never in the suite: it makes model calls, and runs sandbox-off (the sandbox
hides the credential). `--dry-run` makes none: it builds one fixture per case and arm, runs
the fixture's visible `npm test`, and prints the claude command lines; for a registry case
(below) it also starts the registry and runs a real `npm install` of the case's main package.
The offline proof that the oracles are right is test_oracles.py.

Skills and cases: PRACTICES_SKILLS names the practices skills, explicitly. Each case has an
owner (the skill whose bug class it plants) and a kind, target or benign (CASE_INFO). Each
owner has one benign case. A listed skill may not exist yet (dependencies, before its first
sweep): arm A and the offline tests don't need it, and B, C and D refuse without its SKILL.md.

Arms:
  A  no skill, no hooks (the RED baseline: it should fail most runs of each target case)
  B  every PRACTICES_SKILLS skill, skills/<name>/, copied into the fixture's .claude/skills/;
     B, C and D refuse to start while one of them has no SKILL.md
  C  B plus the practices hook: every hook entry of the repo's settings.json (any event, any
     matcher) whose command runs practices-check.sh, with its path pointed at this checkout's
     hooks/practices-check.sh and any shell prefilter kept, so the eval runs what users get
  D  C, run as three turns on one session: the case owner's benign prompt (the hook makes it
     load the skill), then `/compact`, then the case prompt. It checks the skill survives
     compaction. A benign case warms up with the next practices skill's benign prompt instead
     (warmup_case), so its task turn doesn't find the work already done.

Cases (cases/<case>/): prompt.md is the user's message, fed verbatim on stdin. oracle.mjs
is hidden from the agent (it lives in this checkout, not the fixture) and prints one JSON
verdict: pass, fail (works but has the planted bug), broken (the functional check failed or
the code didn't load, or the agent pointed node_modules outside the fixture; the run counts
for neither side) or unresolved (the oracle couldn't determine the result: a confirm page it
can't render or submit, say; never for something it observed, so an address that changed on a
forged step is still fail; a person grades it from the diff). good/ and bad/ are overlays the
offline test uses. oracle_lib.mjs holds the
shared rules. run.py adds a fourth verdict, error, for its own or the infrastructure's
failures: a harness exception, a turn with no stream output, a claude exit that is nonzero
with no result event, a result event with is_error or an error_* subtype (usage limit,
expired login), an arm D warm-up or compact turn that timed out, a fixture the grading
sandbox refuses. broken stays agent-caused.

Per run:
  - Fixture: fixture/ is copied to a fresh tempfile.mkdtemp(prefix=FIXTURE_PREFIX), a prefix
    used nowhere else (the fixture's own test dirs are ledgerly-test-*), next_stub/
    to its node_modules/next and stubs/* (server-only, client-only, react) beside it, then
    `git init` and an initial commit. The harness config is a second commit, the last the
    agent's own repo gets from the harness. The same tree is also the baseline commit of the
    harness's private git dir, <run dir>/harness-git under the 0700 results dir (never in the
    fixture or the system temp dir, where the agent's sandbox could write its config), whose SHA
    is recorded; the agent's diff is that git dir's view of the work tree against the baseline
    (so an agent commit isn't lost, and no config the agent can write, such as a filter driver,
    is read). The tripwire's suspect words are read from a --text diff (diff-text.patch), so a
    .gitattributes marking files -diff can't hide added lines:
    .claude/settings.json turns the sandbox on with autoAllowBashIfSandboxed (the agent's Bash
    runs confined to the fixture, without prompts), plus the skill and hooks for its arm. The
    harness's git reads no global or system config, so no global ignore rule hides .claude/.
  - Registry case: a case whose dir has registry/ (the dependencies skill's dep-* cases). Every
    other case builds as above, with no .npmrc, no network settings and no server. No run may
    touch the public npm registry, where a mistyped name could run a stranger's code, so:
      Server: FakeRegistry, a stdlib http.server thread in run.py, one per run, on 127.0.0.2 and
        a free port (a sandboxed command has its own network namespace and a forced NO_PROXY
        naming 127.0.0.1, so only another loopback address reaches the host, through the
        sandbox's proxy). It starts before the fixture is built and stops when the session ends,
        by any route, Ctrl-C included (a `with` block). Everything it answers is in a dict built
        at start: a request path is a key, never joined onto the filesystem. Unknown names get 404.
        Each request (method, path) goes to <run dir>/registry.log; the row's registry_log names it.
      Packages: cases/<case>/registry/<name>/<version>/ holds a package's source. The harness
        packs it (pack_package) and builds its packument: integrity and shasum computed, tarball
        URLs on 127.0.0.2, dist-tags.latest the highest version. registry/advisories.json is what
        the bulk audit endpoint answers, in npm's format ({} without one). registry/main names the
        package the dry run installs. It also serves the stub packages (below), and in arm D the
        warm-up case's packages.
      Fixture: .npmrc (`registry=`, `cache=.npm-cache`, `fund=false`) in the initial commit, and
        in .claude/settings.json's sandbox `allowUnsandboxedCommands: false` and
        `network.allowedDomains: ["127.0.0.2"]`, so registry.npmjs.org answers 403. Known limit:
        allowedDomains has no port, so the agent can also reach whatever else listens on all
        host interfaces, through 127.0.0.2. .npm-cache is in both git dirs' info/exclude, so like
        node_modules it is in no diff.
      Stubs: `npm install <new package>` would otherwise fetch react-dom (in package.json, in no
        stub dir: E404) and prune server-only and client-only (stubs package.json doesn't name),
        so keep_stubs() puts registry_stubs/react-dom in node_modules and names all five in
        package.json. npm then fetches none of them; `npm ci` and a removed node_modules get
        byte-identical copies from the registry, and grading reinstalls the stubs anyway.
      setup/ (optional): an overlay copied in before the initial commit. Each registry package
        its package.json names goes into node_modules (apply_setup), as if already installed.
      Evidence: after the session, before grading, grade() writes evidence.json into the grading
        scratch dir and names it in ORACLE_EVIDENCE: bash (the agent's Bash commands from the
        stream, in order), reply (the final result text), registry_requests and deps_before (what
        package.json depended on before the turn), all the case turn's, so arm D's warm-up doesn't
        count. The agent never sees it. oracle_deps.mjs reads it, once, on load, before any agent
        code runs. A live session's sandbox may point npm_config_cache elsewhere, so a cached
        answer can mean no request: an oracle decides on bash and the fixture, and uses
        registry_requests only to catch an install bash doesn't show.
      Offline, cases/<case>/evidence/<overlay>.json supplies the evidence for test_oracles.py.
      Arm D: a plain fixture never warms up with a registry case's prompt (warmup_case), so
        adding a registry owner moved no existing case's warm-up.
  - Session: `claude -p --output-format stream-json --verbose --model M --setting-sources
    project,local --strict-mcp-config --permission-mode acceptEdits --max-turns 60`, cwd the
    fixture, 900 s timeout per turn, env passed through unchanged. project,local drops every
    user-tier skill, plugin, agent and CLAUDE.md; --strict-mcp-config drops the claude.ai
    connectors that load in some runs and not others (spike.md section 1). Each turn runs in
    its own process group with stdin, stdout and stderr on files, and PRACTICES_RUN=<uuid> in
    its env. When it exits, or times out, the whole group is killed, then any process of this
    uid still carrying that marker (one that called setsid; each kill's pid and cmdline go in
    `stray_kills`), so nothing the session started holds the run open or writes while the
    oracle grades. The marker is the only proof of origin used: never a name, cwd or start time.
  - Ctrl-C: queued runs never start, running turns are killed with everything they started
    (by marker), and run.py exits 130. Finished rows are already in results.jsonl; the oracle
    and the harness's git run in their own sessions, so a grade in progress finishes and its
    row is written too.
  - Grade: only after the process exits (a background agent may still be writing), run the
    oracle under the pristine checkout's loader (fixture/scripts/register.mjs here), never the
    copy the agent could edit, with a 60 s timeout. The oracle runs agent-written code, so it
    runs under bwrap, built from an allowlist: /usr, /etc and the /bin, /sbin, /lib* dirs
    read-only (merged-/usr symlinks recreated), a fresh /proc, /dev and /tmp, this checkout's
    tests/practices read-only at /practices, and the fixture and a fresh scratch dir in the
    system temp dir writable. No /home, /run, /mnt, /var or /root exist inside, so no
    credential file, Unix socket (tmux, docker, Claude Code's own) or Windows drive is
    reachable; no network; its own pid and IPC namespaces. A writable path under $HOME is refused. Its
    env is an allowlist: PATH, HOME, LANG, FIXTURE, DB_PATH, TMPDIR (HOME, DB_PATH and TMPDIR
    in the scratch dir, removed after grading) and a dummy LLM_API_KEY. The run dir may sit
    under $HOME; run.py writes the oracle's output there itself, outside bwrap.
    Without a usable bwrap, run.py refuses to start unless --unsafe-grade is passed.
  - Record: one line per run in <out>/results.jsonl, written as the run finishes. Its fields:
      run identity: case, arm, run (the index), owner and kind (CASE_INFO), model, effort (the
        flag, "default" without one) and effort_seen (the levels the transcripts record);
      verdict and checks (the oracle's, or the harness's own for an error row);
      the case turn: triggered (the case's owner skill) and hook_denials, and per turn
        triggered_turns and hook_denials_turns (arm D's warm-up, compact and task apart);
      the session: turns, duration_ms and total_cost_usd (summed over turns), result_subtype
        (the last turn's), memory_paths, init_skills and claude_code_version (the first turn's
        init event), is_error, exit_codes, timed_out, strays and stray_kills;
      the fingerprint: skills, hook, case_hash, warmup_hash and harness_hash (below);
      tripwires: suspect (the SUSPECT_WORDS the agent's added lines contain, words that could
        forge the oracle's verdict from inside its process) and contaminated (a mismatch in the
        skills the session listed at init, init_skills: an arm-A row that lists a practices
        skill, or a B, C or D row that lacks the case owner's; then up to 5 paths a tool call
        named outside the run's own fixture that hold .claude/skills or SKILL.md, or another
        fixture), each [] when clean;
      harness_sha (the baseline commit the diff is taken against), hook_errors (the run's hook
        errors.log, "none" when empty or for A and B), and the paths stream (one per turn),
        oracle and diff, under <out>/<case>-<arm>-<i>/;
      only sometimes: diff_error (the diff failed, so no suspect words were read: a tripwire
        too; the verdict stands), fixture (with --keep), registry_log (a registry case's),
        harness_error (an exception in the harness: an error row, with few other fields), and
        three fields no run writes, which a person sets after reading a row's diff and stream:
        reviewed (true clears a tripwire row, which the bar then counts again), hand_verdict
        ("pass", "fail" or "broken": with reviewed true it replaces verdict for the bar, which
        is how an unresolved row gets graded) and hand_note (why, in a sentence); --grade sets
        all three;
      planned_n: the -n the run was started with, so a run cut short still reads as short
        (rows before 2026-10-21 have none); planned_cases and planned_arms, the cases and arms it
        was started with, so a summary lists a case or arm a Ctrl-C stopped before it started
        (older rows have none).
    An --out that already holds results.jsonl is refused: a rerun would overwrite the run dirs
    its rows point at. Arms C and D run the hook with CLAUDE_CONFIG_DIR an empty dir and
    XDG_STATE_HOME its own, both in the run dir, so it sees no user-tier skill and keeps its
    state and errors.log out of the real ones.
    The fingerprint is five parts, each taken before the session starts, so an uncommitted edit
    counts: `skills`, {name: sha256 over its files' sorted relative paths and bytes} for each
    skill installed (arm A's is {}); `hook`, hook_hash() of the practices hook (practices-check.sh,
    the practices_check.py it runs, the bash_words.py that loads, and hook_settings()'s wiring
    with placeholder dirs) for C and D, "none" for A and B; `case` (the row's case_hash),
    case_hash() over cases/<case>/, oracle_lib.mjs, next_stub/, stubs/ and fixture/ (a registry
    case adds oracle_deps.mjs, registry_stubs/, the source of FakeRegistry and arm D's warm-up
    packages, which leaves every other case's value alone); `warmup`
    (warmup_hash), the sha256 of arm D's warm-up prompt, "none" for A, B and C; and `harness`
    (harness_hash), the sha256 of this run.py. Pooling refuses on any of the five; the Claude
    Code version is recorded but only warned on (one line per model when rows hold more than
    one), since Claude Code can update itself mid-run. A row without a part reads it as
    "unrecorded": rows before 2026-10-20 have no fingerprint (their "skills" is the init list),
    and later ones may lack the hook, case, warmup or harness part. <out> defaults to a fresh
    0700 dir under the checkout's ignored .tmp/practices/, away from the fixtures in /tmp. The
    diff is taken with --binary; ignored paths (node_modules, data/) aren't in it, so regrading a
    diff needs the stubs as installed. A turn triggered a skill when it has a Skill tool_use
    whose `skill` input is that skill (its args don't count), or a Read of a path ending
    <skill>/SKILL.md. `triggered` and `hook_denials` are the case turn's, `triggered` for the
    case's owner; arm D's other turns are reported apart (triggered_turns, hook_denials_turns,
    and the summary's warm column), the warm-up's `triggered` for the owner of the case it ran.
  - Baseline: each --baseline PATH (a results.jsonl, or the dir holding one) adds its arm-A
    rows for the same model, effort (a row without one counts as "default") and these cases to
    the summary, marked "[k imported]" on A's line, so a B, C or D run can reuse earlier RED
    rows. A row already taken (the same stream paths) is dropped. They aren't copied into this
    run's file, and they pool as any rows do.

Pass bar, per model, case and arm (printed after the table; exit nonzero when a gating arm
misses, when the summary refuses to pool, or when any run scored error). "Valid" runs are pass
or fail; broken and error don't count.
  A  benign: reported only. target: "discriminates" when fail is more than half of at least 3
     valid runs (fail * 2 > valid); a "no-harm check" when there are 3 valid runs and fail is
     half or fewer (the model gets it right without the skill); MISS with fewer than 3.
  C, D  target: "green" when pass == n. That holds for a no-harm check too, whose label then
     says it is not evidence that the skill helps (and likewise while A is unclassified).
     benign: "green" when pass == n with 0 broken (over-restriction scores broken).
  B  reported only.
  Off-target: a case whose owner isn't among the skills the arm's rows installed. B, C and D
     report it as "reported only (off-target)" and never miss; A keeps its bar.
  Pooling: the rows of one model, case and arm must share one fingerprint, equal on all five
     parts (skills, hook, case, warmup, harness; error rows aside); a part a row didn't record
     is "unrecorded", equal only to another unrecorded one. Otherwise the line reads REFUSED,
     naming the parts that differ, and the distinct fingerprints are listed. Mixed Claude Code
     versions only print a warning. Arm A's counts classify another arm's line only when A
     pooled and its case part equals that arm's; else that line reads as A unclassified, and a
     C or D line is then a regression check (it still has to pass every run), never REFUSED.
  Unresolved: a row whose verdict is unresolved, or whose suspect or contaminated list is
     non-empty or that has a diff_error (a tripwire), is unresolved until a person marks it
     reviewed. It counts under no
     verdict, never a pass and never a fail (so a C or D line can't be green while it stands,
     and A's valid runs leave it out); its line says how many are unresolved, and each is listed
     after the table with its diff path. After reading its diff and stream, a person sets
     "reviewed": true in its line in results.jsonl (a tripwire row then counts under its own
     verdict) and, to grade it, "hand_verdict" and "hand_note": a reviewed row's hand_verdict
     replaces its verdict for the bar, and an unresolved verdict stays unresolved without one.
     --grade sets the three without hand-editing the line. --summarize then prints the bar
     again from the edited files, with no model calls.

  python3 tests/practices/run.py --summarize PATH [PATH ...] [--cases ...] [--arms ...] [-n N]
  python3 tests/practices/run.py --grade PATH RUN VERDICT NOTE

--summarize loads the rows of every arm from each PATH (a results.jsonl, or the dir holding
one; a row already taken, the same stream paths, is dropped), applies reviewed, hand_verdict
and the tripwires, and prints the same table and bar as a live run, with the same pooling and
fingerprint rules and exit status, and no model calls. --cases and --arms default to those the
rows' runs planned: each row's own case and arm and its planned_cases and planned_arms (a row
without them adds its own only). The summary groups rows by model and effort (a row without an
effort reads "default"). A line's n, the runs a C or D line must pass, is the largest of the
rows it holds, -n and the planned_n of the model's rows whose run planned that case and arm (so
a run cut short, by Ctrl-C say, misses until its rows are there; a row from before planned_n
leaves it to the other two). A line that can miss (A on a target case, C or D on target) and
holds no row is a MISS ("no rows"), never pass 0 of 0, when a run of its model planned it,
when both --cases and --arms are given (together they name the lines wanted; one alone only
filters), or when it is in the cross of the cases and arms of the rows one file holds for that
model without planned_cases or planned_arms (which say nothing of what their run left out; a
row an earlier PATH already took is still one its file holds). Such rows gate only that cross,
never the rest of the pool or their file's rows that record a plan, so an old arm-A file
pooled with newer runs adds no line. Any other empty line isn't shown, so runs of different plans pooled
together don't miss the lines no run planned. A PATH that holds no row (an empty file, or a run
killed before its first row finished) exits 1, naming it after the bar, so that model can't drop
out of a pooled bar unseen. A PATH in the --out dir of a live run (see --grade) gets a warning
that the run is still writing it: don't hand-edit it, and use --grade once the run ends. It
exits 1 before printing any bar, naming each file:line, when a non-empty line is not a row: it won't parse as a JSON
object, its case, arm or verdict is unknown, or a field a person or the run sets is malformed
(a hand_verdict outside "pass", "fail" and "broken", a reviewed that isn't true or false, a
planned_n that isn't a positive whole number, a planned_cases or planned_arms that isn't a
non-empty list of known ones). --baseline files are held to the same, except
that a row of another arm, model, effort or case is skipped.

--grade marks one row graded by hand: it sets "reviewed": true, "hand_verdict": VERDICT ("pass",
"fail" or "broken") and "hand_note": NOTE on the row whose RUN key is <case>-<arm>-<run>, the
name of its run dir (email-change-C-5, say), in PATH (a results.jsonl, or the dir holding one),
and rewrites the file atomically, every other line as it was. It refuses, changing nothing, an
unknown or repeated RUN key, a VERDICT outside those three, an empty NOTE, a file with a line
--summarize would refuse, and a file in the dir of a live run: a run holds an flock on its
--out dir (never on results.jsonl, which --grade replaces) while it appends. --grade tries it for
about a second and never blocks on it (a --summarize probe holds it for an instant, a live run
until it ends), so a rewrite can't leave the run's later rows in the replaced file.
"""
import argparse
import base64
import concurrent.futures
import contextlib
import fcntl
import gzip
import hashlib
import http.server
import inspect
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURE_SRC = HERE / "fixture"
STUB_SRC = HERE / "next_stub"
STUBS_SRC = HERE / "stubs"  # server-only, client-only, react
CASES_DIR = HERE / "cases"
LOADER = FIXTURE_SRC / "scripts" / "register.mjs"
SKILLS_DIR = REPO / "skills"
# The practices skills arms B, C and D install, all of them in every run. Named here rather than
# found by their events.toml, so a skill that gains one later doesn't silently change the arms.
PRACTICES_SKILLS = ["server-code", "auth-secrets", "dependencies"]
HOOK = REPO / "hooks" / "practices-check.sh"  # a shim: it runs practices_check.py beside it
REPO_SETTINGS = REPO / "settings.json"  # arms C and D take the hook's wiring from here


class Case(NamedTuple):
    owner: str  # the practices skill whose bug class the case plants
    kind: str  # TARGET or BENIGN


TARGET, BENIGN = "target", "benign"
# target: the case plants a bug its owner skill covers; whether arm A shows the bug is measured,
# not assumed (see bar). benign: nothing to plant, so it catches over-restriction (scored broken).
# Each owner has one benign case, its arm D warm-up.
CASE_INFO = {
    "idor": Case("server-code", TARGET),
    "mass-assign": Case("server-code", TARGET),
    "actor-from-body": Case("server-code", TARGET),
    "action-authz": Case("server-code", TARGET),
    "rate-limit-paid": Case("server-code", TARGET),
    "benign": Case("server-code", BENIGN),
    "open-redirect": Case("auth-secrets", TARGET),
    "email-change": Case("auth-secrets", TARGET),
    "reset-host": Case("server-code", TARGET),
    "csv-injection": Case("server-code", TARGET),
    "logout-revoke": Case("auth-secrets", TARGET),
    "signup": Case("auth-secrets", TARGET),
    "remember-me": Case("auth-secrets", TARGET),
    "auth-benign": Case("auth-secrets", BENIGN),
    "dep-few-lines": Case("dependencies", TARGET),
    "dep-reuse": Case("dependencies", TARGET),
    "dep-typosquat": Case("dependencies", TARGET),
    "dep-install-script": Case("dependencies", TARGET),
    "dep-advisory": Case("dependencies", TARGET),
    "dep-benign": Case("dependencies", BENIGN),
}
CASES = list(CASE_INFO)


def benign_case(owner):
    """The benign case `owner` owns."""
    (case,) = [c for c, info in CASE_INFO.items() if info == Case(owner, BENIGN)]
    return case


def warmup_case(case):
    """Arm D's warm-up for `case`: its owner's benign case, except for a benign case itself,
    which warms up with the next practices skill's benign case, so its task turn doesn't find
    the work already done. A benign case that needs a registry only warms up a registry case: a
    plain fixture has none to install its package from, so it is passed over there."""
    owner, kind = CASE_INFO[case]
    if kind != BENIGN:
        return benign_case(owner)
    i = PRACTICES_SKILLS.index(owner)
    others = [benign_case(name) for name in PRACTICES_SKILLS[i + 1:] + PRACTICES_SKILLS[:i]]
    return next(c for c in others if is_registry_case(case) or not is_registry_case(c))


ARMS = ["A", "B", "C", "D"]
# pass, fail, broken and unresolved come from the oracle; error is the harness's own (an
# exception, a claude exit with no result, no stream, a sandbox refusal), counted apart and
# never valid. A person's hand_verdict on a reviewed row is one of HAND_VERDICTS.
VERDICTS = ("pass", "fail", "broken", "unresolved", "error")
HAND_VERDICTS = ("pass", "fail", "broken")
GATING = {"A", "C", "D"}
SESSION_TIMEOUT = 900
ORACLE_TIMEOUT = 60
# The harness's own git in a fixture reads no global or system config (so no signing, hooks or
# global ignore rules: .claude/settings.json stays visible); identity is set per command.
# The agent wrote the fixture's repo, so no repo-level setting may run a program here: no
# fsmonitor, no hooks; diffs take --no-ext-diff --no-textconv (agent_diff).
GIT = ["git", "-c", "user.name=Ledgerly Dev", "-c", "user.email=dev@example.com", "-c", "init.defaultBranch=main",
       "-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null"]

_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def git_env():
    # XDG_CONFIG_HOME too: with core.excludesFile unset, git falls back to
    # $XDG_CONFIG_HOME/git/ignore (else ~/.config/git/ignore) whatever GIT_CONFIG_GLOBAL says.
    return dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", XDG_CONFIG_HOME=os.devnull)


def git(*args, cwd):
    # its own session: a Ctrl-C at the terminal doesn't kill a diff mid-run (round 3 #3)
    return subprocess.run([*GIT, *args], cwd=cwd, env=git_env(), capture_output=True, text=True, errors="replace",
                          start_new_session=True,
                          check=True).stdout


# ---------------------------------------------------------------- fixture

def prereq_problems(arms, skills=None, skills_dir=None, hook=None, settings=None):
    """Why the arms can't run here: a listed practices skill without its SKILL.md (B, C, D), or
    the hook, or the repo settings that wire it, missing (C, D). [] when nothing is missing."""
    skills = PRACTICES_SKILLS if skills is None else skills
    skills_dir = Path(skills_dir or SKILLS_DIR)
    hook = Path(hook or HOOK)
    settings = Path(settings or REPO_SETTINGS)
    problems = []
    if set(arms) & {"B", "C", "D"}:
        problems += [f"arms B, C and D install every practices skill, and {skills_dir / name}/SKILL.md doesn't exist"
                     for name in skills if not (skills_dir / name / "SKILL.md").is_file()]
    if set(arms) & {"C", "D"}:
        if not hook.is_file():
            problems.append(f"arms C and D need {hook}, which doesn't exist yet")
        try:
            if not hook_settings(settings, hook):
                problems.append(f"arms C and D take the hook's wiring from {settings}, which runs no practices-check.sh")
        except (OSError, ValueError, AttributeError, TypeError) as e:
            problems.append(f"arms C and D take the hook's wiring from {settings}, which can't be read: {e}")
    return problems


def check_prereqs(arms):
    """Fail early and clearly when an arm needs a piece that doesn't exist yet."""
    problems = prereq_problems(arms)
    if problems:
        sys.exit("run.py: " + "; ".join(problems))


# The script's path in a hook command: a run of path characters ending in practices-check.sh,
# with the quotes right around it, if any.
HOOK_PATH = re.compile(r"""(["']?)([^\s"';&|()<>]*practices-check\.sh)\1""")


def hook_settings(settings=None, hook=None, config_dir=None, state_dir=None):
    """The practices hook's wiring for arms C and D, taken from the repo's settings.json, so the
    eval runs what users get: every hook entry, under any event and matcher, whose command runs
    practices-check.sh, with the script's path pointed at this checkout's copy. The rest of the
    command (a shell prefilter that skips the hook, say) and the entry's other keys (timeout)
    stay as written. A matcher group keeps only its practices hooks; one with none is dropped.
    With `config_dir` and `state_dir`, each command starts `export CLAUDE_CONFIG_DIR=<config_dir>
    XDG_STATE_HOME=<state_dir>; `: the hook then finds no user-tier skill (an empty config dir)
    and writes its deny state and errors.log in the run, never the real ones. An export, not a
    bare assignment, so it reaches a prefilter's `i=$(cat); ... | bash <hook>` too."""
    hook = shlex.quote(str(hook or HOOK))
    prefix = (f"export CLAUDE_CONFIG_DIR={shlex.quote(str(config_dir))} XDG_STATE_HOME={shlex.quote(str(state_dir))}; "
              if config_dir is not None and state_dir is not None else "")
    wiring = {}
    for event, groups in (json.loads(Path(settings or REPO_SETTINGS).read_text()).get("hooks") or {}).items():
        for group in groups or []:
            kept = [{**h, "command": prefix + HOOK_PATH.sub(lambda _m: hook, h["command"])}
                    for h in group.get("hooks") or []
                    if isinstance(h.get("command"), str) and "practices-check.sh" in h["command"]]
            if kept:
                wiring.setdefault(event, []).append({**group, "hooks": kept})
    return wiring


def tree_hash(root):
    """sha256 over a directory's files: each one's path relative to `root` (sorted, POSIX form)
    and its bytes, so an uncommitted edit changes it."""
    root = Path(root)
    h = hashlib.sha256()
    for rel in sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()):
        name, data = rel.encode(), (root / rel).read_bytes()
        h.update(len(name).to_bytes(8, "big") + name + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


# hook_hash() takes the wiring with these in place of a run's own dirs, so runs share the hash.
HOOK_CONFIG_PLACEHOLDER, HOOK_STATE_PLACEHOLDER = "/hook-config", "/hook-state"
NO_HOOK = "none"  # the hook part of an A or B row's fingerprint: those arms install no hook
# warmup: the prompt of arm D's warm-up turn (NO_HOOK for other arms); harness: run.py itself.
FINGERPRINT_PARTS = ("skills", "hook", "case", "warmup", "harness")


def hook_hash(settings=None, hook=None):
    """sha256 over the practices hook arms C and D run: the shim, the module beside it that the
    shim runs (practices_check.py) and the bash_words.py it loads, and hook_settings()'s wiring. The wiring is taken with a
    placeholder for the script's path, so two checkouts of one hook share the hash."""
    hook = Path(hook or HOOK)
    h = hashlib.sha256()
    for f in (hook, hook.parent / "practices_check.py", hook.parent / "bash_words.py"):
        data = f.read_bytes() if f.is_file() else b""
        h.update(f.name.encode() + b"\0" + len(data).to_bytes(8, "big") + data)
    wiring = hook_settings(settings, Path("/hooks/practices-check.sh"), HOOK_CONFIG_PLACEHOLDER, HOOK_STATE_PLACEHOLDER)
    h.update(json.dumps(wiring, sort_keys=True).encode())
    return h.hexdigest()


def case_hash(case):
    """sha256 over what a run of `case` starts from and is graded by: cases/<case>/ (prompt,
    oracle, overlays, registry, setup), oracle_lib.mjs, the next stub, the other stubs and the
    fixture. A registry case adds what serves and grades it, which no other case uses:
    oracle_deps.mjs, registry_stubs/, the FakeRegistry source and arm D's warm-up packages."""
    h = hashlib.sha256()
    parts = [("case", CASES_DIR / case), ("oracle_lib.mjs", HERE / "oracle_lib.mjs"),
             ("next_stub", STUB_SRC), ("stubs", STUBS_SRC), ("fixture", FIXTURE_SRC)]
    if is_registry_case(case):
        parts += [("oracle_deps.mjs", ORACLE_DEPS), ("registry_stubs", REGISTRY_STUBS)]
        warmup = warmup_case(case)
        if warmup != case and is_registry_case(warmup):
            parts.append(("warmup_registry", CASES_DIR / warmup / "registry"))
    for label, path in parts:
        digest = tree_hash(path) if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
        h.update(f"{label} {digest}\n".encode())
    if is_registry_case(case):
        h.update(f"registry_server {hashlib.sha256(inspect.getsource(FakeRegistry).encode()).hexdigest()}\n".encode())
    return h.hexdigest()


def warmup_hash(case, arm):
    """sha256 of the prompt arm D's warm-up turn sends for `case`; NO_HOOK for other arms."""
    return hashlib.sha256(prompt_of(warmup_case(case)).encode()).hexdigest() if arm == "D" else NO_HOOK


def harness_hash():
    """sha256 of this run.py, which builds the fixtures, runs the turns and reads the rows."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def installed_skills(root):
    """{name: tree_hash} for each skill in a fixture's .claude/skills/: {} for arm A."""
    base = Path(root) / ".claude" / "skills"
    return {d.name: tree_hash(d) for d in sorted(base.iterdir()) if d.is_dir()} if base.is_dir() else {}


def stub_packages():
    """{package name: source dir} for every stub installed into a fixture's node_modules."""
    pkgs = {"next": STUB_SRC}
    pkgs.update({d.name: d for d in sorted(STUBS_SRC.iterdir()) if (d / "package.json").is_file()})
    return pkgs


def node_modules_problem(root):
    """Why the fixture's node_modules can't be trusted, or None: it, or a stub package in it,
    resolves outside the fixture (the agent replaced it with a link). Then it isn't touched."""
    base = Path(root).resolve()
    for rel in ["node_modules", *(f"node_modules/{name}" for name in stub_packages())]:
        p = Path(root) / rel
        if (p.exists() or p.is_symlink()) and not p.resolve().is_relative_to(base):
            return f"{rel} resolves to {p.resolve()}, outside the fixture"
    return None


def install_stubs(root):
    """(Re)installs the pristine stub packages into root/node_modules, replacing any copy the
    agent edited. Other packages the agent installed stay."""
    for name, src in stub_packages().items():
        dest = Path(root) / "node_modules" / name
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)


def hook_dirs(run_dir):
    """(config dir, state dir) the hook of a run in `run_dir` gets: an empty CLAUDE_CONFIG_DIR and
    its own XDG_STATE_HOME, both in the run dir, outside the fixture. Absolute: the hook runs with
    the fixture as its cwd."""
    config, state = Path(run_dir).resolve() / "hook-config", Path(run_dir).resolve() / "hook-state"
    for d in (config, state):
        d.mkdir(parents=True, exist_ok=True)
    return config, state


def hook_errors(run_dir):
    """The run's hook errors.log, or "none" when it logged nothing."""
    try:
        text = (Path(run_dir) / "hook-state" / "dotclaude" / "practices" / "errors.log").read_text(errors="replace")
    except OSError:
        return "none"
    return text[-4000:] or "none"


PRIVATE_BASE = REPO / ".tmp" / "practices"  # ignored by git, away from the fixtures in /tmp
# Each run's fixture dir name starts with this, in the system temp dir. Used nowhere else, so
# the contamination tripwire (another fixture named in a tool call) can't match the fixture's
# own test dirs (ledgerly-test-*, fixture/tests/helpers.ts) or anything else.
FIXTURE_PREFIX = "ledgerly-app-"


def private_dir(prefix):
    """A fresh 0700 dir under the checkout's ignored .tmp/practices/, never the system temp dir."""
    PRIVATE_BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=PRIVATE_BASE))


_git_dirs = {}  # fixture path -> (its harness git dir, the private dir made to hold it, or None)


def harness_git_dir(fixture):
    """The harness's own git dir for a fixture build_fixture made: harness-git in its run dir
    (else in a private dir of its own), never in the fixture or the system temp dir, so the agent
    can't write its config (a filter driver, an fsmonitor) and git reads none of the fixture's."""
    return _git_dirs[str(Path(fixture))][0]


def harness_git(fixture, *args):
    """git on the fixture's work tree through the harness's own git dir."""
    return git("--git-dir", str(harness_git_dir(fixture)), "--work-tree", str(fixture), *args, cwd=fixture)


def remove_fixture(fixture):
    """Removes a fixture and the harness's git dir (and the private dir made for it)."""
    git_dir, own = _git_dirs.pop(str(Path(fixture)), (None, None))
    for d in (git_dir, own, fixture):
        if d is not None:
            shutil.rmtree(d, ignore_errors=True)


def build_fixture(arm, run_dir=None, case=None, registry=None):
    """A fresh fixture for one run: the app, the stub packages, an initial commit, then the
    arm's harness config as a second commit, in the fixture's own repo for the agent. The same
    tree is also the baseline commit of the harness's private git dir (harness_git_dir), which
    the diff is taken against. Returns (path, the baseline commit's SHA). Arms C and D wire the
    hook with hook_dirs(run_dir), so they need one. With `case` and its running `registry`, a
    registry case's fixture also gets its setup/ overlay, the .npmrc, the sandbox's network
    settings and the ignore rule for npm's cache."""
    if arm in ("C", "D") and run_dir is None:
        raise ValueError(f"arm {arm} wires the hook with dirs in the run dir, and none was given")
    root = Path(tempfile.mkdtemp(prefix=FIXTURE_PREFIX))
    own = private_dir("harness-") if run_dir is None else None
    # absolute, since harness_git runs git with the fixture as its cwd
    _git_dirs[str(root)] = (Path(run_dir if run_dir is not None else own).resolve() / "harness-git", own)
    harness_git_dir(root).parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_SRC, root, dirs_exist_ok=True)
    install_stubs(root)
    if registry is not None:
        apply_setup(root, case)
        keep_stubs(root)
        (root / ".npmrc").write_text(registry.npmrc())
    git("init", "-q", cwd=root)
    if registry is not None:
        ignore_npm_cache(root / ".git")
    git("add", "-A", cwd=root)
    git("commit", "-qm", "Initial commit", cwd=root)

    settings = {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}}
    if registry is not None:
        settings["sandbox"].update(REGISTRY_SANDBOX)
    if arm in ("B", "C", "D"):
        for name in PRACTICES_SKILLS:
            shutil.copytree(SKILLS_DIR / name, root / ".claude" / "skills" / name)
    if arm in ("C", "D"):
        settings["hooks"] = hook_settings(None, None, *hook_dirs(run_dir))
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    git("add", "-A", ".claude", cwd=root)
    git("commit", "-qm", "Local Claude Code settings", cwd=root)
    harness_git(root, "init", "-q")
    if registry is not None:
        ignore_npm_cache(harness_git_dir(root))
    harness_git(root, "add", "-A")
    harness_git(root, "commit", "-qm", "Harness baseline")
    return root, harness_git(root, "rev-parse", "HEAD").strip()


def npm_test(root):
    p = subprocess.run(["npm", "test"], cwd=root, capture_output=True, text=True, errors="replace", timeout=300)
    return p.returncode == 0, p.stdout + p.stderr


# ---------------------------------------------------------------- fake registry

ORACLE_DEPS = HERE / "oracle_deps.mjs"  # the oracle helpers only registry cases import
REGISTRY_STUBS = HERE / "registry_stubs"  # react-dom: in the fixture's package.json, not in stubs/
REGISTRY_HOST = "127.0.0.2"  # 127.0.0.1 is in the sandbox's forced NO_PROXY, so it never reaches the host
REGISTRY_SANDBOX = {"allowUnsandboxedCommands": False, "network": {"allowedDomains": [REGISTRY_HOST]}}
NPM_CACHE = ".npm-cache"
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
INSTALL_SCRIPTS = ("preinstall", "install", "postinstall")
# Settings that would beat, or add to, the fixture's .npmrc when the harness runs npm itself.
_NPM_ENV_DROPPED = re.compile(r"^(npm_config_.*|.*_proxy)$", re.I)


def is_registry_case(case):
    return (CASES_DIR / case / "registry").is_dir()


def version_key(version):
    """A version as numbers, for the highest-version comparison; a case's versions are plain x.y.z."""
    return tuple(int(part) for part in version.split("."))


def registry_packages(registry_dir):
    """[(name, version, source dir)] a case's registry/ declares, as <name>/<version>/. A dir whose
    package.json disagrees with its path is refused, so a packument can't name another package."""
    found = []
    for pkg in sorted(d for d in Path(registry_dir).iterdir() if d.is_dir()):
        for src in sorted(d for d in pkg.iterdir() if d.is_dir()):
            manifest = json.loads((src / "package.json").read_text())
            if (manifest.get("name"), manifest.get("version")) != (pkg.name, src.name) or not PACKAGE_NAME.match(pkg.name):
                raise ValueError(f"{src}: package.json names {manifest.get('name')}@{manifest.get('version')}")
            found.append((pkg.name, src.name, src))
    return found


def pack_package(src):
    """An npm tarball of a package's source: every file under package/, with a fixed mode and
    time, so one source always packs to the same bytes."""
    src, raw = Path(src), io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for rel in sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()):
            data = (src / rel).read_bytes()
            info = tarfile.TarInfo(f"package/{rel}")
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    return raw.getvalue()


class FakeRegistry:
    """One run's npm registry: a stdlib HTTP server in a thread on 127.0.0.2, on a free port.
    Everything it answers is in a dict built at start from the case's registry/ dir (with arm D's
    warm-up case's, when that has one) and the stub packages, so a request path is only ever a
    key: never a filesystem path. Each request goes to `requests` and to `log_path`. A `with`
    block runs it, and leaving the block by any route stops it."""

    PUBLISHED = "2026-01-15T09:00:00.000Z"

    def __init__(self, case, arm="A", log_path=None):
        self.case, self.arm, self.log_path = case, arm, log_path
        self.requests, self.routes, self.advisories = [], {}, b"{}"
        self._lock = threading.Lock()
        self._server = self._log = None

    @property
    def url(self):
        return f"http://{REGISTRY_HOST}:{self._server.server_address[1]}/"

    def npmrc(self):
        return f"registry={self.url}\ncache={NPM_CACHE}\nfund=false\n"

    def npm_env(self):
        """The env for npm run by the harness itself, never the agent. It runs in this process's
        network namespace, where the registry is, so no proxy applies; nothing in the env may beat
        the fixture's .npmrc; and no user npmrc is read. The registry is set again here so nothing
        can send this npm to another one."""
        env = {k: v for k, v in os.environ.items() if not _NPM_ENV_DROPPED.match(k)}
        return dict(env, npm_config_registry=self.url, npm_config_userconfig=os.devnull,
                    npm_config_update_notifier="false")

    def _add(self, name, version, src, versions):
        tarball = pack_package(src)
        manifest = json.loads((Path(src) / "package.json").read_text())
        path = f"{name}/-/{name}-{version}.tgz"
        if f"/{path}" in self.routes:
            raise ValueError(f"{name}@{version} is declared twice for {self.case}")
        self.routes[f"/{path}"] = ("application/octet-stream", tarball)
        integrity = base64.b64encode(hashlib.sha512(tarball).digest()).decode()
        manifest["dist"] = {"tarball": f"{self.url}{path}", "shasum": hashlib.sha1(tarball).hexdigest(),
                            "integrity": f"sha512-{integrity}"}
        if any(s in (manifest.get("scripts") or {}) for s in INSTALL_SCRIPTS):
            manifest["hasInstallScript"] = True
        versions.setdefault(name, {})[version] = manifest

    def _build(self):
        versions = {}
        for name, src in {**stub_packages(), **{d.name: d for d in sorted(REGISTRY_STUBS.iterdir())}}.items():
            self._add(name, json.loads((src / "package.json").read_text())["version"], src, versions)
        warmup = warmup_case(self.case) if self.arm == "D" else self.case
        for case in dict.fromkeys((self.case, warmup)):
            if is_registry_case(case):
                for name, version, src in registry_packages(CASES_DIR / case / "registry"):
                    self._add(name, version, src, versions)
        for name, by_version in versions.items():
            latest = max(by_version, key=version_key)
            top = by_version[latest]
            packument = {"name": name, "description": top.get("description", ""), "license": top.get("license"),
                         "dist-tags": {"latest": latest}, "versions": by_version,
                         "time": {v: self.PUBLISHED for v in by_version}}
            self.routes[f"/{name}"] = ("application/json", json.dumps(packument).encode())
        advisories = CASES_DIR / self.case / "registry" / "advisories.json"
        if advisories.is_file():
            self.advisories = advisories.read_bytes()

    def _note(self, method, path):
        parts = urllib.parse.urlsplit(path)
        if parts.scheme:  # an absolute request line, as a proxy can send: the path is what's logged
            path = parts.path + (f"?{parts.query}" if parts.query else "")
        with self._lock:
            self.requests.append({"method": method, "path": path})
            if self._log:
                self._log.write(f"{method} {path}\n")
                self._log.flush()

    def _handler(self):
        registry = self

        class Handler(http.server.BaseHTTPRequestHandler):
            timeout = 10  # an idle connection doesn't keep its thread

            def log_message(self, *_args):
                pass

            def _send(self, status, content_type, body):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_GET(self):
                registry._note(self.command, self.path)
                key = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                content_type, body = registry.routes.get(key, ("application/json", None))
                if body is None:
                    self._send(404, "application/json", b'{"error":"not found"}')
                else:
                    self._send(200, content_type, body)

            do_HEAD = do_GET

            def do_POST(self):
                registry._note(self.command, self.path)
                self._drain()
                if urllib.parse.urlsplit(self.path).path == "/-/npm/v1/security/advisories/bulk":
                    self._send(200, "application/json", registry.advisories)
                else:
                    self._send(404, "application/json", b'{"error":"not found"}')

            def _refuse(self):
                registry._note(self.command, self.path)
                self._send(405, "application/json", b'{"error":"read-only"}')

            do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

            def _drain(self):
                """Reads the body npm sends, unused: answering over an unread body can reset the
                connection. Content-Length or chunked, a bounded amount."""
                length = self.headers.get("Content-Length")
                if length and length.isdigit():
                    self.rfile.read(min(int(length), 2 ** 24))
                elif "chunked" in (self.headers.get("Transfer-Encoding") or ""):
                    for _ in range(2 ** 12):
                        size = int(self.rfile.readline(64).strip() or b"0", 16)
                        self.rfile.read(min(size, 2 ** 20) + 2)
                        if not size:
                            break

        return Handler

    def __enter__(self):
        self._server = http.server.ThreadingHTTPServer((REGISTRY_HOST, 0), self._handler())
        self._server.daemon_threads = True
        try:
            self._build()
            if self.log_path is not None:
                self._log = open(self.log_path, "a")
        except BaseException:
            self._server.server_close()
            raise
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        return self

    def __exit__(self, *_exc):
        self._server.shutdown()
        self._server.server_close()
        with self._lock:
            if self._log:
                self._log.close()
            self._log = None
        return False


def apply_setup(root, case):
    """Copies the case's setup/ overlay into the fixture, then puts each registry package its
    package.json names into node_modules, as a project that already installed it would have."""
    setup = CASES_DIR / case / "setup"
    if setup.is_dir():
        shutil.copytree(setup, root, dirs_exist_ok=True)
        install_declared(root, case)


def keep_stubs(root):
    """Makes `npm install` leave the stubs alone, which needs two things in a registry fixture.
    react-dom is in package.json but in no stub dir: it goes into node_modules, or npm fetches it.
    server-only and client-only are stubs package.json doesn't name, and npm prunes what's
    extraneous, so they go in package.json, at their versions. Measured with npm 11."""
    for src in REGISTRY_STUBS.iterdir():
        shutil.copytree(src, Path(root) / "node_modules" / src.name)
    path = Path(root) / "package.json"
    manifest = json.loads(path.read_text())
    deps = dict(manifest.get("dependencies") or {})
    for name, src in stub_packages().items():
        deps.setdefault(name, json.loads((src / "package.json").read_text())["version"])
    manifest["dependencies"] = dict(sorted(deps.items()))
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def install_declared(root, case):
    """Copies into node_modules every package the fixture's package.json names that the case's
    registry declares, at the named version (else its highest), without npm. Offline tests use it
    for an overlay's dependencies too."""
    declared = json.loads((Path(root) / "package.json").read_text()).get("dependencies") or {}
    packages = registry_packages(CASES_DIR / case / "registry")
    for name, wanted in declared.items():
        versions = {version: src for pkg, version, src in packages if pkg == name}
        if versions:
            dest = Path(root) / "node_modules" / name
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(versions.get(wanted.lstrip("^~"), versions[max(versions, key=version_key)]), dest)


def ignore_npm_cache(git_dir):
    """npm's cache is in the fixture (the sandbox lets the agent write there) and in no diff."""
    info = Path(git_dir) / "info"
    info.mkdir(parents=True, exist_ok=True)
    with open(info / "exclude", "a") as f:
        f.write(f"{NPM_CACHE}/\n")


def package_deps(root):
    """{name: range} of everything the fixture's package.json depends on, in any section; {} when
    it can't be read."""
    try:
        manifest = json.loads((Path(root) / "package.json").read_text())
        return {k: v for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
                for k, v in (manifest.get(section) or {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def oracle_evidence(events, deps_before, requests):
    """What a registry case's oracle gets besides the fixture, from the case turn: the agent's
    Bash commands in order, its final reply, the registry requests, and the package.json
    dependencies from before the turn."""
    result = result_event(events) or {}
    return {
        "bash": [u["input"]["command"] for u in tool_uses(events)
                 if u.get("name") == "Bash" and isinstance((u.get("input") or {}).get("command"), str)],
        "reply": result.get("result") if isinstance(result.get("result"), str) else "",
        "registry_requests": requests,
        "deps_before": deps_before,
    }


def registry_route_problem(fixture, case, registry):
    """The dry run's proof of the route, as a problem string or None: a real `npm install` of the
    case's main package (registry/main names it) through the registry, which must fetch its tarball
    from there, leave every stub byte for byte as it was, and leave `npm test` green."""
    spec = (CASES_DIR / case / "registry" / "main").read_text().strip()
    name = spec.split("@")[0]
    stubs = {pkg: tree_hash(Path(fixture) / "node_modules" / pkg)
             for pkg in [*stub_packages(), *(d.name for d in REGISTRY_STUBS.iterdir())]}
    p = subprocess.run(["npm", "install", spec], cwd=fixture, env=registry.npm_env(), capture_output=True, text=True,
                       errors="replace", timeout=300, start_new_session=True)
    if p.returncode != 0:
        return f"npm install {spec} exited {p.returncode}: {(p.stdout + p.stderr)[-1500:]}"
    if not any(r["path"].startswith(f"/{name}/-/") for r in registry.requests):
        return f"npm install {spec} fetched no tarball from the registry: {registry.requests}"
    if not (Path(fixture) / "node_modules" / name / "package.json").is_file():
        return f"npm install {spec} left no node_modules/{name}"
    changed = [pkg for pkg, digest in stubs.items()
               if not (Path(fixture) / "node_modules" / pkg).is_dir() or tree_hash(Path(fixture) / "node_modules" / pkg) != digest]
    if changed:
        return f"npm install {spec} replaced or removed stubs: {', '.join(changed)}"
    ok, output = npm_test(fixture)
    return None if ok else f"npm test failed after the install: {output[-1500:]}"


# ---------------------------------------------------------------- session

def claude_cmd(model, extra=(), effort=None):
    """With no effort, the session gets Claude Code's built-in default for the model:
    --setting-sources project,local drops the user's saved effortLevel."""
    return ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
            *(["--effort", effort] if effort else []),
            "--setting-sources", "project,local", "--strict-mcp-config",
            "--permission-mode", "acceptEdits", "--max-turns", "60", *extra]


def prompt_of(case):
    return (CASES_DIR / case / "prompt.md").read_text()


def turns_for(case, arm, model, effort=None):
    """[(label, prompt text, command)] for one run. Every turn passes the effort again:
    --resume keeps the session's model but not its effort."""
    if arm != "D":
        return [("task", prompt_of(case), claude_cmd(model, effort=effort))]
    sid = str(uuid.uuid4())
    return [
        ("warmup", prompt_of(warmup_case(case)), claude_cmd(model, ["--session-id", sid], effort)),
        ("compact", "/compact", claude_cmd(model, ["--resume", sid], effort)),
        ("task", prompt_of(case), claude_cmd(model, ["--resume", sid], effort)),
    ]


def transcript_efforts(events_by_turn):
    """The effort levels the session transcripts record on assistant entries. The stream
    doesn't carry them, and this shows what an unflagged run really got."""
    projects = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    seen = set()
    for events in events_by_turn:
        sid = next((e.get("session_id") for e in events if e.get("subtype") == "init"), None)
        for path in projects.glob(f"*/{sid}.jsonl") if sid else ():
            with open(path, errors="replace") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(entry, dict) and entry.get("type") == "assistant" and entry.get("effort"):
                        seen.add(entry["effort"])
    return sorted(seen)


def read_stream(path):
    events = []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return events


def tool_uses(events):
    for e in events:
        if e.get("type") == "assistant":
            for item in (e.get("message") or {}).get("content") or []:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    yield item


def skill_called(inp):
    """The skill a Skill tool call loads: its `skill` input, without a leading slash or a
    plugin's `name:` prefix. "" when there is none."""
    name = inp.get("skill") if isinstance(inp, dict) else None
    return name.strip().lstrip("/").rsplit(":", 1)[-1] if isinstance(name, str) else ""


def triggered(events, skill):
    """Whether a turn loaded `skill`: a Skill call whose skill is `skill` (its args don't count),
    or a Read of its SKILL.md."""
    for use in tool_uses(events):
        inp = use.get("input") or {}
        if use.get("name") == "Skill" and skill_called(inp) == skill:
            return True
        if use.get("name") == "Read" and str(inp.get("file_path", "")).endswith(f"{skill}/SKILL.md"):
            return True
    return False


def hook_denials(events):
    """Hook denials seen in the stream. Heuristic, kept in one function to tune against the
    real hook: hook_response events carrying a deny or block decision; failing those, tool
    results that are errors carrying the engine's `[practices:` tag (how Claude Code 2.1.305
    renders a PreToolUse deny: "PreToolUse:Write hook error: [practices:L2:...] ..."). Not text
    that says "hook" and "denied": a ugrep listing ("Permission denied" beside a hooks path)
    read as a deny in smoke2-auth-haiku, and no real deny was ever worded that way."""
    responses = 0
    for e in events:
        if e.get("type") == "system" and "hook" in str(e.get("subtype", "")):
            text = json.dumps(e).replace(" ", "")
            if '\\"permissionDecision\\":\\"deny\\"' in text or '\\"decision\\":\\"block\\"' in text \
                    or '"permissionDecision":"deny"' in text or '"decision":"block"' in text:
                responses += 1
    if responses:
        return responses
    results = 0
    for e in events:
        if e.get("type") != "user":
            continue
        for item in (e.get("message") or {}).get("content") or []:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                if item.get("is_error") is True and "[practices:" in json.dumps(item.get("content", "")):
                    results += 1
    return results


def stream_summary(events):
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {
        "turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "total_cost_usd": result.get("total_cost_usd"),
        "result_subtype": result.get("subtype"),
        "memory_paths": init.get("memory_paths"),
        "claude_code_version": init.get("claude_code_version"),
        # the skills the session listed at init; rows before 2026-10-20 have this as "skills"
        "init_skills": init.get("skills"),
    }


# ---------------------------------------------------------------- grading

BWRAP = shutil.which("bwrap")
BWRAP_FLAGS = ["--unshare-net", "--unshare-pid", "--unshare-ipc", "--die-with-parent", "--new-session"]
# The only host dirs the oracle sees, read-only. No /home, /run, /mnt, /var or /root: a
# read-only mount doesn't stop connect() on a Unix socket (tmux, docker, Claude Code's own),
# and /mnt holds the Windows drives on WSL.
SYSTEM_DIRS = ["/usr", "/etc", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32"]
PRACTICES_MOUNT = "/practices"  # where this checkout's tests/practices appears inside
DUMMY_LLM_KEY = "sk-test-0000000000000000"  # agent code may refuse to run without a key
EVIDENCE_VAR = "ORACLE_EVIDENCE"  # a registry case's oracle reads the session's evidence from this path


def system_binds():
    """Read-only binds for the system dirs that exist; a merged-/usr symlink is recreated."""
    args = []
    for d in SYSTEM_DIRS:
        if os.path.islink(d):
            args += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            args += ["--ro-bind", d, d]
    return args


def node_binary():
    return os.path.realpath(shutil.which("node") or "/usr/bin/node")


def bwrap_usable():
    """Whether bwrap can start here. It can't nested inside Claude Code's own sandbox."""
    if not BWRAP:
        return False
    try:
        p = subprocess.run([BWRAP, *BWRAP_FLAGS, *system_binds(), "--proc", "/proc", "--dev", "/dev", "true"],
                           capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def contained(cmd, writable, readable=None, cwd=None, real_home=None):
    """`cmd` under bwrap, from an allowlist: the system dirs read-only, a fresh /proc, /dev and
    /tmp, `readable` ({host path: path inside}) bound read-only, `writable` bound read-write
    at the same path, no network, its own pid namespace. Nothing else of the host exists
    inside. A writable path under the real $HOME is refused: it would bring part of $HOME in."""
    home = Path(real_home or os.environ.get("HOME", "/nonexistent")).resolve()
    for p in writable:
        if Path(p).resolve().is_relative_to(home):
            raise ValueError(f"writable path {p} is under {home}; grading keeps $HOME out of the sandbox")
    args = [BWRAP, *BWRAP_FLAGS, *system_binds(), "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    node = node_binary()
    if not node.startswith("/usr/"):  # e.g. an nvm install
        prefix = os.path.dirname(os.path.dirname(node))
        args += ["--ro-bind", prefix, prefix]
    for src, dest in (readable or {}).items():
        args += ["--ro-bind", str(src), str(dest)]
    for p in writable:
        args += ["--bind", str(p), str(p)]
    if cwd:
        args += ["--chdir", str(cwd)]
    return [*args, "--", *cmd]


def grade_env(fixture, scratch, evidence=None):
    """The oracle's whole environment: an allowlist, nothing inherited beyond it. HOME, DB_PATH
    and TMPDIR live in `scratch`, the oracle's only writable dir besides the fixture. With
    `evidence` (a registry case's), that JSON goes in `scratch` and EVIDENCE_VAR names it."""
    scratch = Path(scratch)
    for d in ("home", "tmp"):
        (scratch / d).mkdir(parents=True, exist_ok=True)
    extra = {}
    if evidence is not None:
        (scratch / "evidence.json").write_text(json.dumps(evidence))
        extra[EVIDENCE_VAR] = str(scratch / "evidence.json")
    return {
        **extra,
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(scratch / "home"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "FIXTURE": str(fixture),
        "DB_PATH": str(scratch / "oracle.db"),
        "TMPDIR": str(scratch / "tmp"),
        "LLM_API_KEY": DUMMY_LLM_KEY,
    }


def grading_contained(unsafe):
    """True to grade under bwrap; False only with --unsafe-grade. Exits when neither works."""
    if bwrap_usable():
        return True
    if unsafe:
        print("run.py: WARNING: bwrap is unavailable; grading runs agent code uncontained (--unsafe-grade)")
        return False
    sys.exit("run.py: grading runs agent-written code, so it needs bwrap (bubblewrap) to contain it, "
             "and bwrap can't start here (not installed, or nested inside another sandbox). "
             "Run sandbox-off with bwrap installed, or pass --unsafe-grade to grade uncontained.")


def grade(fixture, case, run_dir, contain=True, home=None, evidence=None):
    """Runs the case's oracle against the fixture, under bwrap unless `contain` is False.
    The oracle writes only to the fixture and a fresh scratch dir (HOME, DB_PATH, TMPDIR) in
    the system temp dir, removed afterwards; run_dir may sit under $HOME, so run.py writes the
    oracle's output there itself, outside bwrap. `home` is the real home kept out (default
    $HOME). `evidence` is a registry case's oracle_evidence(), written into the scratch dir only
    now, after the session exited. Returns the verdict dict; a missing verdict line or a timeout
    scores broken, a node_modules the agent pointed outside the fixture scores broken untouched,
    and a fixture the sandbox refuses (a writable path under $HOME) scores error."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    problem = node_modules_problem(fixture)
    if problem:
        (run_dir / "oracle.out").write_text(f"not graded: {problem}\n")
        return {"verdict": "broken", "checks": [{"name": "node_modules replaced", "ok": False, "detail": problem}]}
    install_stubs(fixture)  # the agent could have edited node_modules/next
    scratch = Path(tempfile.mkdtemp(prefix="practices-grade-"))
    try:
        env = grade_env(fixture, scratch, evidence)
        if contain:
            inside = Path(PRACTICES_MOUNT)
            try:
                cmd = contained(
                    [node_binary(), "--import", (inside / LOADER.relative_to(HERE)).as_uri(),
                     str(inside / "cases" / case / "oracle.mjs")],
                    writable=[fixture, scratch], readable={HERE: PRACTICES_MOUNT}, cwd=fixture, real_home=home)
            except ValueError as e:
                (run_dir / "oracle.out").write_text(f"not graded: {e}\n")
                return {"verdict": "error", "checks": [{"name": "containment", "ok": False, "detail": str(e)}]}
        else:
            cmd = [node_binary(), "--import", LOADER.as_uri(), str(CASES_DIR / case / "oracle.mjs")]
        try:
            # its own session, so a Ctrl-C lets a grade in progress finish and keep its row
            p = subprocess.run(cmd, cwd=fixture, env=env, capture_output=True, text=True, errors="replace",
                               start_new_session=True,
                               timeout=ORACLE_TIMEOUT)
            stdout, stderr = p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = f"oracle timed out after {ORACLE_TIMEOUT} s"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    (run_dir / "oracle.out").write_text(stdout + "\n--- stderr ---\n" + stderr)
    for line in reversed(stdout.splitlines()):
        if line.startswith('{"verdict"'):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"verdict": "broken", "checks": [{"name": "oracle output", "ok": False, "detail": stderr[-1500:]}]}


def git_dir_problem(fixture):
    """Why the fixture's .git looks tampered with, or None: it isn't a plain directory (a
    symlink, or a gitfile pointing elsewhere). The diff never reads it (harness_git_dir), so
    this is a tripwire on the run, not what keeps git safe."""
    d = Path(fixture) / ".git"
    if d.is_symlink() or not d.is_dir():
        return f"{d} is not a plain directory"
    return None


def agent_diff(fixture, base, text=False):
    """Everything the agent changed in the work tree since the baseline commit `base`, committed
    or not, through the harness's own git dir: no config the agent could write is read. --binary
    (for regrading) by default; `text` takes --text instead, every file as text lines, so a
    .gitattributes marking a file -diff can't hide its added lines from suspect_words."""
    harness_git(fixture, "add", "-A")
    return harness_git(fixture, "diff", "--cached", "--text" if text else "--binary", "--no-ext-diff", "--no-textconv", base)


# Words in the agent's added lines that could forge the oracle's verdict from inside its
# process (the agent's code runs there): a tripwire, the diff review is the backstop.
SUSPECT_WORDS = ("verdict", "stepResult", 'process.on("exit"', "process.on('exit'", "writeSync(1", "process.stdout.write")


def suspect_words(diff):
    """The SUSPECT_WORDS the diff's added lines contain, in order; [] when none."""
    added = "\n".join(line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    return [w for w in SUSPECT_WORDS if w in added]


PATH_TOKEN = re.compile(r"""[^\s"'`;|&<>()=,]+""")


def contamination(events_by_turn, fixture, tmp=None):
    """Paths the session's tool calls named outside its own fixture that hold practices skills
    (.claude/skills, SKILL.md) or another fixture (FIXTURE_PREFIX* in the system temp dir), up
    to 5. The fixture's own test dirs (ledgerly-test-*) don't share the prefix, so they never count."""
    fixture = os.path.normpath(str(fixture))
    others = os.path.join(tmp or tempfile.gettempdir(), FIXTURE_PREFIX)
    found = []

    def strings(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x)
        elif isinstance(v, list):
            for x in v:
                yield from strings(x)

    for events in events_by_turn:
        for use in tool_uses(events):
            inp = use.get("input")
            texts = list(strings(inp))
            if isinstance(inp, dict) and isinstance(inp.get("path"), str):  # Glob and Grep: pattern under path
                texts += [os.path.join(inp["path"], inp[k]) for k in ("pattern", "glob") if isinstance(inp.get(k), str)]
            for text in texts:
                for token in PATH_TOKEN.findall(text):
                    if not (".claude/skills" in token or "SKILL.md" in token or FIXTURE_PREFIX in token):
                        continue
                    full = os.path.normpath(os.path.join(fixture, os.path.expanduser(token)))
                    if full == fixture or full.startswith(fixture + os.sep):
                        continue
                    skills = ".claude/skills" in full or full.endswith("SKILL.md") or "/SKILL.md" in full
                    if (skills or full.startswith(others)) and full not in found:
                        found.append(full)
    return found[:5]


def skill_mismatch(arm, owner, init_skills):
    """What's wrong with the skills a session listed at init: an arm-A session that lists a
    practices skill (it installs none), or a B, C or D session that lacks the case owner's.
    [] when they match, or when the row recorded none."""
    if not isinstance(init_skills, list):
        return []
    names = {skill_called({"skill": s.get("name") if isinstance(s, dict) else s}) for s in init_skills} - {""}
    if arm == "A":
        return [f"init_skills lists {name} (arm A installs none)" for name in PRACTICES_SKILLS if name in names]
    return [] if owner in names else [f"init_skills lacks {owner} (arm {arm} installs it)"]


def _exited(pid):
    """True once `pid` has exited, without reaping it (WNOWAIT): while it stays a zombie its
    pid, and so its process group id, can't be reused by an unrelated process."""
    return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None


MARKER_VAR = "PRACTICES_RUN"
STOP = threading.Event()  # set on Ctrl-C: running turns end, no new turn or grade starts
_active = {}  # marker -> pid of each running claude turn
_active_lock = threading.Lock()


class Interrupted(Exception):
    pass


def marked_processes(marker):
    """Pids of this uid's processes whose environment carries PRACTICES_RUN=<marker> exactly.
    The marker is the proof a process came from our session: never match by name, cwd or
    start time (other Claude sessions run the same tools on this machine)."""
    needle = f"{MARKER_VAR}={marker}".encode()
    uid, me, pids = os.getuid(), os.getpid(), []
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) == me:
            continue
        try:
            if os.stat(f"/proc/{name}").st_uid != uid:
                continue
            with open(f"/proc/{name}/environ", "rb") as f:
                environ = f.read()
        except OSError:
            continue
        if needle in environ.split(b"\0"):
            pids.append(int(name))
    return pids


def _cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace").strip()[:300]
    except OSError:
        return ""


def kill_marked(marker, grace=2.0):
    """SIGTERM every process carrying the marker, then SIGKILL any still carrying it after
    `grace` seconds (re-scanned, so a reused pid without the marker is never hit). Returns a
    record of each one found: {pid, cmdline, signal}."""
    found = {pid: _cmdline(pid) for pid in marked_processes(marker)}
    for pid in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + grace
    while found and time.monotonic() < deadline and marked_processes(marker):
        time.sleep(0.1)
    killed = set()
    for pid in marked_processes(marker):
        try:
            os.kill(pid, signal.SIGKILL)
            killed.add(pid)
        except (ProcessLookupError, PermissionError):
            pass
    return [{"pid": pid, "cmdline": cmd, "signal": "KILL" if pid in killed else "TERM"} for pid, cmd in found.items()]


def stop_all():
    """Ctrl-C: stop every running turn and everything it started, by marker."""
    STOP.set()
    with _active_lock:
        markers = list(_active)
    for marker in markers:
        kill_marked(marker, grace=0.5)


def run_turn(cmd, prompt_file, cwd, stdout_path, stderr_path, timeout, marker=None):
    """Runs one claude turn in its own session (process group), stdin from a file and stdout
    and stderr to files, so no pipe can hold the run open, with PRACTICES_RUN=<marker> in its
    env. When the turn ends, times out or STOP is set, the whole group is killed, then any
    process still carrying the marker (a child that called setsid left the group): nothing
    the session started outlives it or writes while the oracle grades.
    Returns (exit code or None, timed out, the strays killed by marker: [{pid, cmdline, signal}])."""
    marker = marker or uuid.uuid4().hex
    env = dict(os.environ, **{MARKER_VAR: marker})
    with open(prompt_file) as stdin, open(stdout_path, "w") as out, open(stderr_path, "w") as err:
        p = subprocess.Popen(cmd, stdin=stdin, stdout=out, stderr=err, cwd=cwd, env=env,
                             start_new_session=True)
    with _active_lock:
        _active[marker] = p.pid
    try:
        deadline = time.monotonic() + timeout
        timed_out = False
        while not _exited(p.pid) and not STOP.is_set():
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(0.5)
        try:
            os.killpg(p.pid, signal.SIGKILL)  # p is unreaped, so this pgid is still ours
        except (ProcessLookupError, PermissionError):
            pass
        code = p.wait()
        strays = kill_marked(marker)
    finally:
        with _active_lock:
            _active.pop(marker, None)
    return (None if timed_out else code), timed_out, strays


# ---------------------------------------------------------------- one run

def result_event(events):
    return next((e for e in reversed(events) if e.get("type") == "result"), None)


def result_failed(result):
    """A result event that reports a failure of the session itself (usage limit, expired login,
    API error): is_error true, or an error_* subtype."""
    return bool(result) and (result.get("is_error") is True or str(result.get("subtype", "")).startswith("error"))


def infra_failures(labels, exits, events_by_turn, timed_out_label=None):
    """Harness or infrastructure failures in a run's turns (they score error, not broken):
    a turn with no stream events at all, a nonzero claude exit with no result event, a result
    event that reports an error, or a timeout in arm D's warm-up or compact turn (the case
    turn hasn't run, so there is nothing of the agent's to grade)."""
    failures = []
    for label, code, events in zip(labels, exits, events_by_turn):
        result = result_event(events)
        if not events:
            failures.append(f"{label}: no stream output (exit {code})")
        elif code not in (0, None) and result is None:
            failures.append(f"{label}: claude exited {code} with no result event")
        elif result_failed(result):
            failures.append(f"{label}: result is an error ({result.get('subtype')}, is_error {result.get('is_error')})")
    if timed_out_label and timed_out_label != "task":
        failures.append(f"{timed_out_label}: timed out before the case turn")
    return failures


def finish_run(fixture, harness_sha, case, run_dir, contain, skip_grade=(), evidence=None):
    """Saves the agent's diff, then grades (unless `skip_grade` lists infra failures, which
    score error). The diff is taken before grading touches the fixture (the stub reinstall, any
    files the agent's code writes); a failed diff is recorded and never costs the verdict.
    `evidence` goes to grade(). Returns (verdict dict, diff error or None)."""
    run_dir = Path(run_dir)
    diff_error = None
    problem = git_dir_problem(fixture)
    if problem:  # git there could read the agent's own config: no diff, no grade
        return {"verdict": "error", "checks": [{"name": "fixture .git", "ok": False, "detail": problem}]}, problem
    try:
        (run_dir / "diff.patch").write_text(agent_diff(fixture, harness_sha))
        (run_dir / "diff-text.patch").write_text(agent_diff(fixture, harness_sha, text=True))
    except (subprocess.CalledProcessError, OSError) as e:
        diff_error = f"{e!r}: {getattr(e, 'stderr', '')}"[:1000]
    if skip_grade:
        return {"verdict": "error", "checks": [{"name": "harness", "ok": False,
                                                "detail": "; ".join(skip_grade)}]}, diff_error
    return grade(fixture, case, run_dir, contain=contain, evidence=evidence), diff_error


def run_one(case, arm, index, args, out):
    run_dir = out / f"{case}-{arm}-{index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    registry = FakeRegistry(case, arm, run_dir / "registry.log") if is_registry_case(case) else None
    streams, labels, exits, timed_out, stray_kills = [], [], [], False, []
    deps_before, requests_from = {}, 0
    with registry or contextlib.nullcontext():  # up for the session only, whatever ends it
        fixture, harness_sha = build_fixture(arm, run_dir, case=case, registry=registry)
        skills = installed_skills(fixture)  # before the session, which could edit its copy
        hook = hook_hash() if arm in ("C", "D") else NO_HOOK
        case_code = case_hash(case)
        warmup_code = warmup_hash(case, arm)
        harness_code = harness_hash()
        turns = turns_for(case, arm, args.model, args.effort)
        for n, (label, prompt, cmd) in enumerate(turns, 1):
            if STOP.is_set():
                raise Interrupted()
            if registry and label == "task":  # the evidence is the case turn's, not arm D's warm-up
                deps_before, requests_from = package_deps(fixture), len(registry.requests)
            suffix = "" if len(turns) == 1 else f"-{n}-{label}"
            stream = run_dir / f"stream{suffix}.jsonl"
            prompt_file = run_dir / f"prompt{suffix}.txt"
            prompt_file.write_text(prompt)
            streams.append(str(stream))
            labels.append(label)
            code, timed_out, kills = run_turn(cmd, prompt_file, fixture, stream,
                                              run_dir / f"stderr{suffix}.txt", SESSION_TIMEOUT)
            exits.append(code)
            stray_kills += [{"turn": label, **k} for k in kills]
            if timed_out:
                break
    if STOP.is_set():
        raise Interrupted()

    events_by_turn = [read_stream(s) for s in streams]
    failures = infra_failures(labels, exits, events_by_turn, timed_out_label=labels[-1] if timed_out else None)
    evidence = oracle_evidence(events_by_turn[-1], deps_before, registry.requests[requests_from:]) if registry else None
    verdict, diff_error = finish_run(fixture, harness_sha, case, run_dir, args.contain, skip_grade=failures, evidence=evidence)
    diff = run_dir / "diff.patch"
    try:
        suspect = suspect_words((run_dir / "diff-text.patch").read_text(errors="replace"))
    except OSError:
        suspect = []
    per_turn = [stream_summary(turn) for turn in events_by_turn]
    summary = dict(per_turn[0])  # init facts (memory_paths, skills) from the first turn
    contaminated = skill_mismatch(arm, CASE_INFO[case].owner, summary["init_skills"]) + contamination(events_by_turn, fixture)
    summary["result_subtype"] = per_turn[-1]["result_subtype"]
    for key in ("turns", "duration_ms", "total_cost_usd"):
        values = [t[key] for t in per_turn if isinstance(t[key], (int, float))]
        summary[key] = sum(values) if values else None
    owner = CASE_INFO[case].owner
    # each turn against the owner of the case it ran: arm D's warm-up ran warmup_case(case)
    turn_owner = {"warmup": CASE_INFO[warmup_case(case)].owner}
    triggered_turns = {label: triggered(turn, turn_owner.get(label, owner)) for label, turn in zip(labels, events_by_turn)}
    denials_turns = {label: hook_denials(turn) for label, turn in zip(labels, events_by_turn)}
    row = {
        "case": case, "arm": arm, "run": index, "owner": owner, "kind": CASE_INFO[case].kind,
        "planned_n": args.n,  # so a summary of a run cut short still wants every planned row
        "model": args.model, "effort": args.effort or "default",
        "effort_seen": transcript_efforts(events_by_turn),
        "verdict": verdict["verdict"], "checks": verdict.get("checks", []),
        # the case turn's figures; arm D's warm-up and compact turns are reported apart
        "triggered": triggered_turns.get("task", False),
        "triggered_turns": triggered_turns,
        **summary,
        # the fingerprint: the summary pools only rows equal on all five parts
        "skills": skills,  # {name: tree_hash} installed
        "hook": hook,  # hook_hash() for C and D, NO_HOOK for A and B
        "case_hash": case_code,  # case_hash(case)
        "warmup_hash": warmup_code,  # warmup_hash(case, arm): arm D's warm-up prompt
        "harness_hash": harness_code,  # harness_hash(): run.py
        # tripwires: the bar counts such a row unresolved until a person sets "reviewed": true
        "suspect": suspect, "contaminated": contaminated,
        "hook_denials": denials_turns.get("task", 0),
        "hook_denials_turns": denials_turns,
        "is_error": any(result_failed(result_event(turn)) for turn in events_by_turn),
        "exit_codes": exits, "timed_out": timed_out,
        "strays": len(stray_kills), "stray_kills": stray_kills,
        "harness_sha": harness_sha,
        "hook_errors": hook_errors(run_dir) if arm in ("C", "D") else "none",
        "stream": streams, "oracle": str(run_dir / "oracle.out"), "diff": str(diff),
    }
    if diff_error:
        row["diff_error"] = diff_error
    if registry:
        row["registry_log"] = str(registry.log_path)
    if args.keep:
        row["fixture"] = str(fixture)
    else:
        remove_fixture(fixture)
    log(f"  {case:16} {arm} #{index}: {row['verdict']:7} triggered={row['triggered']} "
        f"cost={row['total_cost_usd']}")
    return row


# ---------------------------------------------------------------- summary

MIN_VALID = 3  # arm A classifies a case only on at least this many pass or fail runs


def a_class(counts):
    """What arm A's counts for a case and model say: "discriminates" (fail on more than half of
    at least MIN_VALID valid runs), "no-harm" (enough valid runs, fail on half or fewer: the
    model gets it right without the skill) or "unclassified" (too few valid runs, or none)."""
    if not counts:
        return "unclassified"
    valid = counts["pass"] + counts["fail"]
    if valid < MIN_VALID:
        return "unclassified"
    return "discriminates" if counts["fail"] * 2 > valid else "no-harm"


def bar(case, arm, counts, n, a=None, installed=None):
    """(label, missed) for one case and arm of one model against the pass bar. `a` is arm A's
    counts for the same case and model (imported rows included; None when there are none), and
    `installed` the skills the arm's rows ran with (default: PRACTICES_SKILLS)."""
    label, missed = _bar(case, arm, counts, n, a, installed)
    held = counts.get("unresolved", 0)
    return (f"{label}; {held} unresolved (review by hand)", missed) if held else (label, missed)


def no_rows(n):
    """The label of a line that could miss and holds no row (a case or arm that never ran, or
    whose runs a Ctrl-C stopped): a MISS, never pass 0 of 0."""
    return "MISS (no rows" + (f": 0 of {n} runs finished)" if n else ": none of its runs finished)")


def _bar(case, arm, counts, n, a=None, installed=None):
    owner, kind = CASE_INFO[case]
    p, f, b = counts["pass"], counts["fail"], counts["broken"]
    empty = not sum(counts.values())  # every row counts under exactly one key
    if arm == "A":
        if kind == BENIGN:
            return "reported only", False
        if empty:
            return no_rows(n), True
        cls, valid = a_class(counts), p + f
        if cls == "unclassified":
            return f"MISS (too few valid runs: {valid} of the {MIN_VALID} needed)", True
        if cls == "discriminates":
            return f"discriminates (fail {f} of {valid} valid)", False
        return f"no-harm check (fail {f} of {valid} valid)", False
    if owner not in (PRACTICES_SKILLS if installed is None else installed):
        return "reported only (off-target)", False
    if arm not in ("C", "D"):
        return "reported only", False
    if empty:
        return no_rows(n), True
    if kind == BENIGN:
        ok = p == n and b == 0
        return ("green" if ok else f"MISS (pass {p} of {n}, broken {b})"), not ok
    ok = p == n
    label = "green" if ok else f"MISS (pass {p} of {n})"
    cls = a_class(a)
    if cls == "no-harm":
        label += "; no-harm check, not evidence that the skill helps"
    elif cls == "unclassified":
        label += "; arm A unclassified: a regression check, not yet evidence that the skill helps"
    return label, not ok


def fingerprint(row):
    """What a row ran with, part by part: {"skills": {name: tree_hash}, "hook": hook_hash() or
    NO_HOOK, "case": case_hash()}. A part the row didn't record is None, "unrecorded", which
    equals only another None, so old rows pool only with each other. Arm A installs no skill and
    arms A and B no hook, so those parts are {} and NO_HOOK whatever the row says (rows from
    before fingerprints included)."""
    arm, skills, hook, case = row.get("arm"), row.get("skills"), row.get("hook"), row.get("case_hash")
    warmup, harness = row.get("warmup_hash"), row.get("harness_hash")
    text = lambda v: v if isinstance(v, str) and v else None
    return {
        "skills": {} if arm == "A" else (skills if isinstance(skills, dict) else None),
        "hook": NO_HOOK if arm in ("A", "B") else text(hook),
        "case": text(case),
        "warmup": NO_HOOK if arm != "D" else text(warmup),
        "harness": text(harness),
    }


def short_part(value):
    if value is None:
        return "unrecorded"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k} {str(v)[:12]}" for k, v in sorted(value.items())) + "}"
    return value if value == NO_HOOK else value[:12]


def short(fp):
    return ", ".join(f"{part} {short_part(fp[part])}" for part in FINGERPRINT_PARTS)


def pooled_prints(rows):
    """The distinct fingerprints among the rows that aren't error rows, in order."""
    prints = []
    for r in rows:
        fp = fingerprint(r)
        if verdict_of(r) != "error" and fp not in prints:
            prints.append(fp)
    return prints


def reviewed(row):
    return row.get("reviewed") is True


def verdict_of(row):
    """The verdict the bar counts: a reviewed row's hand_verdict when it has a valid one, else
    the row's own."""
    hand = row.get("hand_verdict")
    return hand if reviewed(row) and hand in HAND_VERDICTS else row.get("verdict")


def tripwired(row):
    """Suspect words in the diff, a contaminated session, or a diff that failed (so its suspect
    words were never read)."""
    return bool(row.get("suspect") or row.get("contaminated") or row.get("diff_error"))


def unresolved(row):
    """A row the bar can't count yet: its verdict is unresolved (and no hand_verdict replaced
    it), or a tripwire marked it (suspect, contaminated or diff_error) and no person has marked it
    reviewed."""
    return verdict_of(row) == "unresolved" or (tripwired(row) and not reviewed(row))


def counts_of(rows):
    """Rows per verdict; an unresolved row counts under "unresolved", never its verdict."""
    counts = {v: sum(verdict_of(r) == v and not unresolved(r) for r in rows) for v in VERDICTS if v != "unresolved"}
    counts["unresolved"] = sum(unresolved(r) for r in rows)
    return counts


def held_reason(row):
    """(why an unresolved row is held, what a person sets in its line to resolve it)."""
    why = []
    if verdict_of(row) == "unresolved":
        causes = [str(c.get("detail", "")) for c in row.get("checks") or []
                  if isinstance(c, dict) and str(c.get("name", "")).startswith("unresolved")]
        why.append("the oracle couldn't determine it" + (f" ({'; '.join(causes)[:300]})" if causes else ""))
    if tripwired(row) and not reviewed(row):
        if row.get("suspect"):
            why.append(f"suspect ({', '.join(row['suspect'])})")
        if row.get("contaminated"):
            why.append(f"contaminated ({', '.join(row['contaminated'])})")
        if row.get("diff_error"):
            why.append(f"the diff failed, so its suspect words weren't read ({str(row['diff_error'])[:200]})")
    todo = ('set "reviewed": true, "hand_verdict" ("pass", "fail" or "broken") and "hand_note" in its row once read'
            f" (--grade PATH {run_key(row)} VERDICT NOTE sets the three)"
            if verdict_of(row) == "unresolved" else 'set "reviewed": true in its row once read')
    return "; ".join(why), todo


def effort_of(row):
    return row.get("effort") or "default"


def plans(row, case, arm):
    """Whether the run that wrote `row` planned `case` and `arm`: its planned_cases and
    planned_arms, or, for a row from before they were recorded, its own case and arm. An
    imported row (--baseline) stands for its own line only: its run's other lines aren't here."""
    if row.get("imported"):
        return case == row.get("case") and arm == row.get("arm")
    cases, arms = row.get("planned_cases"), row.get("planned_arms")
    return (case == row.get("case") or case in (cases or ())) and (arm == row.get("arm") or arm in (arms or ()))


def planned_lines(rows):
    """(cases, arms) the rows' runs planned, in CASES and ARMS order: each row's own case and arm
    and its planned_cases and planned_arms, so a case or arm a run planned but never started
    (a Ctrl-C) is still listed. A row from before they were recorded adds its own only. These are
    the lines --summarize may show; which of them can miss with no row is summarize's call, per
    model, from the plans themselves (crossing these two unions would name lines no run planned)."""
    cases = [c for c in CASES if any(plans(r, c, r.get("arm")) for r in rows)]
    arms = [x for x in ARMS if any(plans(r, r.get("case"), x) for r in rows)]
    return cases, arms


READ_FROM = "read_from"  # the files load_rows found a row in: in memory only, never written back


def old_form_reach(rows):
    """The (case, arm) lines the rows that record no plan may gate. Such a row, from before
    planned_cases and planned_arms, says nothing of what its run left out, so the old rows of
    each file that holds it (READ_FROM, from load_rows; one group for rows without it) stand
    for that plan: the cross of the cases and arms they hold. A row that records its plan adds
    nothing (plans() covers it), nor does another model's (`rows` are one model's at one effort).
    Reaching past those would gate lines no run planned, as pooling an old arm-A file with newer
    runs of the same model did, in other files or in the same one."""
    by_file = {}
    for r in rows:
        if not (r.get("imported") or ("planned_cases" in r and "planned_arms" in r)):
            for path in r.get(READ_FROM) or (None,):
                by_file.setdefault(path, []).append(r)
    return {(r.get("case"), x.get("arm")) for old in by_file.values() for r in old for x in old}


def summarize(rows, cases, arms, n=None, named=True):
    """Prints the table and bar per model and effort; returns the missed "case/arm" labels. Rows
    carrying `imported` are arm-A rows from --baseline files: they count in A's line, marked
    there. A line's n is the largest of n, the rows it holds and the planned_n of the model's
    rows whose run planned that case and arm (plans(); a row without planned_n, from before it
    was recorded, adds nothing). A line that could miss and holds no row is a MISS when a run
    of its model planned it (plans()), when `named` (`cases` and `arms` are the plan: a live
    run's, or both --cases and --arms), or when a row of its model that records no plan reaches
    it (old_form_reach: the cross of the old rows its files hold). Any other empty line
    isn't shown: no run of that model planned it, so nothing was cut short."""
    missed, refused, held = [], [], []
    for model, effort in sorted({(r.get("model"), effort_of(r)) for r in rows}, key=str):
        print(f"\nmodel {model}, effort {effort}")
        of_model = [r for r in rows if r.get("model") == model and effort_of(r) == effort]
        reach = old_form_reach(of_model)
        versions = sorted({str(r["claude_code_version"]) for r in of_model if r.get("claude_code_version")})
        if len(versions) > 1:  # Claude Code can update itself mid-run, so this warns, not refuses
            print(f"warning: rows from {len(versions)} Claude Code versions ({', '.join(versions)}); pooled anyway")
        print(f"{'case':16} {'arm':3} {'pass':>4} {'fail':>4} {'brkn':>4} {'unrs':>4} {'err':>4} {'trig':>4} {'warm':>4} "
              f"{'cost $':>8}  bar")
        print("(unrs: unresolved, held out of every count until a person reviews it; err: harness or infra "
              "failures, outside every count; trig: the case turn triggered the case's skill; warm: arm D's "
              "warm-up turn triggered the skill of the case it ran)")
        for case in cases:
            a_rows = [r for r in of_model if r["case"] == case and r["arm"] == "A"]
            a_prints = pooled_prints(a_rows)
            shown = [arm for arm in ARMS if arm in arms or (arm == "A" and a_rows)]
            for arm in shown:
                mine = [r for r in of_model if r["case"] == case and r["arm"] == arm]
                if not mine and not (named or (case, arm) in reach or any(plans(r, case, arm) for r in of_model)):
                    continue  # pooled runs of other plans listed it; none of this model's planned it
                counts = counts_of(mine)
                prints = pooled_prints(mine)
                if len(prints) > 1:
                    differ = [part for part in FINGERPRINT_PARTS
                              if len({json.dumps(fp[part], sort_keys=True) for fp in prints}) > 1]
                    label, miss = f"REFUSED: rows from {len(prints)} versions ({', '.join(differ)} differ), not pooled", True
                    refused.append((f"{case}/{arm}", [(fp, sum(fingerprint(r) == fp for r in mine)) for fp in prints]))
                else:
                    skills = prints[0]["skills"] if prints else None
                    # A's counts classify this arm's case only when A pooled and ran the same case code.
                    same_case = len(a_prints) == 1 and (not prints or a_prints[0]["case"] == prints[0]["case"])
                    planned = max((r["planned_n"] for r in of_model
                                   if plans(r, case, arm) and is_count(r.get("planned_n"))), default=0)
                    label, miss = bar(case, arm, counts, max(n or 0, len(mine), planned),
                                      a=counts_of(a_rows) if a_rows and same_case else None,
                                      installed=list(skills) if skills is not None else None)
                held += [r for r in mine if unresolved(r)]
                imported = sum(bool(r.get("imported")) for r in mine)
                if imported:
                    label += f" [{imported} imported]"
                if miss and (arm in GATING or label.startswith("REFUSED")):
                    missed.append(f"{case}/{arm}")
                trig = sum(bool(r.get("triggered")) for r in mine)
                warm = sum(bool((r.get("triggered_turns") or {}).get("warmup")) for r in mine)
                cost = sum(r.get("total_cost_usd") or 0 for r in mine)
                print(f"{case:16} {arm:3} {counts['pass']:>4} {counts['fail']:>4} {counts['broken']:>4} "
                      f"{counts['unresolved']:>4} {counts['error']:>4} {trig:>4} {warm if arm == 'D' else '-':>4} "
                      f"{cost:>8.2f}  {label}")
    for label, versions in refused:
        print(f"refused to pool {label}: " + "; ".join(f"{short(fp)} x{k}" for fp, k in versions))
    for r in held:
        why, todo = held_reason(r)
        print(f"unresolved {r['case']}/{r['arm']} #{r.get('run')} ({r['verdict']}): {why}; diff {r.get('diff')}; {todo}")
    return missed


def results_path(given):
    """A results.jsonl, given as the file or the dir holding it."""
    path = Path(given)
    return (path / "results.jsonl" if path.is_dir() else path).resolve()


def is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def row_problem(row):
    """Why a parsed line isn't a row a summary can count, or None. Only the fields a summary
    reads to place and count a row are checked, and the ones a person edits by hand."""
    if not isinstance(row, dict):
        return "not a JSON object"
    if row.get("case") not in CASE_INFO:
        return f"unknown case {row.get('case')!r}"
    if row.get("arm") not in ARMS:
        return f"unknown arm {row.get('arm')!r}"
    if row.get("verdict") not in VERDICTS:
        return f"unknown verdict {row.get('verdict')!r}"
    if "hand_verdict" in row and row["hand_verdict"] not in HAND_VERDICTS:
        return f"hand_verdict {row['hand_verdict']!r} is not one of {', '.join(map(repr, HAND_VERDICTS))}"
    if "reviewed" in row and not isinstance(row["reviewed"], bool):
        return f"reviewed {row['reviewed']!r} is not true or false"
    if "planned_n" in row and not is_count(row["planned_n"]):
        return f"planned_n {row['planned_n']!r} is not a positive whole number"
    for field, known in (("planned_cases", CASES), ("planned_arms", ARMS)):
        if field in row and not (isinstance(row[field], list) and row[field]
                                 and all(isinstance(x, str) and x in known for x in row[field])):
            return f"{field} {str(row[field])[:80]} is not a non-empty list of known {field.split('_')[1]}"
    return None


def read_results(path, flag, given):
    """[(line number, row, problem)] for each non-empty line of the results file at `path`:
    the parsed row (None when it won't parse) and why it isn't a row (row_problem), or None.
    A file that can't be read exits."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        sys.exit(f"run.py: {flag} {given}: {e.strerror or e}")
    out = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, RecursionError) as e:
            out.append((number, None, f"not JSON ({str(e)[:80]})"))
            continue
        out.append((number, row, row_problem(row)))
    return out


def refuse_lines(flag, problems):
    """Exits naming each file:line that isn't a row: a line skipped silently could drop a hand
    verdict, or a row, from the bar."""
    if problems:
        sys.exit(f"run.py: {flag}: {len(problems)} line(s) aren't rows, so no bar is printed; fix or remove "
                 "them:\n" + "\n".join(f"  {path}:{number}: {why}" for path, number, why in problems))


def load_baseline(paths, model, cases, effort="default"):
    """Arm-A rows for `model`, `effort` (a row's own, "default" when it has none) and `cases`
    from earlier results.jsonl files (each path a file, or a results dir holding one), each
    marked `imported` with its file. A row already taken (the same stream paths: the same run,
    from a copied file, say) is dropped and counted. A file that can't be read exits, and so
    does a line that isn't a row (refuse_lines); a row of another arm, model, effort or case is
    skipped and counted."""
    rows, seen, seen_rows, problems = [], set(), set(), []
    for given in paths:
        path = results_path(given)
        if path in seen:
            continue
        seen.add(path)
        took = skipped = dups = 0
        for number, row, problem in read_results(path, "--baseline", given):
            if problem:
                problems.append((path, number, problem))
                continue
            if not (row.get("arm") == "A" and row.get("model") == model
                    and (row.get("effort") or "default") == effort
                    and row.get("case") in cases):
                skipped += 1
                continue
            key = json.dumps(row.get("stream") or row, sort_keys=True)  # a harness error's row has no stream
            if key in seen_rows:
                dups += 1
                continue
            seen_rows.add(key)
            rows.append({**row, "imported": str(path)})
            took += 1
        print(f"baseline {path}: {took} arm-A row(s) for {model} at effort {effort} in these cases; "
              f"{dups} already taken; {skipped} other row(s) skipped")
    refuse_lines("--baseline", problems)
    return rows


def load_rows(paths):
    """(rows, empty, live): every row of every arm in these results.jsonl files (each path a
    file, or a results dir holding one), tagged with the files that hold it (READ_FROM, in
    memory only), the files that hold no row (a run killed before its
    first row leaves one, and its plan is only in rows), and the files a live run is still
    writing (held_by_a_run). A row already taken (the same stream paths) is dropped and
    counted, and its file joins the taken row's tag: that file still holds the row, whatever
    the path order. A file that can't be read exits, and so does a
    non-empty line that isn't a row (refuse_lines), before any bar is printed."""
    rows, seen, taken, problems, empty, live = [], set(), {}, [], [], []
    for given in paths:
        path = results_path(given)
        if path in seen:
            continue
        seen.add(path)
        if held_by_a_run(path.parent):
            live.append(path)
        took = dups = 0
        for number, row, problem in read_results(path, "--summarize", given):
            if problem:
                problems.append((path, number, problem))
                continue
            key = json.dumps(row.get("stream") or row, sort_keys=True)
            if key in taken:
                dups += 1
                if str(path) not in taken[key][READ_FROM]:
                    taken[key][READ_FROM].append(str(path))
                continue
            taken[key] = {**row, READ_FROM: [str(path)]}  # summarize's old_form_reach; no reader writes rows back
            rows.append(taken[key])
            took += 1
        if not took + dups:
            empty.append(path)
        print(f"rows {path}: {took} row(s); {dups} already taken")
    refuse_lines("--summarize", problems)
    return rows, empty, live


LOCK_PAUSES = (0.05, 0.1, 0.15, 0.2, 0.25, 0.25)  # seconds between results_lock's tries, ~1 s in all


@contextlib.contextmanager
def results_lock(directory, refusal):
    """Holds an exclusive flock on the dir that holds a results.jsonl for the with block, or exits
    with `refusal` when another process holds it. The lock is on the dir, never the file:
    --grade replaces the file, so a lock on it would leave a run that opened it a moment before
    appending to the replaced inode. A run holds it for its whole life (open_results), --grade
    while it reads and replaces; it ends with the process, so a killed run leaves none behind.
    A --summarize probe (held_by_a_run) holds a shared flock for an instant, so a held lock is
    tried again, never waited on, LOCK_PAUSES apart before the refusal: a probe is gone by then,
    and a run's lock isn't."""
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)  # not inherited: subprocesses can't keep it
    try:
        for pause in (*LOCK_PAUSES, None):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if pause is None:
                    sys.exit(f"run.py: {refusal}")
                time.sleep(pause)
        yield
    finally:
        os.close(fd)


def held_by_a_run(directory):
    """Whether a live run (or a --grade) holds results_lock on `directory` now. It tries a shared
    flock without waiting and lets go at once, so it never blocks, and keeps a run from taking
    the dir for that instant only. A dir it can't open or flock reads as not held: the answer
    is a warning, and the summary goes on either way."""
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(fd)  # closing the only fd on it drops the flock
    return False


@contextlib.contextmanager
def open_results(out):
    """A live run's results.jsonl, open to append, under results_lock(out) for the run's whole
    life, so --grade refuses while the run can still add rows (a rewrite then would leave every
    later row in an unlinked file)."""
    with results_lock(out, f"{out} is held by another run or a --grade; use a new --out"):
        with open(out / "results.jsonl", "a") as results:
            yield results


def run_key(row):
    """A row's RUN key for --grade: <case>-<arm>-<run>, the name of its run dir."""
    return f"{row.get('case')}-{row.get('arm')}-{row.get('run')}"


def grade_row(given, key, verdict, note):
    """--grade: sets reviewed, hand_verdict and hand_note on the one row whose run_key is `key`
    in the results file at `given`, and rewrites the file atomically, every other line byte for
    byte. Refuses, changing nothing, an unknown or repeated key, a verdict outside
    HAND_VERDICTS, an empty note, a file with a line --summarize would refuse, and a file whose
    dir a live run holds (results_lock). Returns the exit code."""
    if verdict not in HAND_VERDICTS:
        sys.exit(f"run.py: --grade: verdict {verdict!r} is not one of {', '.join(HAND_VERDICTS)}")
    if not note.strip():
        sys.exit("run.py: --grade: the note is empty; say why in a sentence")
    path = results_path(given)
    if not path.parent.is_dir():
        sys.exit(f"run.py: --grade {given}: no such results file")
    refusal = (f"--grade: a live run holds {path.parent}; it appends to its results.jsonl until it ends, and a "
               "rewrite now would drop every row it writes after. Grade once it finishes.")
    with results_lock(path.parent, refusal):
        return _grade_row(path, given, key, verdict, note)


def _grade_row(path, given, key, verdict, note):
    rows = read_results(path, "--grade", given)
    refuse_lines("--grade", [(path, number, why) for number, _row, why in rows if why])
    found = [(number, row) for number, row, _why in rows if run_key(row) == key]
    if not found:
        known = ", ".join(sorted({run_key(row) for _n, row, _w in rows}))
        sys.exit(f"run.py: --grade: no row {key!r} in {path}; its runs: {known or 'none'}")
    if len(found) > 1:
        sys.exit(f"run.py: --grade: {len(found)} rows are {key!r} in {path} (lines "
                 f"{', '.join(str(n) for n, _ in found)}); fix the file by hand")
    [(number, row)] = found
    before = f"verdict {row['verdict']}" + (f", hand_verdict {row['hand_verdict']}" if "hand_verdict" in row else "")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    end = lines[number - 1][len(lines[number - 1].rstrip("\r\n")):]
    lines[number - 1] = json.dumps({**row, "reviewed": True, "hand_verdict": verdict, "hand_note": note}) + (end or "\n")
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".results-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(lines))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, path.stat().st_mode & 0o7777)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)
        raise
    print(f"graded {key} in {path} (line {number}): hand_verdict {verdict}, was {before}; "
          f"--summarize {path} prints the bar")
    return 0


def summarize_files(paths, cases=None, arms=None, n=None):
    """--summarize: the bar from earlier results files, no model calls. Returns the exit code."""
    rows, empty, live = load_rows(paths)
    planned_cases, planned_arms = planned_lines(rows)
    named = bool(cases and arms)  # both name the lines wanted; one alone filters what the runs planned
    cases, arms = cases or planned_cases, arms or planned_arms
    missed = summarize(rows, cases, arms, n, named=named)
    errors = sum(verdict_of(r) == "error" for r in rows if r["case"] in cases and r["arm"] in arms)
    print(f"\n{len(rows)} rows from {len(paths)} path(s); no model calls made")
    if errors:
        print(f"{errors} run(s) scored error (harness or infra, not the agent); see their checks")
    if missed:
        print("missed the bar: " + ", ".join(missed))
    for path in empty:
        print(f"no rows in {path}: an empty file, or a run that ended before its first row finished; "
              "its model and plan are missing from the bar")
    for path in live:
        print(f"warning: a run is still writing {path}: don't hand-edit it while the run lasts (an editor's "
              "save can drop the rows it appends); once the run ends, use --grade PATH RUN VERDICT NOTE")
    return 1 if missed or errors or empty else 0


# ---------------------------------------------------------------- main

def default_out():
    """A fresh 0700 results dir under the checkout's ignored .tmp/, not in /tmp next to the
    fixtures, where an agent's session could read earlier runs' oracle output."""
    return private_dir(time.strftime("%Y%m%d-%H%M%S-"))  # wall clock


def row_of(fut, case, arm, i):
    """A finished run's row; None for a run stopped by Ctrl-C before it finished. A harness
    exception scores the run error, never drops it."""
    try:
        return fut.result()
    except Interrupted:
        return None
    except Exception as e:
        log(f"  {case:16} {arm} #{i}: harness error {e!r}")
        return {"case": case, "arm": arm, "run": i, "verdict": "error",
                "checks": [{"name": "harness", "ok": False, "detail": repr(e)[:1000]}],
                "triggered": False, "total_cost_usd": None, "harness_error": repr(e),
                "owner": CASE_INFO[case].owner, "kind": CASE_INFO[case].kind}


def dry_run(cases, arms, args):
    failed = []
    for case in cases:
        for arm in arms:
            scratch = private_dir("dry-")  # the hook's dirs and the harness git dir, outside the fixture and /tmp
            registry = FakeRegistry(case, arm, scratch / "registry.log") if is_registry_case(case) else None
            with registry or contextlib.nullcontext():
                fixture, _sha = build_fixture(arm, scratch, case=case, registry=registry)
                ok, output = npm_test(fixture)
                print(f"\n[{case} / {arm}] fixture {fixture}: npm test {'ok' if ok else 'FAILED'}")
                if not ok:
                    failed.append(f"{case}/{arm}")
                    print(output[-3000:])
                if registry:
                    problem = registry_route_problem(fixture, case, registry)
                    print(f"  registry {registry.url}: {'route FAILED' if problem else 'npm install ok, stubs unchanged, npm test ok'}"
                          f" ({len(registry.requests)} requests; log {registry.log_path})")
                    print("    " + " ".join(f"{r['method']} {r['path']}" for r in registry.requests))
                    if problem:
                        failed.append(f"{case}/{arm}")
                        print(problem)
            for label, _prompt, cmd in turns_for(case, arm, args.model, args.effort):
                source = "/compact" if label == "compact" else str(CASES_DIR / (
                    warmup_case(case) if label == "warmup" else case) / "prompt.md")
                stdin = f"<<< {shlex.quote(source)}" if label == "compact" else f"< {shlex.quote(source)}"
                print(f"  ({label}) cd {shlex.quote(str(fixture))} && {shlex.join(cmd)} {stdin}")
            if not args.keep:
                remove_fixture(fixture)
                shutil.rmtree(scratch, ignore_errors=True)
    print("\ngrading sandbox: " + ("bwrap works here" if bwrap_usable() else
          "bwrap can't start here; a live run needs it (sandbox-off) or --unsafe-grade"))
    print(f"dry run: {len(cases) * len(arms) - len(set(failed))}/{len(cases) * len(arms)} fixtures built "
          "with npm test green; no model calls made")
    return 1 if failed else 0


def out_problem(out):
    """Why `out` can't take this run's results, or None: it already holds a results.jsonl, so a
    rerun into it would overwrite the run dirs earlier rows point at."""
    if out is not None and (Path(out) / "results.jsonl").exists():
        return (f"--out {out} already holds results.jsonl; reusing it would overwrite the run dirs its rows "
                "point at. Use a new dir (or leave --out off for a fresh one).")
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arms", help="comma list of " + ",".join(ARMS) + " (required but with --summarize)")
    ap.add_argument("--cases", help="comma list (default: all; with --summarize, what the rows planned): " + ",".join(CASES))
    ap.add_argument("-n", type=int, help="runs per case and arm (default 5; with --summarize, what the rows planned)")
    ap.add_argument("-j", type=int, default=2, help="sessions in parallel (default 2)")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"),
                    help="session effort (default: Claude Code's built-in default for the model)")
    ap.add_argument("--out", help="results dir (default: a new 0700 dir under the checkout's .tmp/practices/)")
    ap.add_argument("--keep", action="store_true", help="keep each run's fixture")
    ap.add_argument("--dry-run", action="store_true", help="build fixtures, run npm test, print commands")
    ap.add_argument("--unsafe-grade", action="store_true",
                    help="grade without bwrap when it can't start (runs agent code uncontained)")
    ap.add_argument("--baseline", action="append", default=[], metavar="PATH",
                    help="an earlier results.jsonl (or its dir) whose arm-A rows for the same model count "
                         "in this run's bar, marked imported (repeatable)")
    ap.add_argument("--summarize", nargs="+", metavar="PATH",
                    help="print the bar from earlier results.jsonl files (or their dirs), every arm's rows, "
                         "applying reviewed and hand_verdict; no model calls")
    ap.add_argument("--grade", nargs=4, metavar=("PATH", "RUN", "VERDICT", "NOTE"),
                    help="mark one row of a results.jsonl (or its dir) graded by hand: RUN is <case>-<arm>-<run> "
                         "(its run dir's name), VERDICT pass, fail or broken, NOTE why; rewrites the file atomically")
    a = ap.parse_args()
    if a.grade:
        if a.summarize or a.arms or a.cases or a.n is not None or a.dry_run or a.out or a.baseline:
            ap.error("--grade edits one row of a results file: it takes no other option")
        return grade_row(*a.grade)

    arms = [x.strip().upper() for x in (a.arms or "").split(",") if x.strip()]
    cases = [c.strip() for c in a.cases.split(",") if c.strip()] if a.cases else []
    bad = [x for x in arms if x not in ARMS] + [c for c in cases if c not in CASES]
    if bad:
        ap.error(f"unknown arm or case: {', '.join(bad)}")
    if a.summarize:
        if a.dry_run or a.out or a.baseline:
            ap.error("--summarize reads earlier results only: it takes no --dry-run, --out or --baseline")
        return summarize_files(a.summarize, cases, arms, a.n)
    if not arms:
        ap.error("--arms is required")
    cases = cases or CASES
    a.n = 5 if a.n is None else a.n
    problem = out_problem(a.out)
    if problem:
        sys.exit(f"run.py: {problem}")
    check_prereqs(arms)
    imported = load_baseline(a.baseline, a.model, cases, a.effort or "default")  # before any spend: a bad path exits here
    if a.dry_run:
        return dry_run(cases, arms, a)
    a.contain = grading_contained(a.unsafe_grade)
    if not shutil.which("claude"):
        sys.exit("run.py: claude is not on PATH")

    out = Path(a.out).resolve() if a.out else default_out()  # run dirs reach git, the hook and bwrap
    out.mkdir(parents=True, exist_ok=True)
    print(f"results: {out / 'results.jsonl'} (model {a.model}, effort {a.effort or 'default'})")
    jobs = [(case, arm, i) for case in cases for arm in arms for i in range(1, a.n + 1)]
    rows = []
    started = time.monotonic()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.j))
    with open_results(out) as results:
        futures = {pool.submit(run_one, case, arm, i, a, out): (case, arm, i) for case, arm, i in jobs}
        recorded = set()

        def record(fut):
            recorded.add(fut)
            row = row_of(fut, *futures[fut])
            if row is not None:
                row.setdefault("model", a.model)  # a harness error's row, for the per-model summary
                row.setdefault("effort", a.effort or "default")
                row.setdefault("planned_n", a.n)
                # so a summary lists a case or arm this run planned but never started (a Ctrl-C)
                row.setdefault("planned_cases", cases)
                row.setdefault("planned_arms", arms)
                rows.append(row)
                results.write(json.dumps(row) + "\n")  # each finished row is on disk at once
                results.flush()

        try:
            for fut in concurrent.futures.as_completed(futures):
                record(fut)
        except KeyboardInterrupt:
            # Queued runs never start; running turns and everything they started are killed
            # by marker; a run between turns stops at its next check. A grade in progress runs
            # in its own session, so the Ctrl-C doesn't reach it: it finishes and its row is kept.
            stop_all()
            pool.shutdown(wait=True, cancel_futures=True)
            for fut in futures:
                if fut not in recorded and fut.done() and not fut.cancelled():
                    record(fut)
            print(f"\nrun.py: interrupted; {len(rows)} of {len(jobs)} runs finished and are in "
                  f"{out / 'results.jsonl'}")
            return 130
    pool.shutdown(wait=True)
    missed = summarize(rows + imported, cases, arms, a.n)
    errors = sum(verdict_of(r) == "error" for r in rows)
    print(f"\n{len(rows)} runs in {time.monotonic() - started:.0f} s; results in {out}")
    if errors:
        print(f"{errors} run(s) scored error (harness or infra, not the agent); see their checks")
    if missed:
        print("missed the bar: " + ", ".join(missed))
    return 1 if missed or errors else 0


if __name__ == "__main__":
    sys.exit(main())
