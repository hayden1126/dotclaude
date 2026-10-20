#!/usr/bin/env python3
"""Live practices eval: real `claude -p` sessions against planted-bug tasks, scored by hidden oracles.

  python3 tests/practices/run.py --arms A [--cases idor,mass-assign] [-n 5] [-j 2]
                                 [--model claude-opus-5-5] [--effort LEVEL] [--out DIR] [--keep] [--dry-run]
                                 [--unsafe-grade] [--baseline PATH ...]

Manual only, never in the suite: it makes model calls, and runs sandbox-off (the sandbox
hides the credential). `--dry-run` makes none: it builds one fixture per case and arm, runs
the fixture's visible `npm test`, and prints the claude command lines. The offline proof that
the oracles are right is test_oracles.py.

Skills and cases: PRACTICES_SKILLS names the practices skills, explicitly. Each case has an
owner (the skill whose bug class it plants) and a kind, target or benign (CASE_INFO). Each
owner has one benign case.

Arms:
  A  no skill, no hooks (the RED baseline: it should fail most runs of each target case)
  B  every PRACTICES_SKILLS skill, skills/<name>/, copied into the fixture's .claude/skills/;
     B, C and D refuse to start while one of them has no SKILL.md
  C  B plus the practices hook: every hook entry of the repo's settings.json (any event, any
     matcher) whose command runs practices-check.sh, with its path pointed at this checkout's
     hooks/practices-check.sh and any shell prefilter kept, so the eval runs what users get
  D  C, run as three turns on one session: the case owner's benign prompt (the hook makes it
     load the skill), then `/compact`, then the case prompt. It checks the skill survives
     compaction.

Cases (cases/<case>/): prompt.md is the user's message, fed verbatim on stdin. oracle.mjs
is hidden from the agent (it lives in this checkout, not the fixture) and prints one JSON
verdict: pass, fail (works but has the planted bug) or broken (the functional check failed or
the code didn't load, or the agent pointed node_modules outside the fixture; the run counts
for neither side). good/ and bad/ are overlays the offline test uses. oracle_lib.mjs holds the
shared rules. run.py adds a fourth verdict, error, for its own or the infrastructure's
failures: a harness exception, a turn with no stream output, a claude exit that is nonzero
with no result event, a result event with is_error or an error_* subtype (usage limit,
expired login), an arm D warm-up or compact turn that timed out, a fixture the grading
sandbox refuses. broken stays agent-caused.

Per run:
  - Fixture: fixture/ is copied to a fresh tempfile.mkdtemp(prefix="ledgerly-"), next_stub/
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
  - Record: one line per run in <out>/results.jsonl (case, owner and kind, verdict, checks,
    triggered and triggered_turns, turns, duration, cost, is_error, init memory_paths and
    init_skills, `skills`, hook denials, strays, the harness SHA, and the paths of the saved
    streams, oracle output and diff under <out>/<case>-<arm>-<i>/). `skills` is the
    fingerprint of what was installed, {name: sha256 over its files' sorted relative paths
    and bytes}, taken before the session starts, so an uncommitted edit counts; arm A's is {}.
    (Rows before 2026-10-20 have no fingerprint, and their "skills" is the init list.) <out>
    defaults to a fresh 0700 dir under the
    checkout's ignored .tmp/practices/, away from the fixtures in /tmp. The diff is taken with
    --binary; ignored paths (node_modules, data/) aren't in it, so regrading a diff needs the
    stubs as installed. A turn triggered when it has a Skill tool_use naming the case's
    owner, or a Read of a path ending <owner>/SKILL.md. `triggered` and
    `hook_denials` are the case turn's; arm D's other turns are reported apart
    (triggered_turns, hook_denials_turns, and the summary's warm column).
  - Baseline: each --baseline PATH (a results.jsonl, or the dir holding one) adds its arm-A
    rows for the same model and these cases to the summary, marked "[k imported]" on A's line,
    so a B, C or D run can reuse earlier RED rows. They aren't copied into this run's file.

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
  Pooling: the rows of one model, case and arm must share one skills fingerprint (error rows
     aside); otherwise the line reads REFUSED and the distinct fingerprints are listed.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
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
PRACTICES_SKILLS = ["server-code", "auth-secrets"]
HOOK = REPO / "hooks" / "practices-check.sh"
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
    "auth-benign": Case("auth-secrets", BENIGN),
}
CASES = list(CASE_INFO)


def benign_case(owner):
    """The benign case `owner` owns: arm D's warm-up prompt for every case of that owner."""
    (case,) = [c for c, info in CASE_INFO.items() if info == Case(owner, BENIGN)]
    return case


