#!/usr/bin/env python3
"""Check the cram order (08-practice step 7, FB-157), from the hub root.

  cram_check.py [practice/cram-order.md] [--notes _build/notes.html] [--plain]

The cram order is templates/cram-order.md.tmpl filled: a `# Cram order: <exam>` title, an
`**Out of time?**` line linking at least one Must-know list (`#sec-N-must-know`), tiers
`## Tier N: <name> (M min)` numbered from 1, an intro line before them naming the total
(`<total> minutes in <N> tiers`), rows `K. [§x.y Title](URL#id) (m min): the one thing`
numbered from 1 across the tiers, a `**Skip:**` line and a last `## Tonight` section with at
least one `- ` item. It fails, naming the line, when a tier's minutes aren't its rows' sum or the
intro's total and tier count aren't the tiers' (run B's two copies drifted apart on exactly
this), a tier has no rows, Tonight has no item, a row or tier is out of order or off the format
or outside a tier, a row repeats a section, another heading appears, a notes link's id isn't an
id in the assembled notes page, the notes links don't share one https:// base (the published
page), or a `{{` placeholder is left.
A notes link is any `](URL#id)` on any line, a title in double quotes after the URL allowed;
the mock line links the mock page with no `#id`, so it isn't one. A link target holding a `#` in
any other form (angle brackets, a title in single quotes or parentheses), a link split across
lines, a raw <a> tag, a bare URL with a `#`, reference-style links and autolinks are refused, and
so is a reading row written as a bullet or indented.

With --plain, for plain-text notes (04-write step 6: no notes page, cross-references as text),
a row names its section as text, `K. §x.y Title (m min): the one thing`, the Out of time line
names the Must-know lists, no notes link is allowed and no notes page is read; every other check
holds.

Exit 0 with a CRAM OK line, 1 on any failure, 2 when a file is missing or isn't UTF-8. Stdlib
only."""
import argparse
import html.parser
import os
import re
import sys

TITLE = re.compile(r"^# Cram order: \S")
TIER = re.compile(r"^## Tier (\d+): (.+) \((\d+) min\)$")
ROW = re.compile(r"^(\d+)\. \[§[\d.]+ [^\]]+\]\([^)\s#]*#([^)\s]+)\) \((\d+) min\): \S.*$")
PLAIN_ROW = re.compile(r"^(\d+)\. (§[\d.]+) [^\[\]]+? \((\d+) min\): \S.*$")
TARGET = re.compile(r"\]\(([^)]*)\)")
NOTES_LINK = re.compile(r"""^\s*([^\s#<>"'()]*)#([^\s#<>"'()]+)(?:\s+"[^"]*")?\s*$""")
OTHER_LINK = re.compile(r"\]\[[^\]]*\]|^\s*\[[^\]]+\]:\s*\S|(?<!\]\()<https?://[^>\s]+>")
INTRO = re.compile(r"\b(\d+) minutes in (\d+) tiers?\b")


