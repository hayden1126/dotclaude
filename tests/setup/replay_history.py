#!/usr/bin/env python3
"""Replay the typed prompt history through the handoff-reminder hook, against a git ref's version.

Local only. ~/.claude/history.jsonl holds every prompt typed on this machine, private names
included, so this prints to the terminal and writes nothing. Never paste its output into the
repo, a PR or an agent's brief; turn a case into a genericized test instead.

    python3 tests/setup/replay_history.py                 # this checkout against main
    python3 tests/setup/replay_history.py --against REF   # against another ref
    python3 tests/setup/replay_history.py --all           # also list every fire

It prints the fire counts, every prompt the two versions disagree on, and the near-misses: short
prompts with a wrap-up word that neither version fires on. Read all of them. A version with
hooks/handoff_reminder.py is classified in-process, in seconds; an older one, with the Python inside
hooks/handoff-reminder.sh, runs through bash per prompt (about a minute for 3,000 prompts). Not a
unit test (its name keeps discovery away from it).
"""
import argparse
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = "hooks/handoff-reminder.sh"
MODULE = "hooks/handoff_reminder.py"
NEAR = re.compile(r"wrap|hand ?-?off|stop here|call it|/clear|done for|clear (the )?(context|session)", re.I)
# Versions before the python3 rewrite read the prompt with jq; this stands in where jq is missing.
JQ_SHIM = ('#!/usr/bin/env python3\nimport json, sys\np = json.load(sys.stdin).get("prompt")\n'
           'print(p if isinstance(p, str) else "")\n')


def typed_prompts(path):
    seen = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line).get("display")
            except (ValueError, AttributeError):
                continue
            if isinstance(d, str) and d.strip() and not d.lstrip().startswith("!"):
                seen.setdefault(d, None)  # first occurrence order, no repeats
    return list(seen)


def fires(hook, prompt, env):
    p = subprocess.run(["bash", hook], input=json.dumps({"prompt": prompt}), capture_output=True,
                       text=True, env=env, timeout=30)
    return "[handoff-reminder]" in p.stdout


def replay(hooks_dir, name, prompts, env):
    """Whether each prompt fires the hook in hooks_dir: through the module's classify() when that
    version has one, else through the shell hook, one bash per prompt."""
    module = os.path.join(hooks_dir, os.path.basename(MODULE))
    if os.path.exists(module):
        spec = importlib.util.spec_from_file_location(name, module)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return [mod.classify(p) for p in prompts]
    hook = os.path.join(hooks_dir, os.path.basename(HOOK))
    with ThreadPoolExecutor(12) as ex:
        return list(ex.map(lambda p: fires(hook, p, env), prompts))


def show(ref, path):
    """path's content at ref, or None when it doesn't exist there."""
    p = subprocess.run(["git", "-C", REPO, "show", f"{ref}:{path}"], capture_output=True, text=True)
    return None if p.returncode else p.stdout


def flat(prompt, width=140):
    return " ".join(prompt.split())[:width]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--against", default="main", help="git ref to compare with (default: main)")
    ap.add_argument("--all", action="store_true", help="also list every prompt this checkout fires on")
    ap.add_argument("--history", default=os.path.expanduser("~/.claude/history.jsonl"))
    args = ap.parse_args()

    prompts = typed_prompts(args.history)
    old_hook = show(args.against, HOOK)
    if old_hook is None:
        sys.exit(f"replay_history: can't read {HOOK} at {args.against}")
    old_module = show(args.against, MODULE)  # None before the classifier moved out of the .sh
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = os.path.join(tmp, "hooks")
        os.mkdir(old_dir)
        for path, src in ((HOOK, old_hook), (MODULE, old_module)):
            if src is not None:
                with open(os.path.join(old_dir, os.path.basename(path)), "w") as f:
                    f.write(src)
        os.mkdir(os.path.join(tmp, "bin"))
        jq = os.path.join(tmp, "bin", "jq")
        with open(jq, "w") as f:
            f.write(JQ_SHIM)
        os.chmod(jq, os.stat(jq).st_mode | stat.S_IXUSR)
        env = {**os.environ, "PATH": os.path.join(tmp, "bin") + os.pathsep + os.environ.get("PATH", "")}
        before = replay(old_dir, "handoff_reminder_old", prompts, env)
        after = replay(os.path.join(REPO, "hooks"), "handoff_reminder_new", prompts, env)

    print(f"{len(prompts)} typed prompts. {args.against} fires on {sum(before)}, "
          f"this checkout on {sum(after)}.")
    print(f"\n-- disagreements ({args.against}, this checkout):")
    for p, b, a in zip(prompts, before, after):
        if b != a:
            print(f"   {'1' if b else '.'}{'1' if a else '.'}  {flat(p)}")
    print("\n-- near-misses (18 words or fewer, a wrap-up word, neither fires):")
    for p, b, a in zip(prompts, before, after):
        if not (b or a) and len(p.split()) <= 18 and NEAR.search(p):
            print(f"      {flat(p)}")
    if args.all:
        print("\n-- every fire in this checkout:")
        for p, a in zip(prompts, after):
            if a:
                print(f"      {flat(p)}")


if __name__ == "__main__":
    main()
