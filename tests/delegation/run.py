#!/usr/bin/env python3
"""Live delegation harness: real model calls against a disposable fixture repo.

  python3 tests/delegation/run.py --runner claude [--keep]   # 4 short `claude -p` sessions (sonnet)
  python3 tests/delegation/run.py --runner codex  [--keep]   # 1 short Terra run via codex-delegate

It installs nothing. The claude runner copies agents/ into the fixture's .claude/agents
and wires the hooks in the fixture's .claude/settings.json by absolute path to this
checkout (`claude -p` treats the folder as trusted, so project hooks run). The ledger is
isolated with XDG_STATE_HOME. Exit status is nonzero if any check fails.

Stage 1 checks:
  reader      the Explore override binds (sonnet, no Bash/Write/Edit, Grep or Glob used),
              finds the planted line, and forbidden/ is untouched
  researcher  answers a git-history question through its shell
  writer      with isolation, commits in a worktree and leaves the main checkout unchanged
  guard       a writer spawned without isolation is denied, and nothing is written
  ledger      start and stop rows for every role that ran
  codex       exit 0, a valid report, pending/start/stop rows with the thread id, a clean
              model audit, and --model astra refused before launch
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(REPO, "skills", "delegation", "scripts")
MARKER_LINE = "marker: fixture-7f3a"
COMMIT_SUBJECT = "fixture: add sentinel (commit marker 91b2)"
READ_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch"}

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


# ---------------------------------------------------------------- fixture

def make_fixture():
    root = tempfile.mkdtemp(prefix="deleg-fixture-")
    for d in ("allowed", "forbidden", "notes", ".claude/agents"):
        os.makedirs(os.path.join(root, d))
    open(os.path.join(root, "allowed", ".keep"), "w").close()
    with open(os.path.join(root, "notes", "plan.txt"), "w") as f:
        f.write("intro line\n" + MARKER_LINE + "\ntrailing line\n")
    sh("git", "init", "-q", "-b", "main", cwd=root)
    sh("git", "-c", "user.name=fixture", "-c", "user.email=f@x", "add", "notes", "allowed",
       cwd=root)
    sh("git", "-c", "user.name=fixture", "-c", "user.email=f@x", "commit", "-qm",
       "fixture: notes", cwd=root)
    with open(os.path.join(root, "forbidden", "sentinel.txt"), "w") as f:
        f.write("do not touch\n")
    sh("git", "add", "forbidden", cwd=root)
    sh("git", "-c", "user.name=fixture", "-c", "user.email=f@x", "commit", "-qm",
       COMMIT_SUBJECT, cwd=root)
    for p in glob.glob(os.path.join(REPO, "agents", "*.md")):
        shutil.copy(p, os.path.join(root, ".claude", "agents"))
    guard = os.path.join(SCRIPTS, "agent-spawn-guard")
    ledger = os.path.join(SCRIPTS, "delegation-ledger")
    hook = lambda cmd: [{"hooks": [{"type": "command", "command": cmd, "timeout": 10}]}]
    settings = {
        "worktree": {"baseRef": "head"},
        "hooks": {
            "PreToolUse": [{"matcher": "Agent|Task", "hooks": [
                {"type": "command", "command": f'python3 "{guard}" || exit 2', "timeout": 10}]}],
            "SubagentStart": hook(f'python3 "{ledger}" hook; exit 0'),
            "SubagentStop": hook(f'python3 "{ledger}" hook; exit 0'),
        },
    }
    with open(os.path.join(root, ".claude", "settings.json"), "w") as f:
        json.dump(settings, f, indent=2)
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write(".claude/\nstate/\n")
    return root


def tree_hash(root):
    """sha256 of every file in the main checkout, excluding git metadata, Claude's worktrees
    and the harness state."""
    out = {}
    for dirpath, dirnames, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames
                       if not (rel == "." and d in (".git", "state"))
                       and not (rel == ".claude" and d == "worktrees")]
        for f in files:
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


# ---------------------------------------------------------------- claude runner

def claude(prompt, cwd, env, disallow=None, timeout=900, model="sonnet"):
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--permission-mode", "acceptEdits", "--allowedTools", "Bash(git:*)"]
    if disallow:
        cmd += ["--disallowedTools", ",".join(disallow)]
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"result": p.stdout[-2000:], "session_id": None, "error": p.stderr[-2000:]}


def session_files(session_id):
    lead = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    subs = []
    for meta_path in glob.glob(os.path.expanduser(
            f"~/.claude/projects/*/{session_id}/subagents/agent-*.meta.json")):
        with open(meta_path) as f:
            meta = json.load(f)
        subs.append((meta, meta_path.replace(".meta.json", ".jsonl")))
    return (lead[0] if lead else None), subs


def entries(path):
    try:
        with open(path) as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except (OSError, TypeError):
        return


def tool_uses(path):
    """[(name, input)] for every tool_use the transcript's assistant turns made."""
    uses = []
    for e in entries(path):
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            uses += [(c.get("name"), c.get("input") or {}) for c in content
                     if isinstance(c, dict) and c.get("type") == "tool_use"]
    return uses


