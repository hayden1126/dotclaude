#!/usr/bin/env python3
"""merge-settings.py: print the baseline settings.json with a machine overlay merged in.

setup.sh copies settings.json into ~/.claude/ (see the note there), so a value added by hand to
a key the baseline sets is lost on the next run. What belongs to one machine and not to this repo
goes in ~/.claude/settings.machine.json instead: hooks for local scripts, excludedCommands for
local tools. setup.sh installs baseline + overlay.

Usage: merge-settings.py BASELINE [OVERLAY [LIVE]]
  Prints the merged JSON. A missing OVERLAY (and nothing to keep from LIVE) prints BASELINE byte
  for byte. An overlay or live file that isn't a JSON object, or doesn't parse, exits 1 and
  prints nothing, so setup.sh stops before it touches the live file.

Merge rule: objects merge key by key; lists concatenate, dropping any overlay item already
present (so hooks groups and excludedCommands entries append); any other value in the
overlay replaces the baseline's.

LIVE is the installed copy about to be replaced. Every top-level key that neither the baseline
nor the overlay sets belongs to the machine (what /config, /model and auto mode write there:
autoMode, model, modelSettings and the like), so it is kept as is. A key the baseline does set
still takes the baseline's value, and stderr names each one that changes (a scalar with both
values, an object or list by name) plus every live hook command that is dropped, so a reset is
never silent. Move a value into the overlay to keep it. Only top-level keys are kept, so a key
the baseline drops on purpose must be removed from live machines by hand.
"""
import json
import os
import sys


def merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = merge(base[k], v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(over, list):
        out = list(base)
        for item in over:
            if item not in out:
                out.append(item)
        return out
    return over


def commands(hooks):
    """Every hook command string in a settings `hooks` object."""
    out = set()
    for groups in (hooks or {}).values() if isinstance(hooks, dict) else ():
        for group in groups if isinstance(groups, list) else ():
            for h in (group.get("hooks") or []) if isinstance(group, dict) else ():
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    out.add(h["command"])
    return out


def read_object(path, what):
    """The JSON object at path; {} for a missing or empty file; None (with a message) if bad."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            text = f.read()
        obj = json.loads(text) if text.strip() else {}
    except (OSError, ValueError) as e:
        sys.stderr.write(f"merge-settings: {what} {path} does not parse: {e}\n")
        return None
    if not isinstance(obj, dict):
        sys.stderr.write(f"merge-settings: {what} {path} must be a JSON object\n")
        return None
    return obj


def main(argv):
    if len(argv) not in (2, 3, 4):
        sys.stderr.write(__doc__)
        return 2
    with open(argv[1]) as f:
        text = f.read()
    overlay_path = argv[2] if len(argv) > 2 else None
    overlay = read_object(overlay_path, "overlay")
    live = read_object(argv[3] if len(argv) > 3 else None, "live settings")
    if overlay is None or live is None:
        return 1
    base = json.loads(text)
    keep = {k: v for k, v in live.items() if k not in base and k not in overlay}
    verbatim = not keep and not (overlay_path and os.path.exists(overlay_path))
    out = base if verbatim else merge(base, overlay)
    if keep:
        sys.stderr.write(f"merge-settings: kept the live-only keys {', '.join(sorted(keep))}\n")
    report_resets(live, out)  # on the verbatim path too, so a reset is never silent
    if verbatim:
        sys.stdout.write(text)  # verbatim, so a machine without an overlay installs the file as is
        return 0
    json.dump(dict(out, **keep), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def report_resets(live, out):
    """Name on stderr each live value the installed file `out` changes, and each live hook
    command it drops."""
    changed = sorted(k for k in live if k in out and k != "hooks" and live[k] != out[k])
    if changed:
        sys.stderr.write("merge-settings: the baseline resets "
                         + ", ".join(f"{k} ({live[k]!r} -> {out[k]!r})"
                                     if not isinstance(out[k], (dict, list)) else k
                                     for k in changed)
                         + "; put a value in settings.machine.json to keep it\n")
    # Hooks are compared by command, since the overlay reorders hook groups harmlessly.
    lost = sorted(commands(live.get("hooks")) - commands(out.get("hooks")))
    if lost:
        sys.stderr.write("merge-settings: these live hook commands are not in the baseline or "
                         "the overlay and are dropped: " + "; ".join(lost) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
