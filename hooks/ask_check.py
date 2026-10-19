"""PreToolUse(AskUserQuestion) hook; hooks/ask-check.sh runs it.

Denies a risky ask once, before the user sees the dialog, with a checklist as the reason. A deny
is the only channel that reaches the model first (additionalContext arrives with the answer).
It reaches the model as "PreToolUse:AskUserQuestion hook error: <reason>", and the model resends
in the same turn (probed on 2.1.304 in default and plan mode).

The window is the transcript since the latest of: the last typed prompt, the last answered ask,
the last approved plan. An ask is risky when any of these holds:
  report  a subagent's report is in the window (a completed foreground Agent/Task result, an
          agent's task notification, a hand-back) with at most one Read, Grep, Glob or Bash
          call after the newest one: its claims would reach the user unchecked;
  ticks   the question texts hold 4 or more backticked names, which the user may not know;
  lane    the ask names a file another live lane of this repo is changing (its branch's diff
          from the base, or its brief's Expected files) without naming that lane.
Once per window: a deny of this hook's already in the window lets the ask through, so the
resend always passes. Without a transcript that can't be seen, so the ask passes.

Each ask with a cwd runs one `git rev-parse` to find its repo. The lane rule runs more git only
when that repo has another live lane: one `worktree list`, then one three-dot diff per lane the
ask doesn't name, each with a short timeout, all inside a budget that leaves the other rules
their deny. It reads no uncommitted state, so no `git status` runs in another lane's worktree.

Subagent payloads (agent_id) are skipped. Any failure is logged to
$XDG_STATE_HOME/dotclaude/ask-check.log and allows the ask (fail open: advisory, not a guard).
"""
import json
import os
import re
import subprocess
import sys
import time

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "skills",
                       "lanes", "scripts")
sys.path.insert(0, SCRIPTS)
try:
    import lanelib  # noqa: E402
except ImportError as e:  # the lane rule is off; the others still hold
    lanelib, LANELIB_ERROR = None, e

