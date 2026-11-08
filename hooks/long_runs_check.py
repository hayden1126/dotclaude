#!/usr/bin/env python3
"""PreToolUse(Bash): deny a heavy gate once until the long-runs skill is loaded.

Sessions skip that skill and plan long runs without it. A deny at the command is the one point
every such session passes, but a deny that fires in most sessions gets ignored. Replayed over
45 days of transcripts, the triggers below fire in 161 of 443 real sessions that ran a gate or a
PR command (.lane/artifacts/replay.py in the guards lane). It fires only on:

  - heavy gates, at first use: `lane trial`, `lane lock suite` or `gate`, and the repo's own
    list. Other locks count only when a repo lists them (`lane lock quiet`, say): every lock
    but install would have fired in 296 of 443 real sessions, and the lock name doesn't say
    whether the run is long;
  - a second DIFFERENT whole suite in a session, from the generic table below. A rerun never
    counts, nor does a narrowed run (one test file, `::`, a name filter).

The repo's list is `[long_runs] gates = [...]` in .claude/practices/config.toml: each entry is an
argv prefix, never a pattern, since a repo writes it. It can only add gates.

Deny once per session and compaction window: a resend passes, loaded or not. Skipped for a
subagent (it executes a run someone else planned), when the skill isn't installed, and under
`practices-gate off` (rule id LONG-RUNS).

A call the practices hook could also deny is left to it: when two hooks deny one Bash call,
Claude Code shows only the reason of the last to finish (2.1.319, measured), and several of that
hook's denies fire once, so losing one loses it for good. That is why a command that holds a git
commit or push, a gh pr ready or create, or a package install gets no deny here.

Fails open: an unreadable command, config, transcript or state file allows the call. State holds
hashes of the suites, never command text. The practices hook's parser and transcript readers are
imported, not copied, and FROM_PRACTICES names what a contract test pins. This hook lives in its
own file so that it stays out of the practices eval's hook fingerprint and its runs.
"""
import hashlib
import importlib.util
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
_spec = importlib.util.spec_from_file_location("practices_check",
                                               os.path.join(HERE, "practices_check.py"))
PC = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("practices_check", PC)
_spec.loader.exec_module(PC)

FROM_PRACTICES = ("ADD_VERBS", "Budget", "CMD_MAX", "CONFIG_MAX", "Transcripts", "bash_project",
                  "command_of", "config_home", "is_loaded", "is_off", "l1_window", "load_bash_words",
                  "load_config", "log", "names_a_call", "read_toml", "state_dir")

SKILL = "long-runs"
LOCKS = ("suite", "gate")
RULE_ID = "LONG-RUNS"
GATES_MAX = 50
GATE_LEN_MAX = 200
SOURCE_FILE = re.compile(r"\.(py|ts|tsx|js|jsx|mjs|cjs|rb|rs|go|java|kt)(:\d+)?$")
NOISE = {"-x", "-v", "-vv", "-vvv", "-q", "-qq", "-f", "-b", "--verbose", "--quiet", "--failfast",
         "--buffer", "--exitfirst", "--no-cov"}
NOISE_PREFIX = ("--tb=", "--maxfail=", "--color=", "--reporter=", "--durations=")
REASON = (
    "[long-runs] This command starts a heavy gate or a second test suite, and the long-runs "
    "skill isn't loaded in this context. Load it (the Skill tool, skill \"long-runs\"), work out "
    "what the change can reach and what can run at once, and say what won't run. Then resend; "
    "this check won't stop the resend.")


def narrowed(args, flags=()):
    """Whether a test runner's arguments pick out part of a suite."""
    for a in args:
        head = a.split("=", 1)[0]
        if head in flags or (a.startswith("-k") and not a.startswith("--") and len(a) > 2):
            return True
        if a in ("-k", "--keyword"):
            return True
        if not a.startswith("-") and ("::" in a or SOURCE_FILE.search(a)):
            return True
    return False


def unwrap(name, args):
    """(the runner, its arguments), through python -m, npx and exec; None when it isn't one."""
    if re.fullmatch(r"python[\d.]*", name):
        return (args[1], args[2:]) if len(args) > 1 and args[0] == "-m" else None
    if name in ("npx", "bunx"):
        rest = [a for a in args if not a.startswith("-")]
        return (rest[0], args[args.index(rest[0]) + 1:]) if rest else None
    if name in ("pnpm", "yarn", "bundle") and args[:1] == ["exec"] and len(args) > 1:
        return args[1], args[2:]
    return name, args


def suite_args(name, args):
    """The arguments of a whole-suite run by a known runner; None for any other command."""
    pair = unwrap(name, args)
    if pair is None:
        return None
    name, args = pair
    if name == "pytest" or name in ("tox", "nox", "rspec"):
        return None if narrowed(args) else args
    if name == "unittest":
        if not args or args[0] == "discover" or all(a.startswith("-") for a in args):
            return None if narrowed(args) else args
        return None  # a dotted name or a file
    if name in ("vitest", "jest"):
        rest = args[1:] if args[:1] in (["run"], ["watch"]) else args
        return None if narrowed(rest, ("-t", "--testNamePattern", "--grep")) else rest
    if name == "playwright" and args[:1] == ["test"]:
        return None if narrowed(args[1:], ("-g", "--grep")) else args[1:]
    if name in ("npm", "pnpm", "yarn", "bun"):
        if args[:1] in (["test"], ["t"]):
            rest = args[1:]
        elif args[:1] in (["run"], ["run-script"]) and len(args) > 1 and args[1].startswith("test"):
            rest = args[2:]
        else:
            return None
        return None if narrowed(rest, ("-t", "--grep", "--testNamePattern")) else rest
    if name == "cargo" and args[:1] == ["test"]:
        before = args[1:args.index("--")] if "--" in args else args[1:]
        return None if any(not a.startswith("-") for a in before) else args[1:]
    if name == "go" and args[:1] == ["test"]:
        return None if narrowed(args[1:], ("-run", "--run")) else args[1:]
    if name == "make" and ("test" in args or "check" in args):
        return args
    if name in ("gradle", "gradlew", "mvn") and "test" in args:
        return None if narrowed(args, ("--tests", "-Dtest")) else args
    return None