ARMS = ["A", "B", "C", "D"]
# pass, fail and broken come from the oracle; error is the harness's own (an exception, a
# claude exit with no result, no stream, a sandbox refusal), counted apart and never valid.
VERDICTS = ("pass", "fail", "broken", "error")
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


def hook_settings(settings=None, hook=None):
    """The practices hook's wiring for arms C and D, taken from the repo's settings.json, so the
    eval runs what users get: every hook entry, under any event and matcher, whose command runs
    practices-check.sh, with the script's path pointed at this checkout's copy. The rest of the
    command (a shell prefilter that skips the hook, say) and the entry's other keys (timeout)
    stay as written. A matcher group keeps only its practices hooks; one with none is dropped."""
    hook = shlex.quote(str(hook or HOOK))
    wiring = {}
    for event, groups in (json.loads(Path(settings or REPO_SETTINGS).read_text()).get("hooks") or {}).items():
        for group in groups or []:
            kept = [{**h, "command": HOOK_PATH.sub(lambda _m: hook, h["command"])}
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


def build_fixture(arm):
    """A fresh fixture for one run: the app, the stub packages, an initial commit, then the
    arm's harness config as a second commit. Returns (path, the harness commit's SHA)."""
    root = Path(tempfile.mkdtemp(prefix="ledgerly-"))
    shutil.copytree(FIXTURE_SRC, root, dirs_exist_ok=True)
    install_stubs(root)
    git("init", "-q", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "-qm", "Initial commit", cwd=root)

    settings = {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}}
    if arm in ("B", "C", "D"):
        for name in PRACTICES_SKILLS:
            shutil.copytree(SKILLS_DIR / name, root / ".claude" / "skills" / name)
    if arm in ("C", "D"):
        settings["hooks"] = hook_settings()
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    git("add", "-A", ".claude", cwd=root)
    git("commit", "-qm", "Local Claude Code settings", cwd=root)
    return root, git("rev-parse", "HEAD", cwd=root).strip()


def npm_test(root):
    p = subprocess.run(["npm", "test"], cwd=root, capture_output=True, text=True, errors="replace", timeout=300)
    return p.returncode == 0, p.stdout + p.stderr


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
        ("warmup", prompt_of(benign_case(CASE_INFO[case].owner)), claude_cmd(model, ["--session-id", sid], effort)),
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


def triggered(events, skill):
    """Whether a turn loaded `skill` (the case's owner): a Skill call naming it, or a Read of its
    SKILL.md."""
    for use in tool_uses(events):
        inp = use.get("input") or {}
        if use.get("name") == "Skill" and skill in json.dumps(inp):
            return True
        if use.get("name") == "Read" and str(inp.get("file_path", "")).endswith(f"{skill}/SKILL.md"):
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
    $HOME). Returns the verdict dict; a missing verdict line or a timeout scores broken, a
    node_modules the agent pointed outside the fixture scores broken untouched, and a fixture
    the sandbox refuses (a writable path under $HOME) scores error."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    problem = node_modules_problem(fixture)
    if problem:
        (run_dir / "oracle.out").write_text(f"not graded: {problem}\n")
        return {"verdict": "broken", "checks": [{"name": "node_modules replaced", "ok": False, "detail": problem}]}
    install_stubs(fixture)  # the agent could have edited node_modules/next
    scratch = Path(tempfile.mkdtemp(prefix="practices-grade-"))
    try:
        env = grade_env(fixture, scratch)
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


def agent_diff(fixture, base):
    """Everything the agent changed since the harness commit `base`, committed or not."""
    git("add", "-A", cwd=fixture)
    return git("diff", "--cached", "--binary", base, cwd=fixture)


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


def finish_run(fixture, harness_sha, case, run_dir, contain, skip_grade=()):
    """Saves the agent's diff, then grades (unless `skip_grade` lists infra failures, which
    score error). The diff is taken before grading touches the fixture (the stub reinstall, any
    files the agent's code writes); a failed diff is recorded and never costs the verdict.
    Returns (verdict dict, diff error or None)."""
    run_dir = Path(run_dir)
    diff_error = None
    try:
        (run_dir / "diff.patch").write_text(agent_diff(fixture, harness_sha))
    except (subprocess.CalledProcessError, OSError) as e:
        diff_error = f"{e!r}: {getattr(e, 'stderr', '')}"[:1000]
    if skip_grade:
        return {"verdict": "error", "checks": [{"name": "harness", "ok": False,
                                                "detail": "; ".join(skip_grade)}]}, diff_error
    return grade(fixture, case, run_dir, contain=contain), diff_error


