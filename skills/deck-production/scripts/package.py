#!/usr/bin/env python3
"""Package the deck's runtime files into a self-contained site folder + zip.

Usage: python3 package.py <deck-dir> [--out DIR] [--check] [--no-zip]
                                     [--json] [--config PATH]

Runtime is an allowlist, not an exclusion list: only what a recipient needs is
copied, so fragments, the storyboard, briefs, and review records are
structurally incapable of shipping. The folder is regenerated from scratch each
run.

Presenter notes (<aside class="notes">) are stripped from the shipped
index.html. They are speaker-view-only briefing, hidden on the face and absent
from the PDF, but they would otherwise sit in the distributable's page source.
The deck source keeps them so the presenter's speaker view still works; only
the recipient copy is scrubbed. The strip asserts none survive: a future
pattern drift must fail loudly rather than ship notes quietly.

--check reports what would ship, and the exact byte delta, without writing.

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deckcfg  # noqa: E402

# Non-greedy, DOTALL: each aside is plain text closed by </aside>. Leading
# whitespace is consumed so no blank gap is left behind.
NOTES_RE = re.compile(r'\s*<aside class="notes">.*?</aside>', re.DOTALL)
NOTES_MARKER = 'aside class="notes"'


def strip_notes(html: str) -> tuple[str, int]:
    """Remove every presenter-notes aside; refuse to ship if any remain."""
    stripped, count = NOTES_RE.subn("", html)
    if NOTES_MARKER in stripped:
        raise deckcfg.ConfigError(
            "presenter notes survived the strip: refusing to package a leaky "
            "index.html. The aside pattern has drifted from NOTES_RE."
        )
    return stripped, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    deckcfg.add_common_args(parser)
    parser.add_argument("--out", help="write the site elsewhere (default: <deck>/export/site)")
    parser.add_argument("--check", action="store_true", help="report only; write nothing")
    parser.add_argument("--no-zip", action="store_true", help="skip the archive")
    args = parser.parse_args()

    cfg = deckcfg.load(args.deck, args.config)
    deck = cfg.deck
    runtime = cfg.get("export.site.runtime")
    do_strip = cfg.get("export.site.strip_notes")

    index_name = cfg.get("build.index")
    index = deck / index_name
    if not index.exists():
        deckcfg.bail(f"{index} does not exist; run `deckkit build` first")

    source_html = index.read_text(encoding="utf-8")
    shipped_html, note_blocks = strip_notes(source_html) if do_strip else (source_html, 0)
    byte_delta = len(source_html.encode("utf-8")) - len(shipped_html.encode("utf-8"))

    present = [item for item in runtime if (deck / item).exists()]
    absent = [item for item in runtime if not (deck / item).exists()]

    if args.check:
        report = {
            "runtime_present": present,
            "runtime_absent": absent,
            "note_blocks_stripped": note_blocks,
            "notes_in_source": source_html.count(NOTES_MARKER),
            "notes_in_shipped": shipped_html.count(NOTES_MARKER),
            "byte_delta": byte_delta,
            "char_delta": len(source_html) - len(shipped_html),
            "shipped_sha256": hashlib.sha256(shipped_html.encode("utf-8")).hexdigest(),
        }
        print(json.dumps(report, indent=None if args.json else 2))
        return deckcfg.EXIT_OK

    site = pathlib.Path(args.out).resolve() if args.out else deck / "export" / "site"
    if site.exists():
        shutil.rmtree(site)           # build artifact only, always regenerated in full
    site.mkdir(parents=True)

    for item in runtime:
        src = deck / item
        if not src.exists():
            print(f"  skip {item} (absent)")
            continue
        if src.is_dir():
            shutil.copytree(src, site / item)
        elif item == index_name:
            (site / item).write_text(shipped_html, encoding="utf-8")
        else:
            shutil.copy2(src, site / item)

    if do_strip:
        print(f"  stripped {note_blocks} presenter-note block(s) from {index_name} "
              f"({byte_delta} bytes)")

    total = sum(f.stat().st_size for f in site.rglob("*") if f.is_file())
    result = {"site": str(site), "bytes": total, "note_blocks_stripped": note_blocks,
              "byte_delta": byte_delta}

    if not args.no_zip and cfg.get("export.site.zip"):
        archive_base = site.parent / f"{cfg.slug}-site"
        shutil.make_archive(str(archive_base), "zip", site)
        result["zip"] = f"{archive_base}.zip"

    if args.json:
        print(json.dumps(result))
    else:
        size_mb = total // 1024 // 1024
        print(f"packaged {site} ({size_mb}MB)" + (f" -> {result['zip']}" if "zip" in result else ""))
    return deckcfg.EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except deckcfg.ConfigError as exc:
        deckcfg.bail(str(exc))
