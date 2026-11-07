#!/usr/bin/env python3
"""Live eval of the long-runs skill: does it load before a long job, stay out of small asks, and
change what a session plans? Manual only, never in the suite: it spends model calls, and needs
the sandbox off, since the sandbox hides the login.

Each run is one `claude -p` in a neutral scratch dir (a cwd naming the skill would bias a trigger
check) holding the case's NOTES.md. The session gets only the Skill and Read tools, so it plans
and changes nothing.

Arms: A no skill (behaviour cases only: with no skill nothing can load), B the skill as a project
skill, C the skill plus CLAUDE.md's line in the project tier. User settings stay on, so the skill
competes with the real skill list; `project,local` alone would overstate loading. The fixture
turns hooks off, so a run can't touch session state, tabs or tmux.
limit: real sessions also get the hooks' skill-first text, so load rates here may read low.

Loading is counted from the stream. Behaviour replies are graded by reading, since regex grading
of replies never settled in tests/practices: replies/ holds each one under a random id with no arm
or load result, and a reader's verdicts go in grades.json, {reply id: pass, partial or fail}, which
the report joins back. Cases the no-skill arm already passes stay as regression guards.

    python3 tests/long_runs/run.py --out DIR --arms A --kinds behaviour --cap 5
    python3 tests/long_runs/run.py --out DIR --report-only
"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SKILL = "long-runs"
SKILL_DIR = os.path.join(REPO, "skills", SKILL)
KINDS = ("loads", "quiet", "behaviour")
MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"}
MAX_TURNS = 6
RUN_BUDGET_USD = 1  # one run's own stop, about five times a normal Opus run
TIMEOUT_S = 300
SKIP_LABELS = ("Skipped:", "Safe because:", "Caught by:")


def load_practices_harness():
    """tests/practices/run.py holds the stream readers. Never edit it from here: any edit to it
    orphans that suite's recorded rows."""
    path = os.path.join(REPO, "tests", "practices", "run.py")
    spec = importlib.util.spec_from_file_location("practices_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


practices = load_practices_harness()


def load_cases(path=os.path.join(HERE, "cases.json")):
    with open(path) as f:
        return json.load(f)


def fingerprint(case, arm, skill_dir=SKILL_DIR, line=""):
    """sha256 of what a run is given: the case, and per arm the skill and CLAUDE.md's line. A row
    with another fingerprint tested something else, so resume and the report leave it out."""
    h = hashlib.sha256("\0".join((case["prompt"], case["notes"], arm)).encode())
    if arm in "BC":
        with open(os.path.join(skill_dir, "SKILL.md"), "rb") as f:
            h.update(f.read())
    if arm == "C":
        h.update(line.encode())
    return h.hexdigest()[:12]


def claude_md_line(path=os.path.join(REPO, "CLAUDE.md")):
    """The line arm C installs: CLAUDE.md's one line naming the skill. "" before it exists."""
    with open(path) as f:
        return next((line.strip() for line in f if SKILL in line), "")


def plan_runs(cases, arms, models, reps, stamp=lambda case, arm: "", done=()):
    """Every run still to do, a rep of everything before the next rep, so a stop at the cap leaves
    every cell covered evenly. `done` holds (case, arm, model, rep, fingerprint) already recorded."""
    runs = []
    for rep in range(reps):
        for model in models:
            for arm in arms:
                for case in cases:
                    if arm == "A" and case["kind"] != "behaviour":
                        continue
                    mark = stamp(case, arm)
                    if (case["id"], arm, model, rep, mark) not in done:
                        runs.append({"case": case, "arm": arm, "model": model, "rep": rep,
                                     "fingerprint": mark})
    return runs


def build_fixture(work, case, arm, skill_dir, line):
    os.makedirs(os.path.join(work, ".claude"))
    with open(os.path.join(work, "NOTES.md"), "w") as f:
        f.write(case["notes"])
    with open(os.path.join(work, ".claude", "settings.json"), "w") as f:
        json.dump({"disableAllHooks": True}, f)
    if arm in "BC":
        shutil.copytree(skill_dir, os.path.join(work, ".claude", "skills", SKILL))
    if arm == "C":
        if not line:
            raise ValueError("arm C needs CLAUDE.md's line naming the skill")
        with open(os.path.join(work, "CLAUDE.md"), "w") as f:
            f.write(line + "\n")


def claude_argv(model):
    return ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
            "--tools", "Skill,Read", "--allowedTools", "Skill", "Read",
            "--permission-mode", "default", "--strict-mcp-config", "--no-session-persistence",
            "--max-turns", str(MAX_TURNS), "--max-budget-usd", str(RUN_BUDGET_USD)]