# How a resend finds this hook's deny: the reason's own opening, never Claude Code's wording
# around it ("PreToolUse:AskUserQuestion hook error: " on 2.1.304), which a release may change.
MARKER = "ask-check: this ask was held back before the dialog"
CHECKLIST = (
    "Check each claim in the ask against the code yourself, not from an agent's report.",
    "Name every other live lane whose file the ask mentions.",
    "Restate the scope against the brief, and say so if this grows it.",
    "If the user skipped a question, say so before asking its parts again.",
    "Explain each code name in plain words, or drop it.",
)
CHECKS = {"Read", "Grep", "Glob", "Bash"}
REPORTERS = {"Agent", "Task"}
ANSWERS = {"AskUserQuestion", "ExitPlanMode"}  # a result that isn't an error is the user's
TICK = re.compile(r"`([^`\n]{2,60})`")
TICKS_MAX = 3
CHUNK = 1 << 18
TAIL_MAX = 8 << 20  # bytes read back from the transcript's end at most
RECORD_MAX = 1 << 16
GIT_WAIT = 1.0  # each git call
LANE_BUDGET = 3.0  # seconds for the whole lane rule: settings.json kills the hook at 5 s
# The CLI's OVERLAP_ENV: a three-dot diff reads objects only, and never fetches a missing one.
DIFF_ENV = {"GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "none"}
SKIPPED = ("STATUS.md", "README.md")
GENERIC = {"SKILL.md", "STATUS.md", "README.md", "PLAN.md", "SPEC.md", "CLAUDE.md",
           "__init__.py"}
EXPECTED = re.compile(r"^- Expected files:[ \t]*(.*)$", re.M)
PATHLIKE = re.compile(r"/|\.\w{1,8}$")
TOKEN = re.compile(r"[\w.*-]+(?:/[\w.*-]+)*/?")  # path characters only, * for a glob


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "ask-check.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        return


def entry(line: bytes) -> dict | None:
    """A main-chain user or assistant entry with a message object, or None."""
    if b'"user"' not in line and b'"assistant"' not in line:
        return None
    try:
        e = json.loads(line)
    except (ValueError, RecursionError):  # json recurses on nesting
        return None
    if (not isinstance(e, dict) or e.get("type") not in ("user", "assistant")
            or e.get("isSidechain") or not isinstance(e.get("message"), dict)):
        return None
    return e


def newest_first(path: str):
    """The transcript's entries from its end back, up to TAIL_MAX bytes; a line cut at the cap
    is dropped."""
    with open(path, "rb") as f:
        end = f.seek(0, os.SEEK_END)
        pos, carry = end, b""
        while pos > 0 and end - pos < TAIL_MAX:
            step = min(CHUNK, pos)
            pos -= step
            f.seek(pos)
            lines = (f.read(step) + carry).split(b"\n")
            carry = lines.pop(0) if pos > 0 else b""
            for line in reversed(lines):
                e = entry(line)
                if e:
                    yield e


def typed(e: dict) -> bool:
    return (e["type"] == "user" and not e.get("isMeta")
            and (e.get("origin") or {}).get("kind") == "human")


def blocks(e: dict) -> list[dict]:
    c = e["message"].get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def text_of(e: dict) -> str:
    c = e["message"].get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text") or "" for b in blocks(e) if b.get("type") == "text")


def is_report(text: str) -> bool:
    """An agent's task notification or a subagent's hand-back, not a background command's."""
    head = text.lstrip()[:3000]
    if head.startswith("<task-notification"):
        return "<summary>Agent " in head and "Background command" not in head
    return "[Subagent hand-back]" in head


def result_text(b: dict) -> str:
    c = b.get("content")
    if isinstance(c, list):
        return "\n".join(x.get("text") or "" for x in c if isinstance(x, dict))
    return c if isinstance(c, str) else ""


def window(path: str) -> dict:
    """What the window holds: denied (this hook already denied in it), report (a report is in
    it) and checks (Read, Grep, Glob or Bash calls after the newest report)."""
    rows = []
    for e in newest_first(path):
        if typed(e):
            break
        rows.append(e)
    names, state = {}, {"denied": False, "report": False, "checks": 0}
    for e in reversed(rows):
        if e["type"] == "assistant":
            for b in blocks(e):
                if b.get("type") == "tool_use":
                    names[b.get("id")] = b.get("name")
                    if b.get("name") in CHECKS:
                        state["checks"] += 1
            continue
        if is_report(text_of(e)):
            state.update(report=True, checks=0)
        tur = e.get("toolUseResult")
        for b in blocks(e):
            if b.get("type") != "tool_result":
                continue
            name = names.get(b.get("tool_use_id"))
            if name in ANSWERS and not b.get("is_error"):
                state = {"denied": False, "report": False, "checks": 0}
            elif name == "AskUserQuestion" and b.get("is_error") and MARKER in result_text(b):
                state["denied"] = True
            elif (name in REPORTERS and not b.get("is_error") and isinstance(tur, dict)
                  and tur.get("status") == "completed"):
                state.update(report=True, checks=0)
    return state


def pattern(path: str) -> str:
    """A regex for path, a * matching within one segment."""
    return re.escape(path).replace(r"\*", r"[\w.-]*")


def bounded(path: str) -> str:
    """A regex for path as a whole name: it may end a longer path (`/abs/hooks/x.py`,
    `./hooks/x.py`), but never sits inside a longer name (`myhooks/x.py`, `x.py.bak`); a
    sentence's closing period is fine."""
    return r"(?<![\w.-])" + pattern(path) + r"(?![\w/-]|\.\w)"


def mentions(text: str, path: str) -> bool:
    """Does the ask name path (a file, or a folder when it ends in /): in full when 2+ levels
    deep; by a path under it when it may be a folder (no extension) 2+ levels deep; by a file's
    basename of 8+ characters that isn't generic. tests/ and status files never count."""
    folder = path.endswith("/")
    path = path.strip("/")
    if not path or path.startswith("tests/") or path in SKIPPED:
        return False
    base = path.rsplit("/", 1)[-1]
    if "/" in path:
        if re.search(bounded(path), text):
            return True
        if (folder or "." not in base) and re.search(
                r"(?<![\w.-])" + pattern(path) + r"/[\w.-]", text):
            return True
    return (not folder and "*" not in base and len(base) >= 8 and base not in GENERIC
            and bool(re.search(bounded(base), text)))


def expected_files(lane: dict) -> list[str]:
    """The path-like entries of the lane's brief's Expected files line, from its record (never
    followed through a symlink: lanelib.read_head opens with O_NOFOLLOW). An entry 2+ levels
    deep counts only when its first folder exists in the lane's worktree, so prose like
    `and/or` is no path."""
    if lanelib.record_is_link(lane):
        return []
    raw = lanelib.read_head(lanelib.record_path(lane), RECORD_MAX)
    m = EXPECTED.search(raw.decode("utf-8", "replace")) if raw else None
    if not m:
        return []
    tokens = (t.strip("`'\"()[]{},;:.").removeprefix("./") for t in m.group(1).split())
    return [t for t in tokens if TOKEN.fullmatch(t) and PATHLIKE.search(t)
            and not t.startswith("-")
            and ("/" not in t.strip("/") or os.path.lexists(
                os.path.join(lane["path"], t.split("/", 1)[0])))]


def worktree_heads(repo: "lanelib.Repo") -> dict[str, str]:
    """Registered worktree path (real) -> the ref it has checked out: its branch, or its commit
    when detached. The lane CLI's worktree_heads and lane_head do the same; hooks don't import
    the CLI."""
    p = lanelib.git(["worktree", "list", "--porcelain"], repo.toplevel, timeout=GIT_WAIT,
                    env=DIFF_ENV)
    out, path = {}, None
    for line in p.stdout.splitlines() if p.returncode == 0 else []:
        if line.startswith("worktree "):
            path = os.path.realpath(line[len("worktree "):])
        elif line.startswith("HEAD ") and path:
            out.setdefault(path, line[len("HEAD "):])
        elif line.startswith("branch ") and path:
            out[path] = line[len("branch "):]
    return out


def committed_files(repo: "lanelib.Repo", base: str, ref: str) -> list[str]:
    p = lanelib.git(["diff", "--name-only", "-z", "--no-renames", "--no-ext-diff",
                     "--end-of-options", f"{base}...{ref}", "--"], repo.toplevel,
                    timeout=GIT_WAIT, env=DIFF_ENV)
    return [f for f in p.stdout.split("\0") if f] if p.returncode == 0 else []


def names_lane(text: str, lane_id: str) -> bool:
    """Does the ask name the lane? An id with a hyphen or digit (`branch-reuse`) counts alone,
    outside a path; a plain word (`pass`) only beside "lane" or in backticks, since "the tests
    pass" names no lane."""
    word = re.escape(lane_id)
    if re.search(r"[-\d]", lane_id) and re.search(r"(?<![\w/.-])" + word + r"(?![\w/-])", text):
        return True
    return bool(re.search(r"\blanes?\s+`?" + word + r"`?(?![\w/-])|(?<![\w/.-])`?" + word
                          + r"`?\s+lane\b|`" + word + "`", text, re.I))


def lane_hits(text: str, cwd: str) -> list[tuple[str, str]]:
    """(lane id, file) for each file another live lane is changing that the ask names, where
    the ask doesn't name that lane. A git call that fails or runs past GIT_WAIT costs only its
    own lane, and lanes left when LANE_BUDGET runs out are skipped."""
    if lanelib is None:
        log(f"lane rule off: lanelib unimportable ({LANELIB_ERROR})")
        return []
    deadline = time.monotonic() + LANE_BUDGET
    repo = lanelib.resolve(cwd, timeout=GIT_WAIT)
    if repo is None or not repo.has_lanes:
        return []
    lanes = repo.lanes()
    try:
        _, me = repo.identity(lanes)
    except lanelib.Untrusted:
        me = None
    others = [lane for lane in lanes if lanelib.is_live(lane)
              and (me is None or lane["id"] != me["id"])
              and not names_lane(text, lane["id"])]
    if not others:
        return []
    base = repo.config().get("base", "origin/main")
    base = base if base.startswith("refs/") else f"refs/remotes/{base}"
    try:
        heads = worktree_heads(repo)
    except (OSError, ValueError, subprocess.SubprocessError) as e:  # ValueError: not UTF-8
        log(f"worktree list unread {type(e).__name__}: {e}")
        heads = {}
    hits = []
    for lane in others:
        if time.monotonic() > deadline:
            log(f"lane budget spent: skipped lane {lane['id']} and those after it")
            break
        ref = heads.get(os.path.realpath(lane["path"])) or f"refs/heads/{lane['branch']}"
        try:
            files = committed_files(repo, base, ref)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            log(f"diff unread lane={lane['id']} {type(e).__name__}: {e}")
            files = []
        found = {f.rstrip("/") for f in files + expected_files(lane) if mentions(text, f)}
        hits += [(lane["id"], f) for f in sorted(found)]
    return hits


def reason(fired: list[str], state: dict, ticks: int, hits: list[tuple[str, str]]) -> str:
    why = []
    if "report" in fired:
        n = state["checks"]
        why.append(f"a subagent report came in since the user's last answer, and {n} "
                   f"check{'' if n == 1 else 's'} (Read, Grep, Glob, Bash) followed it")
    if "ticks" in fired:
        why.append(f"the questions use {ticks} backticked names")
    for lane_id, path in hits:
        why.append(f"lane {lane_id} is changing {path}, and the ask doesn't name the lane")
    items = "\n".join(f"{i}. {item}" for i, item in enumerate(CHECKLIST, 1))
    return (f"{MARKER}, since "
            + "; ".join(why) + f".\nBefore you resend:\n{items}\n"
            "Fix what applies, then resend the ask. This check won't stop it again before the "
            "user's next answer.")


def main():
    event = json.load(sys.stdin)
    if (not isinstance(event, dict) or event.get("agent_id")
            or event.get("tool_name") != "AskUserQuestion"):
        return
    path = event.get("transcript_path")
    if not isinstance(path, str) or not os.path.isfile(path):
        return
    state = window(path)
    if state["denied"]:
        log(f"pass already-denied sid={event.get('session_id')}")
        return
    questions = (event.get("tool_input") or {}).get("questions")
    texts = [q.get("question") or "" for q in questions]
    options = [o.get("label", "") + " " + o.get("description", "")
               for q in questions for o in q.get("options") or []]
    ticks = sum(len(TICK.findall(t)) for t in texts)
    fired = []
    if state["report"] and state["checks"] <= 1:
        fired.append("report")
    if ticks > TICKS_MAX:
        fired.append("ticks")
    cwd = event.get("cwd")
    try:
        hits = lane_hits("\n".join(texts + options), cwd) if isinstance(cwd, str) else []
    except Exception as e:  # the other rules still hold
        log(f"lane lookup error {type(e).__name__}: {e}")
        hits = []
    if hits:
        fired.append("lane")
    if not fired:
        return
    log(f"deny {','.join(fired)} sid={event.get('session_id')} "
        + " ".join(f"{lane_id}:{path}" for lane_id, path in hits))
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason(fired, state, ticks, hits)}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a broken check must never block an ask
        log(f"error {type(e).__name__}: {e}")