class Ids(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "id" and v:
                self.ids.add(v)


def notes_links(t):
    """[(base, id)] for the line's notes links, and what would hide one from that check: a link
    target holding a # in another form (angle brackets, a title in single quotes or parentheses),
    a link split across lines, a raw <a> tag, a bare URL with a #."""
    found, odd = [], []
    for target in TARGET.findall(t):
        if "#" in target:
            m = NOTES_LINK.match(target)
            if m:
                found.append(m.groups())
            else:
                odd.append(target)
    rest = TARGET.sub("]", t)
    if "](" in rest:
        odd.append("a link split across lines")
    if re.search(r"<a\b", rest, re.I):
        odd.append("a raw <a> tag")
    if re.search(r"(?<!<)https?://\S*#", rest):
        odd.append("a bare URL")
    return found, odd


def check(lines, ids, plain=False):
    """(problems, summary) for the cram order's lines against the notes page's ids; with plain,
    for plain-text notes, whose rows name their section as text."""
    row_re, row_form = (PLAIN_ROW, "K. §x.y Title (m min): the one thing") if plain else \
        (ROW, "K. [§x.y Title](URL#id) (m min): the one thing")
    bad, links, tiers, rows, seen = [], [], [], 0, {}
    section, out_of_time, skip, intro, tonight = None, False, False, None, 0
    if not lines or not TITLE.match(lines[0][1]):
        bad.append(f"{lines[0][0] if lines else 1}: the file starts with its # Cram order: <exam> title")
    for k, (n, t) in enumerate(lines):
        if "{{" in t:
            bad.append(f"{n}: a {{{{ placeholder is left")
        found, odd = notes_links(t)
        links += [(n, base, i) for base, i in found]
        if plain and found:
            bad.append(f"{n}: a notes link, with plain-text notes: name the section as text, §x.y Title")
        if odd:
            bad.append(f"{n}: a notes link written ({odd[0]}): write [text](URL#id), a title only "
                       f'in double quotes')
        if OTHER_LINK.search(t):
            bad.append(f"{n}: a reference-style link or an autolink: write [text](URL#id)")
        if not tiers and intro is None and INTRO.search(t):
            intro = (n, int(INTRO.search(t).group(1)), int(INTRO.search(t).group(2)))
        if t.startswith("**Out of time?**"):
            out_of_time = True
            if plain and "Must-know" not in t:
                bad.append(f"{n}: the Out of time line names no Must-know list")
            elif not plain and not any(i.endswith("-must-know") for _, i in found):
                bad.append(f"{n}: the Out of time line links no Must-know list (#sec-N-must-know)")
            continue
        if t.startswith("**Skip:**"):
            skip = True
        if t.startswith("#") and k:
            m = TIER.match(t)
            if m:
                if section == "tonight":
                    bad.append(f"{n}: a tier after ## Tonight")
                if int(m.group(1)) != len(tiers) + 1:
                    bad.append(f"{n}: tier {m.group(1)} where tier {len(tiers) + 1} belongs")
                tiers.append({"line": n, "minutes": int(m.group(3)), "rows": []})
                section = "tier"
            elif t.strip() == "## Tonight":
                section = "tonight"
            else:
                bad.append(f"{n}: a heading that is neither ## Tier N: <name> (M min) nor ## Tonight")
                section = None
            continue
        if section == "tonight" and re.match(r"^- \S", t):
            tonight += 1
        if re.match(r"^\d+\. ", t) and section == "tier":
            m = row_re.match(t)
            if not m:
                bad.append(f"{n}: a row is {row_form}")
                continue
            rows += 1
            if int(m.group(1)) != rows:
                bad.append(f"{n}: row {m.group(1)} where row {rows} belongs")
            name = m.group(2) if plain else f"#{m.group(2)}"
            if name in seen:
                bad.append(f"{n}: {name} again (line {seen[name]}): read each section once")
            seen.setdefault(name, n)
            tiers[-1]["rows"].append(int(m.group(3)))
        elif row_re.match(t):
            bad.append(f"{n}: a reading row outside a tier")
        elif section == "tier" and (found or odd or "§" in t) and re.match(r"^\s*([-*+]|\d+\.)\s", t):
            bad.append(f"{n}: a row is {row_form}, numbered and unindented")
        elif section == "tier" and re.search(r"\(\d+ min\)", t):
            bad.append(f"{n}: a row is {row_form}, numbered `K.`")
    if not tiers:
        bad.append("no ## Tier N: <name> (M min) heading")
    for tier in tiers:
        got = sum(tier["rows"])
        if not tier["rows"]:
            bad.append(f"{tier['line']}: a tier with no rows")
        elif got != tier["minutes"]:
            bad.append(f"{tier['line']}: the tier says {tier['minutes']} min, its rows sum to {got}")
    total = sum(t["minutes"] for t in tiers)
    if intro is None:
        bad.append("no intro line naming the total and the tiers (<total> minutes in <N> tiers)")
    elif (intro[1], intro[2]) != (total, len(tiers)):
        bad.append(f"{intro[0]}: the intro says {intro[1]} minutes in {intro[2]} tiers, the tiers make "
                   f"{total} minutes in {len(tiers)}")
    if not out_of_time:
        bad.append("no **Out of time?** line")
    if not skip:
        bad.append("no **Skip:** line (write **Skip:** nothing, when nothing is skipped)")
    if section != "tonight":
        bad.append("the last section is ## Tonight")
    elif not tonight:
        bad.append("## Tonight has no - item")
    bases = sorted({base for _, base, _ in links})
    if len(bases) > 1:
        bad.append(f"the notes links use {len(bases)} bases ({', '.join(b or '(none)' for b in bases)}): one, "
                   f"the published notes page")
    elif bases and not bases[0].startswith("https://"):
        bad.append(f"the notes links' base {bases[0] or '(none)'} isn't the published page's https:// URL")
    bad += [f"{n}: #{i} isn't an id in the notes page" for n, _, i in links if i not in ids]
    tail = "sections named as text" if plain else f"{len(links)} links into the notes"
    return bad, f"{len(tiers)} tiers, {rows} rows, {total} min; {tail}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the cram order (08-practice).")
    ap.add_argument("cram", nargs="?", default=os.path.join("practice", "cram-order.md"))
    ap.add_argument("--notes", default=os.path.join("_build", "notes.html"))
    ap.add_argument("--plain", action="store_true",
                    help="plain-text notes (04-write step 6): no notes page; rows name their section as text")
    args = ap.parse_args(argv)
    texts = []
    for path in (args.cram,) if args.plain else (args.cram, args.notes):
        if not os.path.isfile(path):
            print(f"cram_check: no {path}", file=sys.stderr)
            return 2
        try:
            with open(path, encoding="utf-8") as f:
                texts.append(f.read())
        except UnicodeDecodeError:
            print(f"cram_check: {path} isn't UTF-8 text", file=sys.stderr)
            return 2
    lines = list(enumerate(texts[0].splitlines(), 1))
    while lines and not lines[0][1].strip():
        lines.pop(0)
    parser = Ids()
    if not args.plain:
        try:
            parser.feed(texts[1])
        except (AssertionError, NotImplementedError):  # html.parser's on a malformed <![ (before 3.10: the latter)
            print(f"cram_check: {args.notes}: a <![ section html.parser can't read", file=sys.stderr)
            return 2
    bad, summary = check(lines, parser.ids, args.plain)
    for b in bad:
        print(f"cram_check: {args.cram}:{b}" if b[0].isdigit() else f"cram_check: {args.cram}: {b}",
              file=sys.stderr)
    if bad:
        return 1
    print(f"CRAM OK: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