def child_env(env):
    """The caller's env, minus what would let a run reach this tmux pane."""
    return {k: v for k, v in env.items() if k not in ("TMUX", "TMUX_PANE")}


def skip_fields(text):
    """How many of the skip record's three labels a reply holds, markdown bold allowed."""
    return sum(bool(re.search(rf"^[\s>*_-]*{re.escape(label)}", text, re.M | re.I))
               for label in SKIP_LABELS)


def summarize(events, arm):
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    listed = SKILL in (init.get("skills") or [])
    reply = (result or {}).get("result") or ""
    return {
        "loaded": practices.triggered(events, SKILL),
        # A run with no result (a timeout) still spent, so it counts as its own stop.
        "cost": RUN_BUDGET_USD if result is None else result.get("total_cost_usd") or 0,
        "turns": (result or {}).get("num_turns"),
        "reply": reply,
        "skip_fields": skip_fields(reply),
        "broken": (result is None or bool(result.get("is_error"))
                   or str(result.get("subtype", "")).startswith("error")),
        "contaminated": bool(init) and listed != (arm in "BC"),
    }


class Budget:
    """Holds a run back while it could pass the cap, reserving `per_run` for each run in flight,
    and refuses it once nothing in flight could free room. Set `per_run` to RUN_BUDGET_USD and
    the cap holds: no run spends past its own stop."""

    def __init__(self, cap, spent, per_run):
        self.cap, self.spent, self.per_run, self.flying = cap, spent, per_run, 0
        self.room = threading.Condition()

    def start(self):
        with self.room:
            while self.spent + (self.flying + 1) * self.per_run > self.cap:
                if not self.flying:
                    return False
                self.room.wait()
            self.flying += 1
            return True

    def finish(self, cost):
        with self.room:
            self.flying -= 1
            self.spent += cost
            self.room.notify_all()


def run_one(run, out, skill_dir, line):
    case, arm, model, rep = run["case"], run["arm"], run["model"], run["rep"]
    name = f"{case['id']}-{arm}-{model}-{rep}-{run['fingerprint']}"
    reply_id = hashlib.sha256(name.encode()).hexdigest()[:10]
    stream_path = os.path.join(out, "streams", name + ".jsonl")
    root = tempfile.mkdtemp(prefix="wk-", dir="/tmp")
    work = os.path.join(root, "proj")
    start = time.monotonic()
    timed_out = False
    try:
        build_fixture(work, case, arm, skill_dir, line)
        with open(stream_path, "w") as stdout:
            proc = subprocess.Popen(claude_argv(MODELS[model]), cwd=work, env=child_env(os.environ),
                                    stdin=subprocess.PIPE, stdout=stdout,
                                    stderr=subprocess.DEVNULL, text=True, start_new_session=True)
            try:
                proc.communicate(case["prompt"], timeout=TIMEOUT_S)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    row = summarize(practices.read_stream(stream_path), arm)
    row.update(case=case["id"], kind=case["kind"], arm=arm, model=model, rep=rep,
               fingerprint=run["fingerprint"], reply_id=reply_id, timed_out=timed_out,
               seconds=round(time.monotonic() - start, 1))
    if case["kind"] == "behaviour":
        with open(os.path.join(out, "replies", reply_id + ".md"), "w") as f:
            f.write(f"Prompt: {case['prompt']}\n\nNotes:\n\n{case['notes']}\n"
                    f"Expect: {case['expect']}\n\n---\n\n{row['reply']}\n")
    return row


