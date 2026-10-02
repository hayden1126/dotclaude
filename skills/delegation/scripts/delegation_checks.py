"""The canary and the due checks behind `delegation-ledger canary` and `delegation-ledger due`.

Delegation enforcement leans on Claude Code internals that change without notice, and a change
fails silently: the policy hook fires only when hook input carries "agent_id", a teammate's
role sits in meta.json `customAgentType`, and an unknown settings value is ignored. Claude Code
upgraded three times in three days (2.1.284 to 2.1.286), so the checks split by cost:
- the quick canary tier (unit tests, sandbox posture, strings in the binary; about 20 s, no
  model calls) runs itself in the background on the first session of a new version;
- `audit` runs itself once a day;
- the full tier (the live harness, about 15 sonnet `claude -p` sessions) is nudged when the
  version has moved and the last green full run is 7 or more days old, and again after any
  failed run until one passes;
- dated items in due.toml are nudged from their date on, until they are removed;
- `audit --monthly` (the numbers for retuning liveness.toml and [deadline]) is nudged once the
  ledger holds a month of rows and the last monthly run is a month old, so the first numbers
  rest on weeks of real use.
`due --hook` is the SessionStart body: it prints one line only when something needs Hayden, and
it fails open (it always exits 0; an error goes to delegation-ledger.err). Anything that would
leave the checks unable to run (an unreadable version, a malformed due.toml, a crashing audit)
becomes a nudge itself, so the checks can't go quiet.
`due --hook` also names the watches (`delegation-ledger wait`) left by a session that ended:
no watch guard reads them again, since each guard reads only its own session's watches.

State lives in $XDG_STATE_HOME/dotclaude: canary.json (quick, full, green_full), audit.json
(the last audit's WARN lines, whether a session start has shown them, and when the last
`audit --monthly` ran), due.json (when the
background job last started), checks.lock (one background job at a time), state.lock.
"""
import contextlib
import datetime
import fcntl
import glob
import json
import math
import mmap
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import traceback

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import delegation_common as dc  # noqa: E402

SKILL_DIR = os.path.dirname(dc.HERE)
REPO = os.path.dirname(os.path.dirname(SKILL_DIR))
LEDGER = os.path.join(dc.HERE, "delegation-ledger")
DUE_PATH = os.environ.get("DELEGATION_DUE") or os.path.join(SKILL_DIR, "due.toml")
FULL_EVERY_DAYS = 7
AUDIT_EVERY_HOURS = 24
RELAUNCH_MIN = 10
FULL_COST = "about 16 sonnet `claude -p` sessions and 6 minutes"  # 65 checks in 6 min, 2.1.287
# Set in the quick tier's own test run, so nothing under it can start another background job.
CHILD_ENV = "DELEGATION_CHECKS_CHILD"
VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")

# Strings our hooks and scripts depend on, searched in the claude binary. A missing one means
# an upgrade renamed something we read, and the code that reads it stops working without an
# error. A present one proves little: the live tier is what checks behavior.
CANARY_STRINGS = [
    ("PreToolUse", "settings.json: the policy hook, the spawn guard, the report check"),
    ("SubagentStart", "settings.json: delegation-ledger"),
    ("SubagentStop", "settings.json: delegation-ledger, report-check"),
    ("PostToolUse", "settings.json: delegation-ledger hook (deadline nudge)"),
    ("SessionStart", "settings.json: delegation-due"),
    ("SubagentHandback", "report-check; delegation-ledger handback_message"),
    ("agent_id", "the policy hook's filter in settings.json"),
    ("agent_transcript_path", "delegation-ledger stop rows"),
    ("last_assistant_message", "delegation-ledger, report-check"),
    ("customAgentType", "delegation_common.agent_role"),
    ("teamName", "delegation-ledger, report-check: teammate rows"),
    ("worktreePath", "subagent-policy: a writer's root"),
    ("in_process_teammate", "teammate meta.json taskKind"),
    ("autoAllowBashIfSandboxed", "settings.json sandbox"),
    ("failIfUnavailable", "settings.json sandbox"),
    ("excludedCommands", "settings.json sandbox"),
    ("teammateMode", "settings.json"),
    ("CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS", "SKILL.md §1b: the stall timer"),
]


def state_path(name):
    return os.path.join(dc.state_dir(), name)