def suite_key(name, args, rest):
    """A hash naming the suite, the same across verbosity and fail-fast flags."""
    pair = unwrap(name, args)
    kept = [a for a in rest if a not in NOISE and not a.startswith(NOISE_PREFIX)]
    return hashlib.sha256(json.dumps([pair[0], kept]).encode()).hexdigest()[:32]


def is_heavy(name, args, gates):
    """Whether a simple command is a named heavy gate."""
    if name == "lane":
        if args[:1] == ["trial"]:
            return "--help" not in args
        if args[:1] == ["lock"] and "--" in args:
            lock, i, before = None, 0, args[1:args.index("--")]
            while i < len(before):
                if before[i] == "--wait":
                    i += 2
                    continue
                if not before[i].startswith("-"):
                    lock = before[i]
                    break
                i += 1
            if lock in LOCKS:
                return True
    return any(name == os.path.basename(g[0]) and args[:len(g) - 1] == g[1:] for g in gates)


def repo_gates(project):
    """The repo's own gates as argv lists; none on any fault (logged)."""
    if not project:
        return []
    path = os.path.join(project, ".claude", "practices", "config.toml")
    try:
        table = PC.read_toml(path, PC.CONFIG_MAX).get("long_runs")
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RecursionError) as e:
        PC.log("long-runs-config", f"{path}: {type(e).__name__}")
        return []
    if table is None:
        return []
    listed = table.get("gates") if isinstance(table, dict) else None
    if not isinstance(listed, list) or not all(isinstance(g, str) for g in listed):
        PC.log("long-runs-config", f"{path}: long_runs.gates isn't a list of strings")
        return []
    out = []
    for g in listed[:GATES_MAX]:
        try:
            words = shlex.split(g) if len(g) <= GATE_LEN_MAX else []
        except ValueError:
            words = []
        if words:
            out.append(words)
    return out


def may_be_denied_elsewhere(cmd, parsed):
    """Whether the practices hook could deny this call: see the module docstring."""
    if PC.names_a_call(cmd):
        return True
    return any(os.path.basename(w) in PC.ADD_VERBS and nxt in PC.ADD_VERBS[os.path.basename(w)]
               for words in parsed for w, nxt in zip(words, words[1:]))


def state_path(event):
    key = str(event.get("session_id"))
    return os.path.join(PC.state_dir(), "long-runs",
                        hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def read_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"suites": [], "told": []}
    return data if isinstance(data, dict) else {"suites": [], "told": []}


def write_state(path, data):
    """Whether the write held; a deny needs it, so that its resend can pass."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        return True
    except OSError as e:
        PC.log("long-runs-state", f"{type(e).__name__}")
        return False


def check(event):
    """The deny for this event, or None."""
    if (event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "Bash"
            or event.get("agent_id")):
        return None
    cmd = PC.command_of(event)
    if not cmd or len(cmd) > PC.CMD_MAX:
        return None
    bash_words = PC.load_bash_words()
    try:
        parsed = list(bash_words.segments(cmd))
        commands = [bash_words.command_words(words)[:2] for words in parsed]
    except (ValueError, IndexError, RecursionError):
        return None
    project = PC.bash_project(event)
    gates = repo_gates(project)
    suites = {suite_key(n, a, rest) for n, a in commands if n
              and (rest := suite_args(n, a)) is not None}
    heavy = any(n and is_heavy(n, a, gates) for n, a in commands)
    if not (heavy or suites) or may_be_denied_elsewhere(cmd, parsed):
        return None
    cfg = PC.load_config(project)
    skill_dir = os.path.join(PC.config_home(), "skills", SKILL)
    if not cfg["enabled"] or PC.is_off(cfg, {"name": SKILL}, RULE_ID) or not os.path.isdir(skill_dir):
        return None
    path, state = state_path(event), None
    state = read_state(path)
    seen = set(state.get("suites") or []) | suites
    if suites and not write_state(path, {**state, "suites": sorted(seen)}):
        return None
    if not (heavy or len(seen) >= 2):
        return None
    with PC.Transcripts(event) as ts:
        if ts.own is None:
            return None
        window, boundary = PC.l1_window(ts.own)
        if PC.is_loaded({"name": SKILL, "dir": skill_dir}, window.loads()):
            return None
    told = state.get("told") or []
    if boundary in told or not write_state(path, {"suites": sorted(seen), "told": [*told, boundary]}):
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": REASON}}


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, UnicodeDecodeError):
        return 0
    if not isinstance(event, dict):
        return 0
    try:
        out = check(event)
    except PC.Budget as e:
        PC.log("budget-spent", f"long-runs check: {e}; the call was allowed")
        out = None
    except Exception as e:  # noqa: BLE001 (a crash here must not stop the command)
        PC.log("long-runs-crash", type(e).__name__)
        out = None
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