def read_rows(out):
    path = os.path.join(out, "results.jsonl")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def read_grades(out):
    path = os.path.join(out, "grades.json")
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return json.load(f)


def report(rows, current, grades=None):
    """One line per case, arm and model over rows of `current` fingerprints: loads, then graded
    passes. Spend over every row comes last, since a voided row still cost money."""
    cells = {}
    for row in rows:
        if row.get("broken") or row.get("contaminated") or row["fingerprint"] not in current:
            continue
        cell = cells.setdefault((row["kind"], row["case"], row["arm"], row["model"]), [0, 0, 0, 0])
        cell[0] += bool(row.get("loaded"))
        cell[1] += 1
        grade = (grades or {}).get(row.get("reply_id"))
        cell[2] += grade == "pass"
        cell[3] += grade is not None
    lines = ["kind       case                  arm model   loaded graded-pass"]
    for (kind, case, arm, model), (hits, total, passes, graded) in sorted(cells.items()):
        lines.append(f"{kind:10} {case:21} {arm:3} {model:7} {hits}/{total}    {passes}/{graded}")
    bad = sum(bool(r.get("broken") or r.get("contaminated")) for r in rows)
    lines.append(f"rows {len(rows)}, broken or contaminated {bad}, "
                 f"spent ${sum(r.get('cost', 0) for r in rows):.2f}")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True, help="dir for results.jsonl, streams/, replies/")
    parser.add_argument("--arms", default="ABC")
    parser.add_argument("--models", default="opus,sonnet")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--cases", help="comma-separated case ids; default all")
    parser.add_argument("--kinds", help="comma-separated kinds; default all")
    parser.add_argument("--cap", type=float, default=5.0, help="USD ceiling over all of --out")
    parser.add_argument("--per-run", type=float, default=RUN_BUDGET_USD,
                        help="USD reserved per run in flight")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    os.makedirs(os.path.join(args.out, "streams"), exist_ok=True)
    os.makedirs(os.path.join(args.out, "replies"), exist_ok=True)
    rows = read_rows(args.out)
    all_cases = load_cases()
    line = claude_md_line()

    def stamp(case, arm):
        return fingerprint(case, arm, line=line)

    current = {stamp(case, arm) for case in all_cases for arm in "ABC"}
    if args.report_only:
        print("\n".join(report(rows, current, read_grades(args.out))))
        return

    cases = all_cases
    if args.cases:
        cases = [c for c in cases if c["id"] in args.cases.split(",")]
    if args.kinds:
        cases = [c for c in cases if c["kind"] in args.kinds.split(",")]
    done = {(r["case"], r["arm"], r["model"], r["rep"], r["fingerprint"]) for r in rows
            if not (r.get("broken") or r.get("contaminated"))}
    runs = plan_runs(cases, args.arms, args.models.split(","), args.reps, stamp, done)
    budget = Budget(args.cap, sum(r.get("cost", 0) for r in rows), args.per_run)
    write_lock = threading.Lock()

    def work(run):
        if not budget.start():
            return False
        row = {}
        try:
            row = run_one(run, args.out, SKILL_DIR, line)
        finally:
            budget.finish(row.get("cost", RUN_BUDGET_USD))
        with write_lock, open(os.path.join(args.out, "results.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")
        return True

    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        ran = list(pool.map(work, runs))
    print(f"planned {len(runs)}, ran {sum(ran)}, refused at the cap {ran.count(False)}")
    print("\n".join(report(read_rows(args.out), current, read_grades(args.out))))
    print("LONG_RUNS_EVAL_DONE")


if __name__ == "__main__":
    main()
