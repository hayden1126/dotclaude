#!/usr/bin/env python3
"""Live server-code eval: real `claude -p` sessions against planted-bug tasks, scored by hidden oracles.

  python3 tests/practices/run.py --arms A [--cases idor,mass-assign] [-n 5] [-j 2]
                                 [--model claude-opus-5-5] [--out DIR] [--keep] [--dry-run]
                                 [--unsafe-grade]

Manual only, never in the suite: it makes model calls, and runs sandbox-off (the sandbox
hides the credential). `--dry-run` makes none: it builds one fixture per case and arm, runs
the fixture's visible `npm test`, and prints the claude command lines. The offline proof that
the oracles are right is test_oracles.py.

Arms:
  A  no skill, no hooks (the RED baseline: it should fail most runs of each case)
  B  skills/server-code/ copied into the fixture's .claude/skills/
  C  B plus hooks/practices-check.sh wired by absolute path (PreToolUse and SessionStart)
  D  C, run as three turns on one session: the benign prompt (the hook makes it load the
     skill), then `/compact`, then the case prompt. It checks the skill survives compaction.

Cases (cases/<case>/): prompt.md is the user's message, fed verbatim on stdin. oracle.mjs
is hidden from the agent (it lives in this checkout, not the fixture) and prints one JSON
verdict: pass, fail (works but has the planted bug) or broken (the functional check failed or
the code didn't load; the run counts for neither side). good/ and bad/ are overlays the
offline test uses. oracle_lib.mjs holds the shared rules.

Per run:
  - Fixture: fixture/ is copied to a fresh tempfile.mkdtemp(prefix="practices-"), next_stub/
    to its node_modules/next, then `git init` and an initial commit. The harness config is a
    second commit, so `git diff HEAD` after the session is exactly the agent's change:
    .claude/settings.json turns the sandbox on with autoAllowBashIfSandboxed (the agent's Bash
    runs confined to the fixture, without prompts), plus the skill and hooks for its arm.
  - Session: `claude -p --output-format stream-json --verbose --model M --setting-sources
    project,local --strict-mcp-config --permission-mode acceptEdits --max-turns 60`, cwd the
    fixture, 900 s timeout per turn, env passed through unchanged. project,local drops every
    user-tier skill, plugin, agent and CLAUDE.md; --strict-mcp-config drops the claude.ai
    connectors that load in some runs and not others (spike.md section 1).
  - Grade: only after the process exits (a background agent may still be writing), run the
    oracle under the pristine checkout's loader (fixture/scripts/register.mjs here), never the
    copy the agent could edit, with a 60 s timeout. The oracle runs agent-written code, so it
    runs under bwrap: the filesystem read-only, $HOME an empty read-only tmpfs (no credential
    file visible), this checkout's tests/practices bound back read-only, the fixture and the
    run dir writable, no network, its own pid namespace. Its env is an allowlist: PATH, HOME,
    LANG, FIXTURE, DB_PATH and TMPDIR (both inside the run dir) and a dummy LLM_API_KEY.
    Without a usable bwrap, run.py refuses to start unless --unsafe-grade is passed.
  - Record: one line per run in <out>/results.jsonl (verdict, checks, triggered, turns,
    duration, cost, init memory_paths and skills, hook denials, and the paths of the saved
    stream, oracle output and diff under <out>/<case>-<arm>-<i>/). `triggered` is any Skill
    tool_use naming server-code, or a Read of a path ending server-code/SKILL.md.

Pass bar, per case and arm (printed after the table; exit nonzero when a gating arm misses):
  A  "discriminates": at least 3 valid (non-broken) runs, and fail >= 3 of them. benign has
     no security check, so A on benign is reported only.
  C, D  "green": pass == n (on benign too: over-restriction scores broken).
  B  reported only.
"""
import argparse
import concurrent.futures
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURE_SRC = HERE / "fixture"
STUB_SRC = HERE / "next_stub"
CASES_DIR = HERE / "cases"
LOADER = FIXTURE_SRC / "scripts" / "register.mjs"
SKILL_SRC = REPO / "skills" / "server-code"
HOOK = REPO / "hooks" / "practices-check.sh"
HOOK_TIMEOUT = 5  # seconds; the hook keeps its own budget under this (spike.md section 3)

