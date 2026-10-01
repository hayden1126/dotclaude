#!/usr/bin/env python3
"""merge-settings.py: print the baseline settings.json with a machine overlay merged in.

setup.sh copies settings.json into ~/.claude/ (see the note there), so anything added to the
live copy by hand is lost on the next run. What belongs to one machine and not to this repo
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
still takes the baseline's value; each such override is named on stderr, so a reset is never
silent. Move a value into the overlay to keep it. Only top-level keys are kept, so a key the
baseline drops on purpose must be removed from live machines by hand.
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
    if not keep and not (overlay_path and os.path.exists(overlay_path)):
        sys.stdout.write(text)  # verbatim, so a machine without an overlay installs the file as is
        return 0
    out = merge(base, overlay)
    if keep:
        sys.stderr.write(f"merge-settings: kept the live-only keys {', '.join(sorted(keep))}\n")
    reset = sorted(k for k in live if k in out and live[k] != out[k] and k != "hooks"
                   and not isinstance(out[k], (dict, list)))
    if reset:
        sys.stderr.write("merge-settings: the baseline resets "
                         + ", ".join(f"{k} ({live[k]!r} -> {out[k]!r})" for k in reset)
                         + "; put a value in settings.machine.json to keep it\n")
    json.dump(dict(out, **keep), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
