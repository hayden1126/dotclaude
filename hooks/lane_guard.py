"""PreToolUse(Edit|Write|MultiEdit) guard for lanes records; hooks/lane-guard.sh runs it.

Two rules keep lane status single-writer and absolute (docs/lanes.md, invariants 1 and 2):
  writer    a write to a lane's <lane>/.lane/** is denied unless the session's own checkout is
            that lane, and any write under <common-dir>/lanes/ is denied: the `lane` CLI and the
            hooks write those records, never the Edit tool. Applies only in a repo with lanes
            (<common-dir>/lanes/ exists). The main checkout is a different lane like any other.
  relative  relative-identity phrases ("another session", "this session", "the other lane",
            "my lane"; lanelib.RELATIVE) are denied in the new text of any file under a .lane/,
            and of the main checkout's root STATUS.md when <common-dir>/lanes/config.toml exists.
            New text is a Write's content, or an Edit's new_string minus the phrases its
            old_string already held (a MultiEdit's edits likewise), so an edit near an old line
            still passes.

A repo with no lanes is untouched. Any failure allows the call (fail open) and is logged to
$XDG_STATE_HOME/dotclaude/lane-guard.log, as is every deny.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                                "skills", "lanes", "scripts"))
import lanelib  # noqa: E402

TOOLS = {"Edit", "Write", "MultiEdit"}


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "lane-guard.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def deny(reason, note):
    log(note)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))


def added_text(tool: str, inp: dict) -> list[str]:
    """The relative phrases this call adds to the file."""
    if tool == "Write":
        return lanelib.relative_phrases(str(inp.get("content") or ""))
    edits = inp.get("edits") if tool == "MultiEdit" else [inp]
    out = []
    for e in edits if isinstance(edits, list) else []:
        if isinstance(e, dict):
            out += lanelib.added_phrases(str(e.get("old_string") or ""),
                                         str(e.get("new_string") or ""))
    return out


def record_owner(target: str) -> str | None:
    """The checkout whose .lane/ holds target: the dir above the nearest .lane component."""
    parts = target.split(os.sep)
    for i in range(len(parts) - 1, 0, -1):
        if parts[i] == lanelib.RECORD_DIR and i < len(parts) - 1:
            return os.sep.join(parts[:i]) or os.sep
    return None


def main():
    event = json.load(sys.stdin)
    tool = event.get("tool_name")
    if tool not in TOOLS:
        return
    inp = event.get("tool_input") or {}
    raw = inp.get("file_path")
    cwd = event.get("cwd") or os.getcwd()
    if not isinstance(raw, str) or not raw:
        return
    target = os.path.realpath(os.path.join(cwd, raw))
    # The target's repo. Inside a .git dir --show-toplevel fails, so fall back to the common dir.
    repo = lanelib.resolve_path(target)
    common = repo.common_dir if repo else lanelib.common_dir_of(target)
    if common is None:
        return
    lanes_dir = os.path.join(common, lanelib.LANES)
    if not os.path.isdir(lanes_dir):
        return  # a repo with no lanes is untouched

    owner = record_owner(target)
    session = lanelib.resolve(cwd)
    here = session.toplevel if session else os.path.realpath(cwd)
    who = f"session={str(event.get('session_id'))[:8]}" + (
        f" agent={event['agent_id']}" if event.get("agent_id") else "")

    if lanelib.inside(target, lanes_dir):
        deny(f"lane-guard: {raw} is lanes data under the git common dir, which only the `lane` "
             "CLI and its hooks write. Use `lane claim`, `lane release` or `lane note`, or edit "
             "your own record in <your lane>/.lane/.",
             f"deny cli-data {who} cwd={here} path={target}")
        return
    if owner is not None and os.path.realpath(owner) != here:
        lane = repo.lane_at(owner) if repo else None
        name = f"lane {lane['id']}'s" if lane else f"{owner}'s"
        deny(f"lane-guard: {raw} is {name} record, and only that lane's own sessions write it "
             f"(this session's checkout is {here}). Note it in your own record's \"Not mine\" "
             "section, or ask Hayden to route it to that lane.",
             f"deny other-record {who} cwd={here} path={target}")
        return

    is_status = (repo is not None and repo.has_lanes
                 and target == os.path.join(repo.main, "STATUS.md"))
    if owner is None and not is_status:
        return
    if found := added_text(tool, inp):
        deny(f"lane-guard: relative identity in {raw} ({', '.join(sorted(set(found)))}). "
             f"{lanelib.RELATIVE_HINT}",
             f"deny relative {who} phrases={sorted(set(found))} path={target}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a broken guard must never block an edit
        log(f"error {type(e).__name__}: {e}")