CASES = ["idor", "mass-assign", "actor-from-body", "action-authz", "rate-limit-paid", "benign"]
ARMS = ["A", "B", "C", "D"]
GATING = {"A", "C", "D"}
SESSION_TIMEOUT = 900
ORACLE_TIMEOUT = 60
# Hermetic git in the fixture: no user identity, signing or global ignore rules leak in.
GIT = ["git", "-c", "user.name=Ledgerly Dev", "-c", "user.email=dev@example.com",
       "-c", "commit.gpgsign=false", "-c", "core.excludesFile=/dev/null", "-c", "init.defaultBranch=main"]

_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def git(*args, cwd):
    return subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


# ---------------------------------------------------------------- fixture

def check_prereqs(arms):
    """Fail early and clearly when an arm needs a piece that doesn't exist yet."""
    problems = []
    if set(arms) & {"B", "C", "D"} and not (SKILL_SRC / "SKILL.md").is_file():
        problems.append(f"arms B, C and D need {SKILL_SRC}/SKILL.md, which doesn't exist yet")
    if set(arms) & {"C", "D"} and not HOOK.is_file():
        problems.append(f"arms C and D need {HOOK}, which doesn't exist yet")
    if problems:
        sys.exit("run.py: " + "; ".join(problems))


def hook_settings():
    """The practices hook's wiring for arms C and D. Kept in one place, so the hook's real
    interface (events, matchers, timeout) can change it later."""
    entry = lambda matcher: {"matcher": matcher, "hooks": [
        {"type": "command", "command": shlex.quote(str(HOOK)), "timeout": HOOK_TIMEOUT}]}
    return {"PreToolUse": [entry("Edit|Write|MultiEdit|Bash")], "SessionStart": [entry("compact")]}


def build_fixture(arm):
    """A fresh fixture for one run: the app, the next stub, an initial commit, then the arm's
    harness config as a second commit. Returns its path."""
    root = Path(tempfile.mkdtemp(prefix="practices-"))
    shutil.copytree(FIXTURE_SRC, root, dirs_exist_ok=True)
    shutil.copytree(STUB_SRC, root / "node_modules" / "next")
    git("init", "-q", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "-qm", "Initial commit", cwd=root)

    settings = {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}}
    if arm in ("B", "C", "D"):
        shutil.copytree(SKILL_SRC, root / ".claude" / "skills" / "server-code")
    if arm in ("C", "D"):
        settings["hooks"] = hook_settings()
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    git("add", "-A", "-f", ".claude", cwd=root)
    git("commit", "-qm", "Local Claude Code settings", cwd=root)
    return root


def npm_test(root):
    p = subprocess.run(["npm", "test"], cwd=root, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, p.stdout + p.stderr


# ---------------------------------------------------------------- session

def claude_cmd(model, extra=()):
    return ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
            "--setting-sources", "project,local", "--strict-mcp-config",
            "--permission-mode", "acceptEdits", "--max-turns", "60", *extra]


def prompt_of(case):
    return (CASES_DIR / case / "prompt.md").read_text()


def turns_for(case, arm, model):
    """[(label, prompt text, command)] for one run."""
    if arm != "D":
        return [("task", prompt_of(case), claude_cmd(model))]
    sid = str(uuid.uuid4())
    return [
        ("warmup", prompt_of("benign"), claude_cmd(model, ["--session-id", sid])),
        ("compact", "/compact", claude_cmd(model, ["--resume", sid])),
        ("task", prompt_of(case), claude_cmd(model, ["--resume", sid])),
    ]