def read_state(name):
    try:
        with open(state_path(name)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _d(x):
    """A state field as a dict: a file can be valid JSON of the wrong shape."""
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


@contextlib.contextmanager
def _flock(name, blocking=True):
    os.makedirs(dc.state_dir(), exist_ok=True)
    with open(state_path(name), "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def modify_state(name, fn):
    """Read a state file, let fn edit its dict in place, and replace the file atomically, all
    under one lock. fn returns False to leave the file as it was."""
    with _flock("state.lock"):
        d = read_state(name)
        if fn(d) is False:
            return d
        fd, tmp = tempfile.mkstemp(dir=dc.state_dir(), prefix=f".{name}.")
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=1, sort_keys=True)
        os.replace(tmp, state_path(name))
        return d


def update_state(name, **fields):
    return modify_state(name, lambda d: d.update(fields))


def log_error(note=None):
    try:
        os.makedirs(dc.state_dir(), exist_ok=True)
        with open(state_path("delegation-ledger.err"), "a") as f:
            f.write(f"{dc.now_iso()} {note or traceback.format_exc(limit=3)}\n")
    except Exception:  # noqa: BLE001  the error log must not raise either
        pass


def _age(ts, now):
    """Seconds since an ISO timestamp; infinite when there is none."""
    try:
        return now - dc.parse_iso(ts).timestamp()
    except (TypeError, ValueError):
        return float("inf")


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def cc_version(timeout=10):
    """The version of the `claude` on PATH, which is the one the live tier runs. None when it
    can't be read, which `due` reports instead of going quiet."""
    try:
        p = subprocess.run(["claude", "--version"], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    m = VERSION_RE.search(p.stdout or "") or VERSION_RE.search(p.stderr or "")
    return m.group(1) if m else None


def cc_binary():
    # The `claude` on PATH first, to match cc_version(). CLAUDE_CODE_EXECPATH is the running
    # session's binary, which is the old one in a session started before an upgrade.
    w = shutil.which("claude")
    if w:
        return os.path.realpath(w)
    p = os.environ.get("CLAUDE_CODE_EXECPATH")
    return p if p and os.path.isfile(p) else None


# --- the quick tier ------------------------------------------------------------------------

def check_units():
    tests = os.path.join(REPO, "tests")
    if not os.path.isdir(os.path.join(tests, "delegation")):
        return False, f"no tests at {tests}: the skill isn't linked from a dotclaude checkout"
    done = []
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items()
               if k not in ("DELEGATION_POLICY", "DELEGATION_LEDGER", "DELEGATION_DUE")}
        env["XDG_STATE_HOME"] = tmp  # no test may touch the real ledger
        env[CHILD_ENV] = "1"
        for suite in ("delegation", "setup"):
            d = os.path.join(tests, suite)
            if not os.path.isdir(d):
                continue
            p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", d, "-t", d],
                               cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
            if p.returncode:
                lines = p.stderr.splitlines()
                failed = [ln for ln in lines if ln.startswith(("FAIL:", "ERROR:"))]
                why = [ln for ln in lines if re.match(r"\w+(Error|Exception): ", ln)]
                return False, f"tests/{suite}: " + ("; ".join(failed[:3] + why[-1:])
                                                    or p.stderr.strip()[-300:])
            ran = re.search(r"Ran (\d+) test", p.stderr)
            done.append(f"tests/{suite} {ran.group(1) if ran else '?'}")
    return True, ", ".join(done) + " passed"


def check_posture():
    try:
        with tempfile.TemporaryDirectory() as tmp:  # no project settings: the user posture
            p = subprocess.run(["claude", "sandbox", "status"], cwd=tmp, capture_output=True,
                               text=True, timeout=30)
        s = json.loads(p.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        return False, f"`claude sandbox status` gave no JSON ({type(e).__name__}: {e})"
    if not isinstance(s, dict):
        return False, "`claude sandbox status` gave no JSON object"
    want = {"enabled": True, "autoAllowBashIfSandboxed": False, "unavailableReason": None}
    # A key that is gone fails too: an upgrade that renames one must not read as the default.
    bad = [f"{k}={s[k]!r}" if k in s else f"{k} missing" for k, v in want.items()
           if k not in s or s[k] != v]
    if bad:
        return False, f"sandbox posture {', '.join(bad)}, want " + ", ".join(
            f"{k}={v!r}" for k, v in want.items())
    return True, "sandbox enabled, Bash auto-allow off"


def check_strings(path=None, strings=CANARY_STRINGS):
    path = path or cc_binary()
    if not path:
        return False, "no claude binary on PATH"
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            missing = [s for s, _ in strings if m.find(s.encode()) < 0]
    except (OSError, ValueError) as e:
        return False, f"can't read {path} ({type(e).__name__}: {e})"
    if missing:
        return False, (f"missing from {path}: {', '.join(missing)}. An upgrade renamed something "
                       "our hooks read; CANARY_STRINGS names who reads each")
    return True, f"all {len(strings)} strings present in {path}"


def run_quick(version):
    results = []
    for name, fn in (("units", check_units), ("posture", check_posture),
                     ("strings", check_strings)):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001  a crashed check is a failed check
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append({"check": name, "ok": bool(ok), "detail": detail})
    return {"version": version, "ts": dc.now_iso(), "ok": all(r["ok"] for r in results),
            "results": results}


# --- the full tier -------------------------------------------------------------------------

def run_live(log):
    """The live harness, all stages: (passed, checks passed, checks run, FAIL lines)."""
    run_py = os.path.join(REPO, "tests", "delegation", "run.py")
    timed_out = False
    with open(log, "w") as f:
        try:
            rc = subprocess.run([sys.executable, "-u", run_py, "--runner", "claude"], cwd=REPO,
                                stdout=f, stderr=subprocess.STDOUT, timeout=4 * 3600).returncode
        except subprocess.TimeoutExpired:
            rc, timed_out = None, True
    with open(log, errors="replace") as f:
        text = f.read()
    scores = re.findall(r"^(\d+)/(\d+) checks passed", text, re.M)
    fails = [ln.strip() for ln in text.splitlines() if "[FAIL]" in ln]
    if timed_out:
        fails.append("the live harness timed out after 4 h")
    n, m = (int(scores[-1][0]), int(scores[-1][1])) if scores else (0, 0)
    return rc == 0 and m > 0 and n == m, n, m, fails  # 0/0 exits 0 too, and isn't green


def _say(line):
    print(line, flush=True)  # a background run's output file shows progress as it goes


def canary(quick_only, accept_fewer=False, out=_say):
    version = cc_version()
    if not version:
        out("canary: `claude --version` printed no version")
        return 1
    if not quick_only and os.environ.get("SANDBOX_RUNTIME"):
        out("canary: the live tier runs `claude -p`, which needs the credentials the sandbox "
            "hides. Run `delegation-ledger canary` outside the sandbox and in the background "
            f"({FULL_COST}). `canary --quick` runs anywhere.")
        return 2
    rec = run_quick(version)
    for r in rec["results"]:
        out(f"{'ok  ' if r['ok'] else 'FAIL'} {r['check']}: {r['detail']}")
    try:
        update_state("canary.json", quick=rec)
    except OSError as e:
        out(f"canary: can't record the result in {dc.state_dir()} ({e}). Inside the sandbox "
            "the state dir is read-only: rerun outside it to record it.")
        return 1
    if quick_only or not rec["ok"]:
        if not rec["ok"] and not quick_only:
            out("live tier skipped: fix the quick tier first")
        return 0 if rec["ok"] else 1
    log = state_path(f"canary-{version}-{time.strftime('%Y%m%dT%H%M%S')}.log")
    out(f"live tier: tests/delegation/run.py --runner claude, logging to {log}")
    least = _d(read_state("canary.json").get("green_full")).get("total")
    total = None
    try:
        ok, n, total, fails = run_live(log)
        score = f"{n}/{total}"
    except Exception as e:  # noqa: BLE001  a crashed run is recorded as a failed one
        ok, score, fails = False, f"crashed ({type(e).__name__}: {e})", []
    if ok and isinstance(least, int) and total < least and not accept_fewer:
        # A harness change that drops checks would otherwise pass as green.
        ok = False
        fails.append(f"the harness ran {total} checks, fewer than the last green run's {least}. "
                     "If checks were removed on purpose, rerun with --accept-fewer")
    full = {"version": version, "ts": dc.now_iso(), "ok": ok, "score": score, "log": log,
            "fails": fails[:10]}
    green = {"green_full": {"version": version, "ts": full["ts"], "total": total}} if ok else {}
    update_state("canary.json", full=full, **green)
    for ln in fails:
        out(f"FAIL {ln}")
    out(f"{'ok  ' if ok else 'FAIL'} live: {score} checks" + ("" if ok else f", log {log}"))
    return 0 if ok else 1


# --- due -----------------------------------------------------------------------------------

def load_items(path=None):
    """[(date, do)] from due.toml. A missing file has no items; a malformed one raises."""
    try:
        with open(path or DUE_PATH, "rb") as f:
            d = tomllib.load(f)
    except FileNotFoundError:
        return []
    items = d.get("item", [])
    if not isinstance(items, list):
        raise ValueError("due.toml: `item` must be an array of tables ([[item]])")
    out = []
    for it in items:
        date, do = (it.get("date"), it.get("do")) if isinstance(it, dict) else (None, None)
        if (not isinstance(date, datetime.date) or isinstance(date, datetime.datetime)
                or not isinstance(do, str) or not do.strip()):
            raise ValueError(f"due.toml: each [[item]] needs date = YYYY-MM-DD and a do string, "
                             f"got {it!r}")
        out.append((date, do.strip()))
    return out


def read_items():
    """(items, error): a malformed due.toml becomes a nudge, not silence."""
    try:
        return load_items(), None
    except (ValueError, tomllib.TOMLDecodeError, OSError) as e:
        return [], f"{type(e).__name__}: {e}"


MONTHLY_NUDGE = ("the monthly audit is due: run `delegation-ledger audit --monthly` as a bare "
                 "command, then retune policy.toml [deadline] and liveness.toml where it has "
                 "the samples (it marks the rest too few to retune).")


ORPHANS_LISTED = 3


def orphaned_watches(current=None, now=None):
    """(watches, unreadable): the open or acknowledged watches nobody waits on, oldest first,
    and how many watch files couldn't be read. A watch is nobody's when its session isn't
    running and its waiter isn't alive; `current` (the starting session's id) counts as
    running, and a watch whose waiter lives is still waited on, even with its session gone.
    A file that can't be read or judged is logged and counted, and the rest go on. Where pids
    can't be seen (a sandboxed run) every waiter and session would read as dead, so there are
    none."""
    if not dc.pids_visible():
        return [], 0
    live = set(dc.live_sessions())
    if isinstance(current, str) and current:
        live.add(current)
    found, unreadable = [], 0
    for p in sorted(glob.glob(os.path.join(dc.watches_dir(), "*.json"))):
        try:
            w = dc.read_watch(os.path.basename(p)[:-len(".json")])
            if (w and w.get("state") in dc.UNRESOLVED and w.get("session_id") not in live
                    and not dc.waiter_alive(w, now)):
                found.append(w)
        except Exception as e:  # noqa: BLE001  one bad file mustn't hide the others
            log_error(f"watch file {p}: {type(e).__name__}: {e}")
            unreadable += 1
    return sorted(found, key=lambda w: str(w.get("created"))), unreadable


def orphans_nudge(orphans, unreadable=0):
    bad = (f"{unreadable} watch {'file' if unreadable == 1 else 'files'} couldn't be read; see "
           "delegation-ledger.err") if unreadable else ""
    if not orphans:
        return f"{bad}."
    n = len(orphans)
    named = [f"{w.get('id')} ({w['description']})" if w.get("description") else str(w.get("id"))
             for w in orphans[:ORPHANS_LISTED]]
    more = f" and {n - ORPHANS_LISTED} more" if n > ORPHANS_LISTED else ""
    text = (f"{n} {'watch' if n == 1 else 'watches'} from a session that ended: "
            f"{', '.join(named)}{more}. Pick one up with `delegation-ledger wait --resume "
            "<id>`, or drop it with `delegation-ledger wait --drop <id>`.")
    return f"{text} ({bad})" if bad else text


def evaluate(version, canary_st, audit_st, due_st, items, now=None, today=None,
             items_error=None, ledger_since=None, orphans=(), unreadable=0):
    """(nudges, jobs, warns) from the state, without side effects. `warns` are the audit
    warnings the nudges show, for mark_shown. `ledger_since` is the ledger's first ts.
    `orphans` and `unreadable` are orphaned_watches' result: the watches a session left,
    oldest first, and how many watch files couldn't be read."""
    now = time.time() if now is None else now
    today = today or datetime.date.today()
    canary_st, audit_st, due_st = _d(canary_st), _d(audit_st), _d(due_st)
    nudges, jobs = [], []
    if orphans or unreadable:  # first: a finished job's result may be waiting on it
        nudges.append(orphans_nudge(list(orphans), unreadable))
    may_launch = _age(due_st.get("bg_started"), now) > RELAUNCH_MIN * 60
    quick, full, green = (_d(canary_st.get(k)) for k in ("quick", "full", "green_full"))
    if not version:
        nudges.append("can't read the Claude Code version from `claude --version`, so the "
                      "canary can't tell when an upgrade lands. Check that `claude` is on PATH "
                      "and what `claude --version` prints.")
    else:
        if quick.get("version") != version:
            if may_launch:
                jobs.append("quick")
        elif not quick.get("ok"):
            first = next((r for r in _l(quick.get("results"))
                          if isinstance(r, dict) and not r.get("ok")), {})
            nudges.append(f"the quick canary failed on Claude Code {version}: "
                          f"{first.get('check')}: {first.get('detail')}. Rerun "
                          "`delegation-ledger canary --quick` outside the sandbox to see it "
                          "and record the result.")
        # A red run newer than the last green one stays red across upgrades, until a run passes.
        if full and not full.get("ok") and str(full.get("ts", "")) > str(green.get("ts", "")):
            nudges.append(f"the last full canary failed (Claude Code {full.get('version')}, "
                          f"{full.get('score')} checks; log {full.get('log')}). Rerun "
                          "`delegation-ledger canary` once it is fixed.")
        elif not green or (green.get("version") != version
                           and _age(green.get("ts"), now) >= FULL_EVERY_DAYS * 86400):
            last = (f"last green: {green.get('version')} on {str(green.get('ts'))[:10]}"
                    if green else "none on record")
            nudges.append(f"the full canary is due for Claude Code {version} ({last}). Run "
                          "`delegation-ledger canary` outside the sandbox and in the "
                          f"background: {FULL_COST}.")
    if _age(audit_st.get("ts"), now) >= AUDIT_EVERY_HOURS * 3600 and may_launch:
        jobs.append("audit")
    warns = [str(w) for w in _l(audit_st.get("warns"))]
    if warns and not audit_st.get("shown"):
        nudges.append("the daily audit warned: " + " ".join(warns)
                      + " (`delegation-ledger audit` has the detail)")
    else:
        warns = []
    month = dc.MONTH_DAYS * 86400
    if (ledger_since and _age(ledger_since, now) >= month
            and _age(audit_st.get("monthly"), now) >= month):
        nudges.append(MONTHLY_NUDGE)
    if items_error:
        nudges.append(f"skills/delegation/due.toml is malformed, so the dated reminders are off "
                      f"until it is fixed: {items_error}")
    for date, do in items:
        if date <= today:
            nudges.append(f"due since {date.isoformat()}: {do}")
    return nudges, jobs, warns


def launch_background(jobs):
    if os.environ.get(CHILD_ENV):
        return  # inside the quick tier's own test run: never start another
    subprocess.Popen([sys.executable, LEDGER, "due", "--background", *jobs], cwd=dc.HERE,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def render(nudges):
    # systemMessage only: Claude Code 2.1.286 shows it to Hayden at session start
    # ("SessionStart:startup says: ..."), while additionalContext reaches only the model, which
    # would carry an upkeep note into every unrelated session.
    text = "Delegation checks: " + " ".join(f"({i}) {n}" for i, n in enumerate(nudges, 1))
    return {"systemMessage": text}


def mark_shown(displayed):
    """Mark the audit warnings shown, unless an audit replaced them since they were read."""
    def fn(d):
        if [str(w) for w in _l(d.get("warns"))] != displayed:
            return False
        d["shown"] = True
    modify_state("audit.json", fn)


def hook_main(stdin_text="", out=print):
    """The SessionStart body. Fails open: it always returns 0, and an error is logged. A
    watch file that can't be read is counted in the watch nudge; any other error reading the
    watches drops only that nudge."""
    try:
        session = _d(json.loads(stdin_text or "{}")).get("session_id")
    except ValueError:
        session = None  # the payload only spares this session's own watches
    try:
        orphans, unreadable = orphaned_watches(session)
    except Exception:  # noqa: BLE001
        log_error()
        orphans, unreadable = [], 0
    try:
        version = cc_version(timeout=2)  # the hook itself gets 5 s
        items, items_error = read_items()
        nudges, jobs, warns = evaluate(version, read_state("canary.json"),
                                       read_state("audit.json"), read_state("due.json"),
                                       items, items_error=items_error,
                                       ledger_since=dc.first_row_ts(), orphans=orphans,
                                       unreadable=unreadable)
    except Exception:  # noqa: BLE001  a reminder must never get in the way of a session
        log_error()
        return 0
    # A headless `claude -p` (CLAUDE_CODE_SESSION_ATTENDED=0, probed on 2.1.286) still starts
    # the cheap checks, but nobody reads its screen: it neither prints nor uses up warnings.
    attended = os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") != "0"
    if nudges and attended:
        out(json.dumps(render(nudges)))  # first, so a failure below can't drop the nudges
    try:
        if warns and attended:
            mark_shown(warns)
        if jobs:
            update_state("due.json", bg_started=dc.now_iso(), bg_jobs=jobs)
            launch_background(jobs)
    except Exception:  # noqa: BLE001
        log_error()
    return 0


def background(jobs):
    """The detached job a session start launches: the quick tier and/or the audit."""
    try:
        with _flock("checks.lock", blocking=False) as got:
            if not got:
                return 0  # another session's job is already running
            if "quick" in jobs:
                version = cc_version()
                if version and _d(read_state("canary.json").get("quick")).get(
                        "version") != version:
                    update_state("canary.json", quick=run_quick(version))
            # Re-read under the lock: another session's job may have just run the audit.
            age = _age(read_state("audit.json").get("ts"), time.time())
            if "audit" in jobs and age >= AUDIT_EVERY_HOURS * 3600:
                hours = min(168.0, age / 3600 + 0.1)
                p = subprocess.run([sys.executable, LEDGER, "audit", "--hours", f"{hours:.2f}",
                                    "--unshown"], capture_output=True, text=True, timeout=600)
                if p.returncode not in (0, 1):  # 1 means it warned, and its stamp holds that
                    log_error(f"daily audit exited {p.returncode}: {p.stderr[-2000:]}")
                    tail = (p.stderr.strip().splitlines() or ["no output"])[-1]
                    stamp_audit(hours, [f"WARN the daily audit crashed (exit {p.returncode}): "
                                        f"{tail}"], shown=False)
    except Exception:  # noqa: BLE001
        log_error()
    return 0


def stamp_audit(hours, lines, shown, now=None):
    """Record an audit for `due`. Only an audit whose window reaches back to the last stamp
    moves it, so a narrow manual run leaves no unaudited gap. Warnings nobody has seen yet
    are kept, never overwritten."""
    now = time.time() if now is None else now
    new = [ln[len("WARN "):].strip() for ln in lines if ln.startswith("WARN")]

    def fn(d):
        age = _age(d.get("ts"), now)
        if not math.isinf(age) and hours * 3600 + 60 < age:
            return False  # this window doesn't cover the time since the last stamp
        pending = [] if d.get("shown") else [str(w) for w in _l(d.get("warns"))]
        # A manual run printed its own warnings, so only the unseen older ones remain.
        warns = pending if shown else pending + [w for w in new if w not in pending]
        d.update(ts=_iso(now), hours=hours, warns=warns, shown=not warns)
    modify_state("audit.json", fn)


def status(out=print):
    """What `due` would nudge now, and the state behind it. Read-only."""
    version = cc_version()
    c, a, d = read_state("canary.json"), read_state("audit.json"), read_state("due.json")
    items, items_error = read_items()
    since = dc.first_row_ts()
    nudges, jobs, _ = evaluate(version, c, a, d, items, items_error=items_error,
                               ledger_since=since)
    out(f"Claude Code {version or '(no version)'}")
    for key in ("quick", "full", "green_full"):
        r = _d(c.get(key))
        if not r:
            out(f"  {key:10} none on record")
            continue
        verdict = "" if key == "green_full" else (" ok" if r.get("ok") else " FAILED")
        score = f" {r['score']}" if r.get("score") else ""
        out(f"  {key:10} {r.get('version')} at {r.get('ts')}{verdict}{score}")
    unseen = 0 if a.get("shown") else len(_l(a.get("warns")))
    out("  audit      " + (f"{a.get('ts')}, {unseen} unseen warning(s)" if a else "never run"))
    out("  monthly    " + (str(a.get("monthly")) if a.get("monthly") else "never run")
        + (f" (ledger since {str(since)[:10]})" if since else " (no ledger)"))
    for date, do in items:
        out(f"  dated      {date.isoformat()}: {do}")
    if jobs:
        out(f"a session start would run in the background: {', '.join(jobs)}")
    out("due now:" if nudges else "nothing due")
    for n in nudges:
        out(f"  - {n}")
    return 0
