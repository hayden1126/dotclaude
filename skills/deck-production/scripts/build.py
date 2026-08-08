#!/usr/bin/env python3
"""Stitch slide fragments into index.html in storyboard-manifest order.

Usage: python3 build.py <deck-dir> [--check] [--urls] [--out PATH] [--json]
                                   [--allow-draft] [--config PATH]

The storyboard manifest table is authoritative for order. index.html must
contain the BUILD:SLIDES:BEGIN / BUILD:SLIDES:END markers; everything between
them is regenerated. Edit the fragments, never the generated block.

--check stitches into memory, diffs against the file on disk, and writes
nothing. That is what lets the regression harness drive a deck it must not
touch, and it doubles as the determinism assertion every phase exit needs.

Stdlib only, deliberately: this is the one tool that must run anywhere.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deckcfg  # noqa: E402

# The exact join below is byte-identity load-bearing. It is not configurable on
# purpose: a knob here buys nothing and adds a divergence axis between decks.
SLIDE_HEADER = "<!-- slide {n:02d}: {rel} -->\n"
JOIN = "\n\n"
END_INDENT = "\n    "

APPROVED_RE = re.compile(r"\bapproved\b", re.I)
UNAPPROVED_RE = re.compile(r"\b(?:un|not\s+)approved\b", re.I)


def frontmatter(text: str) -> dict[str, str]:
    """Parse a leading --- fenced block into a flat key/value map."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def storyboard_approved(text: str) -> tuple[bool, str]:
    status = frontmatter(text).get("status", "")
    if not status:
        return False, "storyboard frontmatter has no `status:` field"
    if UNAPPROVED_RE.search(status):
        return False, f"storyboard status is {status!r}"
    if APPROVED_RE.search(status):
        return True, status
    return False, f"storyboard status is {status!r}, not approved"


def manifest_rows(storyboard_text: str, fragment_dir: str) -> list[tuple[int, str]]:
    pattern = re.compile(rf"\|\s*(\d+)\s*\|\s*({re.escape(fragment_dir)}/\S+\.html)\s*\|")
    rows = [(int(m.group(1)), m.group(2)) for line in storyboard_text.splitlines()
            if (m := pattern.match(line.strip()))]
    rows.sort()
    return rows


def stitch(deck: pathlib.Path, rows, index_text: str, begin: str, end: str) -> tuple[str, list]:
    parts, missing = [], []
    for n, rel in rows:
        fragment = deck / rel
        if not fragment.exists():
            missing.append((n, rel))
            continue
        parts.append(SLIDE_HEADER.format(n=n, rel=rel)
                     + fragment.read_text(encoding="utf-8").strip())

    if begin not in index_text or end not in index_text:
        raise deckcfg.ConfigError(
            f"index.html lacks the {begin!r} / {end!r} markers"
        )
    pre, rest = index_text.split(begin, 1)
    marker_tail, post = rest.split(end, 1)
    begin_full = begin + marker_tail.split("-->", 1)[0] + "-->"
    body = JOIN.join(parts)
    return pre + begin_full + "\n" + body + END_INDENT + end + post, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    deckcfg.add_common_args(parser)
    parser.add_argument("--check", action="store_true",
                        help="diff against index.html on disk; write nothing; exit 1 on drift")
    parser.add_argument("--urls", action="store_true", help="print the per-slide URLs")
    parser.add_argument("--out", help="write the stitched index elsewhere")
    parser.add_argument("--allow-draft", action="store_true",
                        help="build from an unapproved storyboard (prints a banner)")
    args = parser.parse_args()

    cfg = deckcfg.load(args.deck, args.config)
    deck = cfg.deck
    storyboard = cfg.path("build.storyboard")
    if not storyboard.exists():
        deckcfg.bail(f"{storyboard} does not exist")
    sb_text = storyboard.read_text(encoding="utf-8")

    if cfg.get("build.require_approved_storyboard") and not args.check:
        ok, detail = storyboard_approved(sb_text)
        if not ok and not args.allow_draft:
            print(f"GATE: no fragment is built before the storyboard is approved.\n"
                  f"      {detail}\n"
                  f"      Set `status: approved` in {storyboard} frontmatter once a "
                  f"human has signed off, or pass --allow-draft for an "
                  f"infrastructure smoke test.", file=sys.stderr)
            return deckcfg.EXIT_FAIL
        if not ok and args.allow_draft:
            print("!! --allow-draft: building from an UNAPPROVED storyboard. "
                  "This output is a smoke test, not a deck.", file=sys.stderr)

    fragment_dir = cfg.get("build.fragment_dir")
    rows = manifest_rows(sb_text, fragment_dir)
    if not rows:
        deckcfg.bail(f"no manifest rows found in {storyboard} "
                     f"(expected `| N | {fragment_dir}/x.html |` table rows)")

    index = cfg.path("build.index")
    if not index.exists():
        deckcfg.bail(f"{index} does not exist; run `deckkit new` to scaffold it")

    stitched, missing = stitch(deck, rows, index.read_text(encoding="utf-8"),
                               cfg.get("build.begin_marker"), cfg.get("build.end_marker"))
    built = len(rows) - len(missing)
    digest = hashlib.sha256(stitched.encode("utf-8")).hexdigest()

    if args.check:
        current = index.read_text(encoding="utf-8")
        drifted = current != stitched
        if args.json:
            print(json.dumps({"rows": len(rows), "built": built,
                              "missing": [r for _, r in missing],
                              "sha256": digest, "would_change": drifted}))
        else:
            print(f"build --check: {built}/{len(rows)} fragments, sha256 {digest[:16]}")
            if drifted:
                diff = difflib.unified_diff(current.splitlines(keepends=True),
                                            stitched.splitlines(keepends=True),
                                            fromfile="index.html (on disk)",
                                            tofile="index.html (stitched)", n=2)
                sys.stdout.writelines(list(diff)[:200])
                print("build --check: index.html is stale; run `deckkit build`")
            else:
                print("build --check: index.html matches the fragments")
        return deckcfg.EXIT_FAIL if drifted else deckcfg.EXIT_OK

    target = pathlib.Path(args.out).resolve() if args.out else index
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stitched, encoding="utf-8")

    if args.json:
        print(json.dumps({"rows": len(rows), "built": built,
                          "missing": [r for _, r in missing],
                          "sha256": digest, "out": str(target)}))
        return deckcfg.EXIT_OK

    print(f"built {built}/{len(rows)} slides into {target}")
    for n, rel in missing:
        print(f"  MISSING s{n:02d}: {rel}")
    if args.urls:
        port = cfg.get("build.serve_port")
        position = 0
        for n, rel in rows:
            if (n, rel) not in missing:
                print(f"  s{n:02d} -> http://localhost:{port}/#/{position}")
                position += 1
    return deckcfg.EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except deckcfg.ConfigError as exc:
        deckcfg.bail(str(exc))