def run_one(case, arm, index, args, out):
    run_dir = out / f"{case}-{arm}-{index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    fixture, harness_sha = build_fixture(arm)
    skills = installed_skills(fixture)  # before the session, which could edit its copy
    streams, labels, exits, timed_out, stray_kills = [], [], [], False, []
    turns = turns_for(case, arm, args.model, args.effort)
    for n, (label, prompt, cmd) in enumerate(turns, 1):
        if STOP.is_set():
            raise Interrupted()
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
    verdict, diff_error = finish_run(fixture, harness_sha, case, run_dir, args.contain, skip_grade=failures)
    diff = run_dir / "diff.patch"

    per_turn = [stream_summary(turn) for turn in events_by_turn]
    summary = dict(per_turn[0])  # init facts (memory_paths, skills) from the first turn
    summary["result_subtype"] = per_turn[-1]["result_subtype"]
    for key in ("turns", "duration_ms", "total_cost_usd"):
        values = [t[key] for t in per_turn if isinstance(t[key], (int, float))]
        summary[key] = sum(values) if values else None
    owner = CASE_INFO[case].owner
    triggered_turns = {label: triggered(turn, owner) for label, turn in zip(labels, events_by_turn)}
    denials_turns = {label: hook_denials(turn) for label, turn in zip(labels, events_by_turn)}
    row = {
        "case": case, "arm": arm, "run": index, "owner": owner, "kind": CASE_INFO[case].kind,
        "model": args.model, "effort": args.effort or "default",
        "effort_seen": transcript_efforts(events_by_turn),
        "verdict": verdict["verdict"], "checks": verdict.get("checks", []),
        # the case turn's figures; arm D's warm-up and compact turns are reported apart
        "triggered": triggered_turns.get("task", False),
        "triggered_turns": triggered_turns,
        **summary,
        "skills": skills,  # {name: tree_hash} installed; the summary pools only equal ones
        "hook_denials": denials_turns.get("task", 0),
        "hook_denials_turns": denials_turns,
        "is_error": any(result_failed(result_event(turn)) for turn in events_by_turn),
        "exit_codes": exits, "timed_out": timed_out,
        "strays": len(stray_kills), "stray_kills": stray_kills,
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
    owner, kind = CASE_INFO[case]
    p, f, b = counts["pass"], counts["fail"], counts["broken"]
    if arm == "A":
        if kind == BENIGN:
            return "reported only", False
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
    if kind == BENIGN:
        ok = p == n and b == 0
        return ("green" if ok else f"MISS (pass {p} of {n}, broken {b})"), not ok
    ok = p == n
    label = "green" if ok else f"MISS (pass {p} of {n})"
    cls = a_class(a)
    if cls == "no-harm":
        label += "; no-harm check, not evidence that the skill helps"
    elif cls == "unclassified":
        label += "; arm A unclassified, not yet evidence that the skill helps"
    return label, not ok


def fingerprint(row):
    """The skills a row ran with, {name: tree_hash}: {} for arm A, which installs none (rows from
    before fingerprints included). None for a B, C or D row that didn't record it."""
    if row.get("arm") == "A":
        return {}
    skills = row.get("skills")
    return skills if isinstance(skills, dict) else None


def short(fp):
    if fp is None:
        return "unrecorded"
    return "{" + ", ".join(f"{k} {v[:12]}" for k, v in sorted(fp.items())) + "}" if fp else "{}"


def counts_of(rows):
    return {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS}


def summarize(rows, cases, arms, n):
    """Prints the table and bar per model; returns the missed "case/arm" labels. Rows carrying
    `imported` are arm-A rows from --baseline files: they count in A's line, marked there."""
    missed, refused = [], []
    for model in sorted({r.get("model") for r in rows}, key=str):
        print(f"\nmodel {model}")
        print(f"{'case':16} {'arm':3} {'pass':>4} {'fail':>4} {'brkn':>4} {'err':>4} {'trig':>4} {'warm':>4} "
              f"{'cost $':>8}  bar")
        print("(err: harness or infra failures, outside every count; trig: the case turn triggered the "
              "case's skill; warm: arm D's warm-up turn did)")
        of_model = [r for r in rows if r.get("model") == model]
        for case in cases:
            a_rows = [r for r in of_model if r["case"] == case and r["arm"] == "A"]
            shown = [arm for arm in ARMS if arm in arms or (arm == "A" and a_rows)]
            for arm in shown:
                mine = [r for r in of_model if r["case"] == case and r["arm"] == arm]
                counts = counts_of(mine)
                prints = []
                for r in mine:
                    fp = fingerprint(r)
                    if r["verdict"] != "error" and fp not in prints:
                        prints.append(fp)
                if len(prints) > 1:
                    label, miss = f"REFUSED: rows from {len(prints)} skill versions, not pooled", True
                    refused.append((f"{case}/{arm}", [(fp, sum(fingerprint(r) == fp for r in mine)) for fp in prints]))
                else:
                    installed = list(prints[0]) if prints and prints[0] is not None else None
                    label, miss = bar(case, arm, counts, n, a=counts_of(a_rows) if a_rows else None,
                                      installed=installed)
                imported = sum(bool(r.get("imported")) for r in mine)
                if imported:
                    label += f" [{imported} imported]"
                if miss and (arm in GATING or label.startswith("REFUSED")):
                    missed.append(f"{case}/{arm}")
                trig = sum(bool(r.get("triggered")) for r in mine)
                warm = sum(bool((r.get("triggered_turns") or {}).get("warmup")) for r in mine)
                cost = sum(r.get("total_cost_usd") or 0 for r in mine)
                print(f"{case:16} {arm:3} {counts['pass']:>4} {counts['fail']:>4} {counts['broken']:>4} "
                      f"{counts['error']:>4} {trig:>4} {warm if arm == 'D' else '-':>4} {cost:>8.2f}  {label}")
    for label, versions in refused:
        print(f"refused to pool {label}: " + "; ".join(f"{short(fp)} x{k}" for fp, k in versions))
    return missed


def load_baseline(paths, model, cases):
    """Arm-A rows for `model` and `cases` from earlier results.jsonl files (each path a file, or
    a results dir holding one), each marked `imported` with its file. A file that can't be read
    exits; a line that isn't a row is skipped and counted."""
    rows, seen = [], set()
    for given in paths:
        path = Path(given)
        path = (path / "results.jsonl" if path.is_dir() else path).resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError as e:
            sys.exit(f"run.py: --baseline {given}: {e.strerror or e}")
        took = skipped = 0
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            if not (isinstance(row, dict) and row.get("arm") == "A" and row.get("model") == model
                    and row.get("case") in cases and row.get("verdict") in VERDICTS):
                skipped += bool(line.strip())
                continue
            rows.append({**row, "imported": str(path)})
            took += 1
        print(f"baseline {path}: {took} arm-A row(s) for {model} in these cases; {skipped} other line(s) skipped")
    return rows


# ---------------------------------------------------------------- main

def default_out():
    """A fresh 0700 results dir under the checkout's ignored .tmp/, not in /tmp next to the
    fixtures, where an agent's session could read earlier runs' oracle output."""
    base = REPO / ".tmp" / "practices"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=base))  # wall clock


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
            fixture, _sha = build_fixture(arm)
            ok, output = npm_test(fixture)
            print(f"\n[{case} / {arm}] fixture {fixture}: npm test {'ok' if ok else 'FAILED'}")
            if not ok:
                failed.append(f"{case}/{arm}")
                print(output[-3000:])
            for label, _prompt, cmd in turns_for(case, arm, args.model, args.effort):
                source = "/compact" if label == "compact" else str(CASES_DIR / (
                    benign_case(CASE_INFO[case].owner) if label == "warmup" else case) / "prompt.md")
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
    a = ap.parse_args()

    arms = [x.strip().upper() for x in a.arms.split(",") if x.strip()]
    cases = [c.strip() for c in a.cases.split(",") if c.strip()] if a.cases else CASES
    bad = [x for x in arms if x not in ARMS] + [c for c in cases if c not in CASES]
    if bad:
        ap.error(f"unknown arm or case: {', '.join(bad)}")
    check_prereqs(arms)
    imported = load_baseline(a.baseline, a.model, cases)  # before any spend: a bad path exits here
    if a.dry_run:
        return dry_run(cases, arms, a)
    a.contain = grading_contained(a.unsafe_grade)
    if not shutil.which("claude"):
        sys.exit("run.py: claude is not on PATH")

    out = Path(a.out) if a.out else default_out()
    out.mkdir(parents=True, exist_ok=True)
    print(f"results: {out / 'results.jsonl'} (model {a.model}, effort {a.effort or 'default'})")
    jobs = [(case, arm, i) for case in cases for arm in arms for i in range(1, a.n + 1)]
    rows = []
    started = time.monotonic()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.j))
    with open(out / "results.jsonl", "a") as results:
        futures = {pool.submit(run_one, case, arm, i, a, out): (case, arm, i) for case, arm, i in jobs}
        recorded = set()

        def record(fut):
            recorded.add(fut)
            row = row_of(fut, *futures[fut])
            if row is not None:
                row.setdefault("model", a.model)  # a harness error's row, for the per-model summary
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
    errors = sum(r["verdict"] == "error" for r in rows)
    print(f"\n{len(rows)} runs in {time.monotonic() - started:.0f} s; results in {out}")
    if errors:
        print(f"{errors} run(s) scored error (harness or infra, not the agent); see their checks")
    if missed:
        print("missed the bar: " + ", ".join(missed))
    return 1 if missed or errors else 0


if __name__ == "__main__":
    sys.exit(main())