def read_stream(path):
    events = []
    try:
        with open(path) as f:
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


def triggered(events):
    for use in tool_uses(events):
        inp = use.get("input") or {}
        if use.get("name") == "Skill" and "server-code" in json.dumps(inp):
            return True
        if use.get("name") == "Read" and str(inp.get("file_path", "")).endswith("server-code/SKILL.md"):
            return True
    return False


def hook_denials(events):
    """Hook denials seen in the stream. Heuristic, kept in one function to tune against the
    real hook: hook_response events carrying a deny or block decision; failing those, tool
    results whose text says a hook denied or blocked the call."""
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
                text = json.dumps(item.get("content", "")).lower()
                if "hook" in text and ("denied" in text or "blocked" in text):
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
        "skills": init.get("skills"),
    }


# ---------------------------------------------------------------- grading

BWRAP = shutil.which("bwrap")
BWRAP_BASE = ["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
              "--unshare-net", "--unshare-pid", "--die-with-parent", "--new-session"]
DUMMY_LLM_KEY = "sk-test-0000000000000000"  # agent code may refuse to run without a key


def bwrap_usable():
    """Whether bwrap can start here. It can't nested inside Claude Code's own sandbox."""
    if not BWRAP:
        return False
    try:
        p = subprocess.run([BWRAP, *BWRAP_BASE, "true"], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def contained(cmd, home, writable, readable=(), cwd=None):
    """`cmd` under bwrap: the filesystem read-only, `home` an empty read-only tmpfs (so no
    credential file under it is visible or writable), `readable` bound back read-only and
    `writable` read-write, no network, its own pid namespace. Order matters: a later bind
    overlays an earlier one, and the home remount comes after the binds that need mount points
    in it."""
    args = [BWRAP, *BWRAP_BASE, "--tmpfs", str(home)]
    node = os.path.realpath(shutil.which("node") or "/usr/bin/node")
    if node.startswith(str(home).rstrip("/") + "/"):  # e.g. an nvm install under $HOME
        prefix = os.path.dirname(os.path.dirname(node))
        args += ["--ro-bind", prefix, prefix]
    for p in readable:
        args += ["--ro-bind", str(p), str(p)]
    for p in writable:
        args += ["--bind", str(p), str(p)]
    args += ["--remount-ro", str(home)]
    if cwd:
        args += ["--chdir", str(cwd)]
    return [*args, "--", *cmd]


def grade_env(fixture, run_dir):
    """The oracle's whole environment: an allowlist, nothing inherited beyond it."""
    tmp = Path(run_dir) / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/nonexistent"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "FIXTURE": str(fixture),
        "DB_PATH": str(Path(run_dir) / "oracle.db"),
        "TMPDIR": str(tmp),
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


def grade(fixture, case, run_dir, contain=True):
    """Runs the case's oracle against the fixture, under bwrap unless `contain` is False.
    Returns its verdict dict; a missing verdict line or a timeout scores broken."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    db = run_dir / "oracle.db"
    if db.exists():
        db.unlink()
    env = grade_env(fixture, run_dir)
    cmd = ["node", "--import", LOADER.as_uri(), str(CASES_DIR / case / "oracle.mjs")]
    if contain:
        cmd = contained(cmd, home=env["HOME"], writable=[fixture, run_dir], readable=[HERE], cwd=fixture)
    try:
        p = subprocess.run(cmd, cwd=fixture, env=env, capture_output=True, text=True, timeout=ORACLE_TIMEOUT)
        stdout, stderr = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = f"oracle timed out after {ORACLE_TIMEOUT} s"
    (run_dir / "oracle.out").write_text(stdout + "\n--- stderr ---\n" + stderr)
    for line in reversed(stdout.splitlines()):
        if line.startswith('{"verdict"'):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"verdict": "broken", "checks": [{"name": "oracle output", "ok": False, "detail": stderr[-1500:]}]}


def agent_diff(fixture):
    git("add", "-A", cwd=fixture)
    return git("diff", "--cached", "HEAD", cwd=fixture)


# ---------------------------------------------------------------- one run

def run_one(case, arm, index, args, out):
    run_dir = out / f"{case}-{arm}-{index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    fixture = build_fixture(arm)
    streams, events, exits, timed_out = [], [], [], False
    turns = turns_for(case, arm, args.model)
    for n, (label, prompt, cmd) in enumerate(turns, 1):
        stream = run_dir / ("stream.jsonl" if len(turns) == 1 else f"stream-{n}-{label}.jsonl")
        streams.append(str(stream))
        with open(stream, "w") as f:
            try:
                p = subprocess.run(cmd, input=prompt, cwd=fixture, env=os.environ.copy(), stdout=f,
                                   stderr=subprocess.PIPE, text=True, timeout=SESSION_TIMEOUT)
                exits.append(p.returncode)
                if p.stderr:
                    (run_dir / f"stderr-{n}.txt").write_text(p.stderr)
            except subprocess.TimeoutExpired:
                exits.append(None)
                timed_out = True
        events.extend(read_stream(stream))
        if timed_out:
            break

    verdict = grade(fixture, case, run_dir, contain=args.contain)
    diff = run_dir / "diff.patch"
    diff.write_text(agent_diff(fixture))
    per_turn = [stream_summary(read_stream(s)) for s in streams]
    summary = dict(per_turn[0])  # init facts (memory_paths, skills) from the first turn
    summary["result_subtype"] = per_turn[-1]["result_subtype"]
    for key in ("turns", "duration_ms", "total_cost_usd"):
        values = [t[key] for t in per_turn if isinstance(t[key], (int, float))]
        summary[key] = sum(values) if values else None
    row = {
        "case": case, "arm": arm, "run": index,
        "verdict": verdict["verdict"], "checks": verdict.get("checks", []),
        "triggered": triggered(events),
        **summary,
        "hook_denials": hook_denials(events),
        "exit_codes": exits, "timed_out": timed_out,
        "stream": streams, "oracle": str(run_dir / "oracle.out"), "diff": str(diff),
    }
    if args.keep:
        row["fixture"] = str(fixture)
    else:
        shutil.rmtree(fixture, ignore_errors=True)
    log(f"  {case:16} {arm} #{index}: {row['verdict']:7} triggered={row['triggered']} "
        f"cost={row['total_cost_usd']}")
    return row


# ---------------------------------------------------------------- summary

def bar(case, arm, counts, n):
    """(label, missed) for one case and arm against the pass bar."""
    p, f, b = counts["pass"], counts["fail"], counts["broken"]
    if arm == "A" and case != "benign":
        valid = p + f
        ok = valid >= 3 and f >= 3
        return ("discriminates" if ok else f"MISS (fail {f} of {valid} valid)"), not ok
    if arm in ("C", "D"):
        ok = p == n
        return ("green" if ok else f"MISS (pass {p} of {n})"), not ok
    return "reported only", False


def summarize(rows, cases, arms, n):
    print(f"\n{'case':16} {'arm':3} {'pass':>4} {'fail':>4} {'brkn':>4} {'trig':>4} {'cost $':>8}  bar")
    missed = []
    for case in cases:
        for arm in arms:
            mine = [r for r in rows if r["case"] == case and r["arm"] == arm]
            counts = {v: sum(r["verdict"] == v for r in mine) for v in ("pass", "fail", "broken")}
            trig = sum(bool(r["triggered"]) for r in mine)
            cost = sum(r["total_cost_usd"] or 0 for r in mine)
            label, miss = bar(case, arm, counts, n)
            if miss and arm in GATING:
                missed.append(f"{case}/{arm}")
            print(f"{case:16} {arm:3} {counts['pass']:>4} {counts['fail']:>4} {counts['broken']:>4} "
                  f"{trig:>4} {cost:>8.2f}  {label}")
    return missed


# ---------------------------------------------------------------- main

def dry_run(cases, arms, args):
    failed = []
    for case in cases:
        for arm in arms:
            fixture = build_fixture(arm)
            ok, output = npm_test(fixture)
            print(f"\n[{case} / {arm}] fixture {fixture}: npm test {'ok' if ok else 'FAILED'}")
            if not ok:
                failed.append(f"{case}/{arm}")
                print(output[-3000:])
            for label, _prompt, cmd in turns_for(case, arm, args.model):
                source = "/compact" if label == "compact" else str(CASES_DIR / (
                    "benign" if label == "warmup" else case) / "prompt.md")
                stdin = f"<<< {shlex.quote(source)}" if label == "compact" else f"< {shlex.quote(source)}"
                print(f"  ({label}) cd {shlex.quote(str(fixture))} && {shlex.join(cmd)} {stdin}")
            if not args.keep:
                shutil.rmtree(fixture, ignore_errors=True)
    print("\ngrading sandbox: " + ("bwrap works here" if bwrap_usable() else
          "bwrap can't start here; a live run needs it (sandbox-off) or --unsafe-grade"))
    print(f"dry run: {len(cases) * len(arms) - len(failed)}/{len(cases) * len(arms)} fixtures built "
          "with npm test green; no model calls made")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arms", required=True, help="comma list of " + ",".join(ARMS))
    ap.add_argument("--cases", help="comma list (default: all): " + ",".join(CASES))
    ap.add_argument("-n", type=int, default=5, help="runs per case and arm (default 5)")
    ap.add_argument("-j", type=int, default=2, help="sessions in parallel (default 2)")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--out", help="results dir (default: a new practices-out-* temp dir)")
    ap.add_argument("--keep", action="store_true", help="keep each run's fixture")
    ap.add_argument("--dry-run", action="store_true", help="build fixtures, run npm test, print commands")
    ap.add_argument("--unsafe-grade", action="store_true",
                    help="grade without bwrap when it can't start (runs agent code uncontained)")
    a = ap.parse_args()

    arms = [x.strip().upper() for x in a.arms.split(",") if x.strip()]
    cases = [c.strip() for c in a.cases.split(",") if c.strip()] if a.cases else CASES
    bad = [x for x in arms if x not in ARMS] + [c for c in cases if c not in CASES]
    if bad:
        ap.error(f"unknown arm or case: {', '.join(bad)}")
    check_prereqs(arms)
    if a.dry_run:
        return dry_run(cases, arms, a)
    a.contain = grading_contained(a.unsafe_grade)
    if not shutil.which("claude"):
        sys.exit("run.py: claude is not on PATH")

    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="practices-out-"))
    out.mkdir(parents=True, exist_ok=True)
    print(f"results: {out / 'results.jsonl'}")
    jobs = [(case, arm, i) for case in cases for arm in arms for i in range(1, a.n + 1)]
    rows, write_lock = [], threading.Lock()
    started = time.monotonic()
    with open(out / "results.jsonl", "a") as results, \
            concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.j)) as pool:
        futures = {pool.submit(run_one, case, arm, i, a, out): (case, arm, i) for case, arm, i in jobs}
        for fut in concurrent.futures.as_completed(futures):
            case, arm, i = futures[fut]
            try:
                row = fut.result()
            except Exception as e:  # a harness error scores the run broken, never silently drops it
                row = {"case": case, "arm": arm, "run": i, "verdict": "broken", "checks": [],
                       "triggered": False, "total_cost_usd": None, "harness_error": repr(e)}
                log(f"  {case:16} {arm} #{i}: harness error {e!r}")
            rows.append(row)
            with write_lock:
                results.write(json.dumps(row) + "\n")
                results.flush()
    missed = summarize(rows, cases, arms, a.n)
    print(f"\n{len(rows)} runs in {time.monotonic() - started:.0f} s; results in {out}")
    if missed:
        print("missed the bar: " + ", ".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