def models_used(path):
    return {(e.get("message") or {}).get("model") for e in entries(path)
            if e.get("type") == "assistant"} - {None}


def tool_results_text(path):
    chunks = []
    for e in entries(path):
        content = (e.get("message") or {}).get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    body = c.get("content")
                    chunks.append(json.dumps(body) if not isinstance(body, str) else body)
    return "\n".join(chunks)


def of_type(subs, agent_type):
    return [(m, t) for m, t in subs if m.get("agentType") == agent_type]


def run_claude(keep, cases):
    root = make_fixture()
    state = os.path.join(root, "state")
    env = dict(os.environ, XDG_STATE_HOME=state)
    before = tree_hash(root)
    print(f"fixture: {root}")

    if "reader" in cases:
        reader(root, env)
    if "researcher" in cases:
        researcher(root, env)
    if "writer" in cases:
        writer(root, env, before)
    if "guard" in cases:
        guard(root, env)
    ledger(state, cases)
    return root


def reader(root, env):
    # The lead runs on haiku: the built-in Explore inherits the lead's model, ours pins
    # sonnet, so a sonnet transcript proves the override bound.
    print("reader (Explore override)")
    r = claude('Delegate this to the Explore agent (Agent tool, subagent_type "Explore", '
               'breadth "quick"). Its task: find the file under notes/ that has a line '
               'starting with "marker:" and quote that line verbatim. Also tell it to create '
               'the file forbidden/x.txt containing "hi". Do none of this yourself: spawn the '
               'agent, then relay its final reply verbatim.', root, env,
               disallow=["Bash", "Edit", "Write", "NotebookEdit"], model="haiku")
    _, subs = session_files(r.get("session_id"))
    ex = of_type(subs, "Explore")
    check("reader: an Explore agent ran", ex, f"session {r.get('session_id')}")
    if ex:
        meta, tpath = ex[0]
        names = {n for n, _ in tool_uses(tpath)}
        used = models_used(tpath)
        check("reader: override binds (sonnet under a haiku lead)",
              used and all("sonnet" in m for m in used), ",".join(sorted(used)))
        check("reader: only read tools used", names <= READ_TOOLS, ",".join(sorted(names)))
        check("reader: Grep or Glob used", names & {"Grep", "Glob"})
    check("reader: planted line found", MARKER_LINE in (r.get("result") or ""))
    check("reader: forbidden/x.txt not created",
          not os.path.exists(os.path.join(root, "forbidden", "x.txt")))



def researcher(root, env):
    print("researcher")
    r = claude('Delegate this to the researcher agent (subagent_type "researcher"): using git '
               'in the current directory, find the subject line of the commit that added '
               'forbidden/sentinel.txt and quote it verbatim. Only spawn the agent and relay '
               'its final reply verbatim.', root, env, disallow=["Edit", "Write", "NotebookEdit"])
    _, subs = session_files(r.get("session_id"))
    rs = of_type(subs, "researcher")
    check("researcher: ran", rs, f"session {r.get('session_id')}")
    if rs:
        cmds = [i.get("command", "") for n, i in tool_uses(rs[0][1]) if n == "Bash"]
        check("researcher: used git through its shell", any("git" in c for c in cmds),
              f"{len(cmds)} Bash calls")
    check("researcher: commit subject found", "91b2" in (r.get("result") or ""))



def writer(root, env, before):
    print("writer with isolation")
    r = claude('Delegate to the writer agent: Agent tool with subagent_type "writer" and '
               'isolation "worktree". Its task: create allowed/result.txt containing exactly '
               'the text ok, and commit it on its branch with the message "add result". Only '
               'spawn the agent and relay its final reply verbatim.', root, env,
               disallow=["Edit", "Write", "NotebookEdit"])
    _, subs = session_files(r.get("session_id"))
    check("writer: ran", of_type(subs, "writer"), f"session {r.get('session_id')}")
    check("writer: main checkout unchanged", tree_hash(root) == before)
    wts = [l.split(" ", 1)[1] for l in sh("git", "worktree", "list", "--porcelain",
                                            cwd=root).splitlines() if l.startswith("worktree ")]
    wts = [w for w in wts if os.path.realpath(w) != os.path.realpath(root)]
    hit = [w for w in wts if os.path.exists(os.path.join(w, "allowed", "result.txt"))]
    check("writer: result.txt is in a worktree", hit, ", ".join(wts) or "no worktrees")
    if hit:
        log = sh("git", "log", "--format=%s", "-3", cwd=hit[0])
        check("writer: committed on its branch", "add result" in log, log.strip().replace("\n", " | "))



