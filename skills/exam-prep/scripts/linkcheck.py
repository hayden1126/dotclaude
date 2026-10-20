#!/usr/bin/env python3
"""Check the notes' cross-references (STYLE S12), from the hub root.

  linkcheck.py [--root DIR]      the Markdown notes, notes/NN-*.md, against _build/backbone.md
  linkcheck.py --html FILE       an assembled page

Markdown mode. An id is defined by a `{#id}` anchor, by a `# §N` heading with no anchor of its own
(sec-N), or by a `<!-- FIG fig-... -->` marker. Fenced code (``` or ~~~) counts for nothing. The
registry is every backticked `sec-N...`, `ex-N...` and `fig-N...` id in the backbone, plus each
lettered set written as `set-<name>-a` .. `-<last>` (its members a to last). It fails on a
`](#id)` link to an id no note defines, a registry id no note defines, an id defined twice, and a
bare `§N.M` reference to a section the backbone numbers (S12: every mention links). Headings, link
text, citations (`[W1 §2.1]`, a section of another document), code and comments don't
count, nor does a mention of the section the line sits in (a `# §N` or `## N.K` heading sets it).
Warnings, which don't fail: an id defined but not in the registry, and a bare reference to a number
the backbone doesn't have (a section left out of scope, say).

HTML mode. Every href="#id" must match exactly one id="..." in the page, and no id may repeat.

Exit 1 on any failure, 0 otherwise. Stdlib only."""
import argparse
import html.parser
import os
import re
import sys
import urllib.parse
from collections import Counter

NOTE = re.compile(r"\d+-.*\.md")
H1_SECTION = re.compile(r"^# §(\d+)(?=\s|$)(?!.*\{#)")
FENCE = re.compile(r"^\s*(```|~~~)")
ANCHOR = re.compile(r"\{#([\w-]+)\}")
FIG = re.compile(r"<!--\s*FIG\s+(fig-[\w-]+)")
LINK = re.compile(r"\]\(#([^)\s]+)\)")
REGISTRY = re.compile(r"`((?:sec|ex|fig)-\d+(?:-[\w-]+)?)`")
SET = re.compile(r"`(set-[\w-]+)-a`\s*\.\.\s*`-([a-z])`")
# What a bare reference is checked in: the line minus links, citations (a bracket that opens with a
# document id, `[W1 §2.1]`; a bare `[§3.2]` is a reference that lost its link), inline code and
# comments.
NOT_PROSE = re.compile(r"\[[^\]]*\]\([^)]*\)|\[[A-Za-z][\w.-]*\s[^\]]*\]|`[^`]*`|<!--.*?-->")
BARE = re.compile(r"§\s?(\d+(?:\.\d+)*)")
HEADING = re.compile(r"^#{1,6}\s+(?:§(\d+(?:\.\d+)*)|(\d+\.\d+(?:\.\d+)*))(?=\s|$)")
# Section numbers the backbone defines: `## §N` headings and `| N.M |` table rows.
NUMBERED = re.compile(r"^## §(\d+)\b|^\|\s*(\d+(?:\.\d+)+)\s*\|", re.M)


def numbered(backbone):
    return {a or b for a, b in NUMBERED.findall(backbone)}


def registry(backbone):
    ids = set(REGISTRY.findall(backbone))
    for base, last in SET.findall(backbone):
        ids.update(f"{base}-{chr(c)}" for c in range(ord("a"), ord(last) + 1))
    return ids


def md_mode(root):
    notes_dir = os.path.join(root, "notes")
    backbone_path = os.path.join(root, "_build", "backbone.md")
    if not os.path.isfile(backbone_path):
        print(f"linkcheck: no {backbone_path}", file=sys.stderr)
        return 2
    names = sorted(n for n in os.listdir(notes_dir) if NOTE.fullmatch(n)) \
        if os.path.isdir(notes_dir) else []
    if not names:
        print(f"linkcheck: no notes/NN-*.md under {root}", file=sys.stderr)
        return 2
    with open(backbone_path, encoding="utf-8") as f:
        backbone = f.read()
    reg, known = registry(backbone), numbered(backbone)
    defined, links, bare, stray = Counter(), [], [], []
    for name in names:
        with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
            text = f.read()
        fence, here = None, ""
        for n, line in enumerate(text.splitlines(), 1):
            m = FENCE.match(line)
            if m and (fence is None or m.group(1) == fence):
                fence = None if fence else m.group(1)
                continue
            if fence:
                continue
            defined.update(f"sec-{x}" for x in H1_SECTION.findall(line))
            defined.update(ANCHOR.findall(line))
            defined.update(FIG.findall(line))
            links += [(name, i) for i in LINK.findall(line)]
            heading = HEADING.match(line)
            if heading:
                here = heading.group(1) or heading.group(2)
            if line.lstrip().startswith("#"):
                continue
            for ref in BARE.findall(NOT_PROSE.sub("", line)):
                if ref == here or here.startswith(ref + "."):
                    continue  # the section this line is in
                (bare if ref in known else stray).append((name, n, ref))
    broken = [(f, i) for f, i in links if i not in defined]
    missing = sorted(reg - set(defined))
    dupes = sorted(i for i, n in defined.items() if n > 1)
    unknown = sorted(set(defined) - reg)
    print(f"{len(names)} files, {len(defined)} ids defined, {len(links)} links, "
          f"registry {len(reg)}")
    for f, i in broken:
        print(f"  BROKEN LINK {f}: #{i}")
    for i in missing:
        print(f"  REGISTRY ID NOT DEFINED: {i}")
    for i in dupes:
        print(f"  DUPLICATE ID: {i}")
    for f, n, ref in bare:
        print(f"  BARE REFERENCE {f}:{n}: §{ref} (make it a link)")
    for i in unknown:
        print(f"  ID NOT IN REGISTRY (allowed, check): {i}")
    for f, n, ref in stray:
        print(f"  BARE REFERENCE TO AN UNNUMBERED SECTION (allowed, check) {f}:{n}: §{ref}")
    return 1 if (broken or missing or dupes or bare) else 0


class Ids(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs = Counter(), []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "id" and v:
                self.ids[v] += 1
            elif k == "href" and v and v.startswith("#") and len(v) > 1:
                self.hrefs.append(urllib.parse.unquote(v[1:]))


def html_mode(path):
    p = Ids()
    with open(path, encoding="utf-8") as f:
        p.feed(f.read())
    p.close()
    bad = sorted({h for h in p.hrefs if p.ids[h] != 1})
    dup = sorted(i for i, n in p.ids.items() if n > 1)
    print(f"{len(p.hrefs)} in-page links, {len(p.ids)} ids; {len(bad)} unresolved; "
          f"{len(dup)} duplicate ids")
    for h in bad:
        print(f"  UNRESOLVED #{h} (defined {p.ids[h]}x)")
    for i in dup:
        print(f"  DUPLICATE id {i}")
    return 1 if (bad or dup) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the notes' cross-references (STYLE S12).")
    ap.add_argument("--root", default=".", help="the hub root (default: the current directory)")
    ap.add_argument("--html", metavar="FILE", help="check an assembled page instead")
    args = ap.parse_args(argv)
    return html_mode(args.html) if args.html else md_mode(args.root)


if __name__ == "__main__":
    sys.exit(main())
