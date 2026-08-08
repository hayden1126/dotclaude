#!/usr/bin/env python3
"""Regression gate: run this skill's tooling against a reference deck, read-only.

Usage: python3 parity_check.py --ref-deck PATH [--config PATH]
                               [--capture] [--goldens FILE] [--json]

The reference deck is a real deck built by an earlier, deck-specific version of
these tools. It is NOT migrated and NOT written to: no deck.toml is created
there, `build --check` stitches into memory, and packaging is redirected to a
temp directory. Every write path is asserted before it runs.

Goldens are CAPTURED BY THIS TOOL on a known-good run (`--capture`), never
transcribed from prose. The reference deck's own review record states its
package delta as 2246; the measured byte delta is 2248 (2246 is the *character*
delta). A hand-copied constant would have failed this harness on day one for a
reason nobody could find.

Run this green before editing any script in this skill.

Stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deckcfg  # noqa: E402

SKILL = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
DEFAULT_GOLDENS = SKILL / "tests" / "parity" / "goldens.json"
DEFAULT_CONFIG = SKILL / "tests" / "parity" / "bella.deck.toml"


def run(argv: list[str]) -> tuple[int, str]:
    result = subprocess.run([sys.executable, *argv], capture_output=True, text=True, timeout=600)
    return result.returncode, result.stdout + result.stderr


def snapshot(root: pathlib.Path) -> dict[str, str]:
    """Content digest of every file under root, so any write is detectable."""
    digests = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.parts:
            digests[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def collect(ref: pathlib.Path, config: pathlib.Path, workdir: pathlib.Path) -> dict:
    """Every observation the gate asserts on. Pure measurement, no comparison."""
    facts: dict = {}

    # --- stitch, in memory
    code, out = run([str(SCRIPTS / "build.py"), str(ref), "--config", str(config),
                     "--check", "--json"])
    payload = json.loads(out.strip().splitlines()[-1])
    facts["build"] = {"rows": payload["rows"], "built": payload["built"],
                      "sha256": payload["sha256"], "would_change": payload["would_change"],
                      "exit": code}

    # --- lint
    code, out = run([str(deckcfg.DEFAULTS["env.fonttools_python"])] and
                    [str(SCRIPTS / "lint.py"), str(ref), "--config", str(config)])
    tail = re.search(r"lint: (\d+) errors, (\d+) warnings, (\d+) FLAG", out)
    flags = sorted(re.findall(r"^  FLAG (\S+ \S+) \[([^\]]+)\]", out, re.M))
    facts["lint"] = {
        "errors": int(tail.group(1)) if tail else -1,
        "warnings": int(tail.group(2)) if tail else -1,
        "flag_count": int(tail.group(3)) if tail else -1,
        "flags": [f"{where} [{what}]" for where, what in flags],
        "exit": code,
    }

    # --- package, redirected out of the reference tree
    site = workdir / "site"
    code, out = run([str(SCRIPTS / "package.py"), str(ref), "--config", str(config),
                     "--check", "--json"])
    facts["package_check"] = json.loads(out.strip().splitlines()[-1])
    code, out = run([str(SCRIPTS / "package.py"), str(ref), "--config", str(config),
                     "--out", str(site), "--no-zip", "--json"])
    facts["package"] = {"exit": code}
    if site.exists():
        files = sorted(str(p.relative_to(site)) for p in site.rglob("*") if p.is_file())
        facts["package"]["file_count"] = len(files)
        facts["package"]["top_level"] = sorted({f.split("/")[0] for f in files})
        shipped = site / "index.html"
        facts["package"]["shipped_sha256"] = hashlib.sha256(shipped.read_bytes()).hexdigest()

    # --- shipped font faces, if the reference deck has any
    fonts = sorted((ref / "fonts").glob("*.woff2"))
    facts["fonts"] = {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                               "bytes": p.stat().st_size} for p in fonts}
    return facts


def compare(observed: dict, golden: dict, path: str = "") -> list[str]:
    diffs: list[str] = []
    for key in sorted(set(golden) | set(observed)):
        here = f"{path}.{key}" if path else key
        if key not in observed:
            diffs.append(f"{here}: missing from this run (golden {golden[key]!r})")
        elif key not in golden:
            diffs.append(f"{here}: new in this run ({observed[key]!r}), not in the golden")
        elif isinstance(golden[key], dict) and isinstance(observed[key], dict):
            diffs.extend(compare(observed[key], golden[key], here))
        elif golden[key] != observed[key]:
            diffs.append(f"{here}: golden {golden[key]!r} != observed {observed[key]!r}")
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description="Reference-deck regression gate")
    parser.add_argument("--ref-deck", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--goldens", default=str(DEFAULT_GOLDENS))
    parser.add_argument("--capture", action="store_true",
                        help="record this run as the golden (only on a known-good tree)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ref = pathlib.Path(args.ref_deck).resolve()
    if not ref.is_dir():
        deckcfg.bail(f"{ref} is not a directory")
    config = pathlib.Path(args.config).resolve()
    if not config.exists():
        deckcfg.bail(f"{config} does not exist")
    if config.is_relative_to(ref):
        deckcfg.bail("the parity config must live outside the reference deck; "
                     "the point is that the reference tree stays untouched")

    before = snapshot(ref)
    with tempfile.TemporaryDirectory(prefix="deckkit-parity-") as tmp:
        observed = collect(ref, config, pathlib.Path(tmp))
    after = snapshot(ref)

    touched = sorted(set(before) ^ set(after)) + \
              sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    if touched:
        print("FAIL: the reference deck was modified. That is the one thing this "
              "harness must never do.", file=sys.stderr)
        for rel in touched[:20]:
            print(f"  {rel}", file=sys.stderr)
        return deckcfg.EXIT_FAIL

    goldens_path = pathlib.Path(args.goldens)
    if args.capture:
        goldens_path.parent.mkdir(parents=True, exist_ok=True)
        goldens_path.write_text(json.dumps(observed, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
        print(f"captured goldens -> {goldens_path}")
        print(f"  build   {observed['build']['built']}/{observed['build']['rows']} rows, "
              f"sha256 {observed['build']['sha256'][:16]}")
        print(f"  lint    {observed['lint']['errors']} errors, "
              f"{observed['lint']['warnings']} warnings, {observed['lint']['flag_count']} FLAG")
        print(f"  package {observed['package'].get('file_count', 0)} files, "
              f"{observed['package_check']['note_blocks_stripped']} notes stripped, "
              f"{observed['package_check']['byte_delta']} byte delta")
        print(f"  fonts   {len(observed['fonts'])} woff2 faces")
        return deckcfg.EXIT_OK

    if not goldens_path.exists():
        deckcfg.bail(f"{goldens_path} does not exist; run once with --capture on a "
                     f"known-good tree")
    golden = json.loads(goldens_path.read_text(encoding="utf-8"))
    diffs = compare(observed, golden)

    if args.json:
        print(json.dumps({"diffs": diffs, "observed": observed}, indent=2))
    else:
        print(f"parity against {ref}")
        print(f"  reference tree: unmodified ({len(before)} files verified)")
        print(f"  build   {observed['build']['built']}/{observed['build']['rows']} rows, "
              f"sha256 {observed['build']['sha256'][:16]}, "
              f"stale={observed['build']['would_change']}")
        print(f"  lint    {observed['lint']['errors']} errors, "
              f"{observed['lint']['warnings']} warnings, "
              f"{observed['lint']['flag_count']} FLAG")
        print(f"  package {observed['package'].get('file_count', 0)} files, "
              f"{observed['package_check']['note_blocks_stripped']} notes stripped, "
              f"{observed['package_check']['byte_delta']} byte delta")
        print(f"  fonts   {len(observed['fonts'])} woff2 faces")
        if diffs:
            print(f"\n{len(diffs)} regression(s):")
            for diff in diffs:
                print(f"  {diff}")
        else:
            print("\nparity: green")
    return deckcfg.EXIT_FAIL if diffs else deckcfg.EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except deckcfg.ConfigError as exc:
        deckcfg.bail(str(exc))