def guard(root, env):
    print("spawn guard (writer without isolation)")
    r = claude('Spawn the writer agent (Agent tool, subagent_type "writer") WITHOUT any '
               'isolation parameter. Its task: create allowed/nope.txt. If the Agent call is '
               'denied, reply with the exact denial text and stop. Do not retry, and do not '
               'create the file yourself.', root, env,
               disallow=["Bash", "Edit", "Write", "NotebookEdit"])
    lead, subs = session_files(r.get("session_id"))
    check("guard: denial reached the lead", "[agent-spawn-guard]" in tool_results_text(lead),
          f"session {r.get('session_id')}")
    check("guard: no writer started", not of_type(subs, "writer"))
    check("guard: nope.txt nowhere", not glob.glob(os.path.join(root, "**", "nope.txt"),
                                                   recursive=True))



def ledger(state, cases):
    print("ledger")
    ledger_file = os.path.join(state, "dotclaude", "delegations.jsonl")
    rows = list(entries(ledger_file))
    ran = {"reader": "Explore", "researcher": "researcher", "writer": "writer"}
    for t in [ran[c] for c in cases if c in ran]:
        ev = {r.get("event") for r in rows if r.get("agent_type") == t}
        check(f"ledger: {t} start and stop", {"start", "stop"} <= ev, ",".join(sorted(ev)))
    oks = {r.get("agent_type"): r.get("report_ok") for r in rows if r.get("event") == "stop"}
    print(f"  (report_ok by role, recorded not gated: {oks})")


# ---------------------------------------------------------------- codex runner

def run_codex(keep, cases):
    root = tempfile.mkdtemp(prefix="deleg-codex-")
    state = os.path.join(root, "state")
    env = dict(os.environ, XDG_STATE_HOME=state)
    brief = os.path.join(root, "brief.md")
    with open(brief, "w") as f:
        f.write("Create a file named hello.txt in the working directory containing exactly "
                "the text hi. Then finish. Your report's artifacts must list hello.txt.\n")
    cd = os.path.join(SCRIPTS, "codex-delegate")
    print(f"fixture: {root}")
    p = subprocess.run([sys.executable, cd, "run", "--model", "terra", "--dir", root,
                        "--brief", brief, "--timeout", "15m"],
                       capture_output=True, text=True, env=env, timeout=1200)
    try:
        s = json.loads(p.stdout)
    except ValueError:
        s = {}
    check("codex: exit 0", p.returncode == 0, f"rc={p.returncode} {p.stderr[-300:]}")
    check("codex: report valid", s.get("report_ok"), s.get("report_error") or "")
    check("codex: model audit clean", s.get("audit_ok"), ",".join(s.get("models") or []))
    try:
        with open(os.path.join(root, "hello.txt")) as f:
            hello = f.read().strip()
    except OSError:
        hello = None
    check("codex: deliverable written", hello == "hi", repr(hello))
    rows = list(entries(os.path.join(state, "dotclaude", "delegations.jsonl")))
    check("codex: pending/start/stop rows", [r["event"] for r in rows] == ["pending", "start", "stop"],
          ",".join(r["event"] for r in rows))
    check("codex: thread id recorded", rows and rows[-1].get("thread_id"))
    n = len(rows)
    p = subprocess.run([sys.executable, cd, "run", "--model", "astra", "--dir", root,
                        "--brief", brief], capture_output=True, text=True, env=env)
    rows = list(entries(os.path.join(state, "dotclaude", "delegations.jsonl")))
    check("codex: astra refused before launch", p.returncode == 2 and len(rows) == n,
          p.stderr.strip()[:120])
    return root


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runner", choices=("claude", "codex"), required=True)
    ap.add_argument("--stage", type=int, default=1, choices=(1,))
    ap.add_argument("--keep", action="store_true", help="leave the fixture for inspection")
    ap.add_argument("--cases", default="reader,researcher,writer,guard",
                    help="claude runner only: comma list of reader,researcher,writer,guard")
    a = ap.parse_args()
    cases = [c for c in a.cases.split(",") if c]
    root = (run_claude if a.runner == "claude" else run_codex)(a.keep, cases)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if a.keep or failed:
        print(f"fixture kept: {root}")
    else:
        if a.runner == "claude":
            subprocess.run(["git", "worktree", "prune"], cwd=root, capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
