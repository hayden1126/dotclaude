#!/usr/bin/env python3
"""merge-settings.py: print the baseline settings.json with a machine overlay merged in.

setup.sh copies settings.json into ~/.claude/ (see the note there), so anything added to the
live copy by hand is lost on the next run. What belongs to one machine and not to this repo
goes in ~/.claude/settings.machine.json instead: hooks for local scripts, excludedCommands for
local tools. setup.sh installs baseline + overlay.

Usage: merge-settings.py BASELINE [OVERLAY]
  Prints the merged JSON. A missing OVERLAY prints BASELINE byte for byte. An overlay that isn't
  a JSON object, or doesn't parse, exits 1 and prints nothing, so setup.sh stops before it
  touches the live file.

Merge rule: objects merge key by key; lists concatenate, dropping any overlay item already
present (so hooks groups and excludedCommands entries append); any other value in the
overlay replaces the baseline's.
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


def main(argv):
    if len(argv) not in (2, 3):
        sys.stderr.write(__doc__)
        return 2
    with open(argv[1]) as f:
        text = f.read()
    if len(argv) == 2 or not os.path.exists(argv[2]):
        sys.stdout.write(text)  # verbatim, so a machine without an overlay installs the file as is
        return 0
    try:
        with open(argv[2]) as f:
            overlay = json.load(f)
    except ValueError as e:
        sys.stderr.write(f"merge-settings: {argv[2]} does not parse: {e}\n")
        return 1
    if not isinstance(overlay, dict):
        sys.stderr.write(f"merge-settings: {argv[2]} must be a JSON object\n")
        return 1
    json.dump(merge(json.loads(text), overlay), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
