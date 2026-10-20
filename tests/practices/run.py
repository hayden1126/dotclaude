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
    to its node_modules/next and stubs/* (server-only, client-only, react) beside it, then
    `git init` and an initial commit. The harness config is a second commit whose SHA is
    recorded, and the agent's diff is taken against it (so an agent commit isn't lost):
    .claude/settings.json turns the sandbox on with autoAllowBashIfSandboxed (the agent's Bash
    runs confined to the fixture, without prompts), plus the skill and hooks for its arm. The
    harness's git reads no global or system config, so no global ignore rule hides .claude/.
  - Session: `claude -p --output-format stream-json --verbose --model M --setting-sources
    project,local --strict-mcp-config --permission-mode acceptEdits --max-turns 60`, cwd the
    fixture, 900 s timeout per turn, env passed through unchanged. project,local drops every
    user-tier skill, plugin, agent and CLAUDE.md; --strict-mcp-config drops the claude.ai
    connectors that load in some runs and not others (spike.md section 1). Each turn runs in
    its own process group with stdin, stdout and stderr on files, and PRACTICES_RUN=<uuid> in
    its env. When it exits, or times out, the whole group is killed, then any process of this
    uid still carrying that marker (one that called setsid; counted as `strays`), so nothing
    the session started holds the run open or writes while the oracle grades. The marker is
    the only proof of origin used: never a name, cwd or start time.
  - Ctrl-C: queued runs never start, running turns are killed with everything they started
    (by marker), finished rows are already in results.jsonl, and run.py exits 130.
  - Grade: only after the process exits (a background agent may still be writing), run the
    oracle under the pristine checkout's loader (fixture/scripts/register.mjs here), never the
    copy the agent could edit, with a 60 s timeout. The oracle runs agent-written code, so it
    runs under bwrap, built from an allowlist: /usr, /etc and the /bin, /sbin, /lib* dirs
    read-only (merged-/usr symlinks recreated), a fresh /proc, /dev and /tmp, this checkout's
    tests/practices read-only at /practices, and the fixture and a fresh scratch dir in the
    system temp dir writable. No /home, /run, /mnt, /var or /root exist inside, so no
    credential file, Unix socket (tmux, docker, Claude Code's own) or Windows drive is
    reachable; no network; its own pid namespace. A writable path under $HOME is refused. Its
    env is an allowlist: PATH, HOME, LANG, FIXTURE, DB_PATH, TMPDIR (HOME, DB_PATH and TMPDIR
    in the scratch dir, removed after grading) and a dummy LLM_API_KEY. The run dir may sit
    under $HOME; run.py writes the oracle's output there itself, outside bwrap.
    Without a usable bwrap, run.py refuses to start unless --unsafe-grade is passed.
  - Record: one line per run in <out>/results.jsonl (verdict, checks, triggered and
    triggered_turns, turns, duration, cost, init memory_paths and skills, hook denials, the
    harness SHA, and the paths of the saved streams, oracle output and diff under
    <out>/<case>-<arm>-<i>/). A turn triggered when it has a Skill tool_use naming
    server-code, or a Read of a path ending server-code/SKILL.md. `triggered` is the case
    turn's; arm D's warm-up turn is reported apart (triggered_turns, and the summary's warm
    column).

Pass bar, per case and arm (printed after the table; exit nonzero when a gating arm misses):
  A  "discriminates": at least 3 valid (non-broken) runs, and fail on more than half of them
     (fail * 2 > valid). benign has no security check, so A on benign is reported only.
  C, D  "green": pass == n (on benign too: over-restriction scores broken).
  B  reported only.
"""
import argparse
import concurrent.futures
import json
import os
import shlex
import shutil
import signal
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
STUBS_SRC = HERE / "stubs"  # server-only, client-only, react
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
# The harness's own git in a fixture reads no global or system config (so no signing, hooks or
# global ignore rules: .claude/settings.json stays visible); identity is set per command.
GIT = ["git", "-c", "user.name=Ledgerly Dev", "-c", "user.email=dev@example.com", "-c", "init.defaultBranch=main"]

_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def git_env():
    # XDG_CONFIG_HOME too: with core.excludesFile unset, git falls back to
    # $XDG_CONFIG_HOME/git/ignore (else ~/.config/git/ignore) whatever GIT_CONFIG_GLOBAL says.
    return dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", XDG_CONFIG_HOME=os.devnull)


def git(*args, cwd):
    return subprocess.run([*GIT, *args], cwd=cwd, env=git_env(), capture_output=True, text=True,
                          check=True).stdout


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


def stub_packages():
    """{package name: source dir} for every stub installed into a fixture's node_modules."""
    pkgs = {"next": STUB_SRC}
    pkgs.update({d.name: d for d in sorted(STUBS_SRC.iterdir()) if (d / "package.json").is_file()})
    return pkgs


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


def build_fixture(arm):
    """A fresh fixture for one run: the app, the stub packages, an initial commit, then the
    arm's harness config as a second commit. Returns (path, the harness commit's SHA)."""
    root = Path(tempfile.mkdtemp(prefix="practices-"))
    shutil.copytree(FIXTURE_SRC, root, dirs_exist_ok=True)
    install_stubs(root)
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
    git("add", "-A", ".claude", cwd=root)
    git("commit", "-qm", "Local Claude Code settings", cwd=root)
    return root, git("rev-parse", "HEAD", cwd=root).strip()


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
BWRAP_FLAGS = ["--unshare-net", "--unshare-pid", "--die-with-parent", "--new-session"]
# The only host dirs the oracle sees, read-only. No /home, /run, /mnt, /var or /root: a
# read-only mount doesn't stop connect() on a Unix socket (tmux, docker, Claude Code's own),
# and /mnt holds the Windows drives on WSL.
SYSTEM_DIRS = ["/usr", "/etc", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32"]
PRACTICES_MOUNT = "/practices"  # where this checkout's tests/practices appears inside
DUMMY_LLM_KEY = "sk-test-0000000000000000"  # agent code may refuse to run without a key


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


def grade_env(fixture, scratch):
    """The oracle's whole environment: an allowlist, nothing inherited beyond it. HOME, DB_PATH
    and TMPDIR live in `scratch`, the oracle's only writable dir besides the fixture."""
    scratch = Path(scratch)
    for d in ("home", "tmp"):
        (scratch / d).mkdir(parents=True, exist_ok=True)
    return {
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


def grade(fixture, case, run_dir, contain=True, home=None):
    """Runs the case's oracle against the fixture, under bwrap unless `contain` is False.
    The oracle writes only to the fixture and a fresh scratch dir (HOME, DB_PATH, TMPDIR) in
    the system temp dir, removed afterwards; run_dir may sit under $HOME, so run.py writes the
    oracle's output there itself, outside bwrap. `home` is the real home kept out (default
    $HOME). Returns the verdict dict; a missing verdict line or a timeout scores broken."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    install_stubs(fixture)  # the agent could have edited node_modules/next
    scratch = Path(tempfile.mkdtemp(prefix="practices-grade-"))
    try:
        env = grade_env(fixture, scratch)
        if contain:
            inside = Path(PRACTICES_MOUNT)
            cmd = contained(
                [node_binary(), "--import", (inside / LOADER.relative_to(HERE)).as_uri(),
                 str(inside / "cases" / case / "oracle.mjs")],
                writable=[fixture, scratch], readable={HERE: PRACTICES_MOUNT}, cwd=fixture, real_home=home)
        else:
            cmd = [node_binary(), "--import", LOADER.as_uri(), str(CASES_DIR / case / "oracle.mjs")]
        try:
            p = subprocess.run(cmd, cwd=fixture, env=env, capture_output=True, text=True, timeout=ORACLE_TIMEOUT)
            stdout, stderr = p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
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


def agent_diff(fixture, base):
    """Everything the agent changed since the harness commit `base`, committed or not."""
    git("add", "-A", cwd=fixture)
    return git("diff", "--cached", base, cwd=fixture)


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


def kill_marked(marker, grace=2.0):
    """SIGTERM every process carrying the marker, then SIGKILL any still carrying it after
    `grace` seconds (re-scanned, so a reused pid without the marker is never hit). Returns how
    many were found."""
    found = marked_processes(marker)
    for pid in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + grace
    while found and time.monotonic() < deadline and marked_processes(marker):
        time.sleep(0.1)
    for pid in marked_processes(marker):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return len(found)


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
    Returns (exit code or None, timed out, strays killed by marker)."""
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

def run_one(case, arm, index, args, out):
    run_dir = out / f"{case}-{arm}-{index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    fixture, harness_sha = build_fixture(arm)
    streams, labels, exits, timed_out, strays = [], [], [], False, 0
    turns = turns_for(case, arm, args.model)
    for n, (label, prompt, cmd) in enumerate(turns, 1):
        if STOP.is_set():
            raise Interrupted()
        suffix = "" if len(turns) == 1 else f"-{n}-{label}"
        stream = run_dir / f"stream{suffix}.jsonl"
        prompt_file = run_dir / f"prompt{suffix}.txt"
        prompt_file.write_text(prompt)
        streams.append(str(stream))
        labels.append(label)
        code, timed_out, turn_strays = run_turn(cmd, prompt_file, fixture, stream,
                                                run_dir / f"stderr{suffix}.txt", SESSION_TIMEOUT)
        exits.append(code)
        strays += turn_strays
        if timed_out:
            break
    if STOP.is_set():
        raise Interrupted()

    # The agent's change, taken before grading touches the fixture (the stub reinstall, any
    # files the agent's code writes). A failed diff is recorded and never costs the verdict.
    diff = run_dir / "diff.patch"
    diff_error = None
    try:
        diff.write_text(agent_diff(fixture, harness_sha))
    except (subprocess.CalledProcessError, OSError) as e:
        diff_error = f"{e!r}: {getattr(e, 'stderr', '')}"[:1000]
    verdict = grade(fixture, case, run_dir, contain=args.contain)

    events_by_turn = [read_stream(s) for s in streams]
    events = [e for turn in events_by_turn for e in turn]
    per_turn = [stream_summary(turn) for turn in events_by_turn]
    summary = dict(per_turn[0])  # init facts (memory_paths, skills) from the first turn
    summary["result_subtype"] = per_turn[-1]["result_subtype"]
    for key in ("turns", "duration_ms", "total_cost_usd"):
        values = [t[key] for t in per_turn if isinstance(t[key], (int, float))]
        summary[key] = sum(values) if values else None
    triggered_turns = {label: triggered(turn) for label, turn in zip(labels, events_by_turn)}
    row = {
        "case": case, "arm": arm, "run": index,
        "verdict": verdict["verdict"], "checks": verdict.get("checks", []),
        # the case turn's trigger; arm D's warm-up turn is reported apart in triggered_turns
        "triggered": triggered_turns.get("task", False),
        "triggered_turns": triggered_turns,
        **summary,
        "hook_denials": hook_denials(events),
        "exit_codes": exits, "timed_out": timed_out, "strays": strays,
        "harness_sha": harness_sha,
        "stream": streams, "oracle": str(run_dir / "oracle.out"), "diff": str(diff),
    }
    if diff_error:
        row["diff_error"] = diff_error
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
        ok = valid >= 3 and f * 2 > valid
        return ("discriminates" if ok else f"MISS (fail {f} of {valid} valid)"), not ok
    if arm in ("C", "D"):
        ok = p == n
        return ("green" if ok else f"MISS (pass {p} of {n})"), not ok
    return "reported only", False


def summarize(rows, cases, arms, n):
    print(f"\n{'case':16} {'arm':3} {'pass':>4} {'fail':>4} {'brkn':>4} {'trig':>4} {'warm':>4} "
          f"{'cost $':>8}  bar")
    print("(trig: the case turn triggered the skill; warm: arm D's warm-up turn did)")
    missed = []
    for case in cases:
        for arm in arms:
            mine = [r for r in rows if r["case"] == case and r["arm"] == arm]
            counts = {v: sum(r["verdict"] == v for r in mine) for v in ("pass", "fail", "broken")}
            trig = sum(bool(r["triggered"]) for r in mine)
            warm = sum(bool((r.get("triggered_turns") or {}).get("warmup")) for r in mine)
            cost = sum(r["total_cost_usd"] or 0 for r in mine)
            label, miss = bar(case, arm, counts, n)
            if miss and arm in GATING:
                missed.append(f"{case}/{arm}")
            print(f"{case:16} {arm:3} {counts['pass']:>4} {counts['fail']:>4} {counts['broken']:>4} "
                  f"{trig:>4} {warm if arm == 'D' else '-':>4} {cost:>8.2f}  {label}")
    return missed


# ---------------------------------------------------------------- main

def dry_run(cases, arms, args):
    failed = []
    for case in cases:
        for arm in arms:
            fixture, _sha = build_fixture(arm)
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
    rows = []
    started = time.monotonic()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.j))
    with open(out / "results.jsonl", "a") as results:
        futures = {pool.submit(run_one, case, arm, i, a, out): (case, arm, i) for case, arm, i in jobs}
        try:
            for fut in concurrent.futures.as_completed(futures):
                case, arm, i = futures[fut]
                try:
                    row = fut.result()
                except Interrupted:
                    continue
                except Exception as e:  # a harness error scores the run broken, never silently drops it
                    row = {"case": case, "arm": arm, "run": i, "verdict": "broken", "checks": [],
                           "triggered": False, "total_cost_usd": None, "harness_error": repr(e)}
                    log(f"  {case:16} {arm} #{i}: harness error {e!r}")
                rows.append(row)
                results.write(json.dumps(row) + "\n")  # each finished row is on disk at once
                results.flush()
        except KeyboardInterrupt:
            # Queued runs never start; running turns and everything they started are killed
            # by marker; a run between turns or grading stops at its next check.
            stop_all()
            pool.shutdown(wait=True, cancel_futures=True)
            print(f"\nrun.py: interrupted; {len(rows)} of {len(jobs)} runs finished and are in "
                  f"{out / 'results.jsonl'}")
            return 130
    pool.shutdown(wait=True)
    missed = summarize(rows, cases, arms, a.n)
    print(f"\n{len(rows)} runs in {time.monotonic() - started:.0f} s; results in {out}")
    if missed:
        print("missed the bar: " + ", ".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
