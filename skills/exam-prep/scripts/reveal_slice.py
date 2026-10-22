#!/usr/bin/env python3
"""Map and slice a reveal.js deck saved as raw HTML (fetched with curl, never WebFetch).

  reveal_slice.py map <deck.html>
      One line per slide: its reveal fragment (#/h or #/h/v), its id and the start of its text.
  reveal_slice.py slice <deck.html> --from H --to H [--skip H,H] [--base URL] -o <out>
      Writes the raw HTML of horizontal slides H..H (inclusive, with every vertical slide under
      them) to <out> (its directory is created), each under a header naming the fragment an
      extract cites.
  reveal_slice.py images <deck.html> --base URL -o <out.tsv>
      Lists every image the slides use (img src or data-src, svg image href, a section's
      data-background-image, object data, embed src), one line each: the src as written, its URL
      resolved against the deck's URL (path and query percent-encoded, so no `{}[]` reaches
      curl), and its local path in the deck's own folder, <deck dir>/<deck name>_files/. An image
      under the deck's directory keeps its relative path there; one elsewhere goes under
      _abs/<host>/. A data: URI, a non-http URL, a path that would leave the folder, a control
      character anywhere in a row (it would split the TSV into rows the deck chose) and a path
      holding `{}[]#` (curl's globs) are skipped with a warning. Fetch with `curl -g`.

Slides are the <section> elements inside the element whose class list holds `slides` (the
container ends where its tag closes, counted by tag name). A top-level section that holds sections
is a vertical stack: its children are #/h/0, #/h/1 and so on, as reveal numbers them. A section
with data-visibility="hidden" gets no number, since reveal removes it at load. A data-markdown
section is split into slides by reveal's markdown plugin at load time, which raw HTML can't show,
so the script warns that fragments from there on may not match the live deck. Nesting is read
from section tags alone, so unclosed <p> or <li> tags don't matter. Section tags inside <script>
or <style> are not slides: the parser skips their content. Stdlib only."""
import argparse
import html.parser
import os
import posixpath
import re
import sys
import urllib.parse

# A tab or newline in a TSV field would split it into rows the deck chose (a path like CLAUDE.md).
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# What stays unencoded in a URL path or query: the RFC 3986 characters, and `%` so an encoded src
# isn't encoded twice. Never `{}[]`: curl globs them, and its `#N` in an output name takes the
# glob's text, which can climb out of the folder (probed with curl 8.5).
URL_SAFE = "/%:@!$&'()*+,;=-._~"
QUERY_SAFE = URL_SAFE + "?"
# A character curl would glob in a URL or substitute in an output name, refused in a path.
GLOB = re.compile(r"[{}\[\]#]")


class Slide:
    def __init__(self, start, attrs):
        self.start = start
        self.end = None
        self.id = attrs.get("id")
        self.hidden = attrs.get("data-visibility") == "hidden"
        self.markdown = "data-markdown" in attrs
        self.children = []
        self.text = []


class Deck(html.parser.HTMLParser):
    """The deck's top-level sections, each with its character span in the source."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_starts = [0] + [m.end() for m in re.finditer(r"\n", source)]
        self.container = None  # the `slides` element's tag, once found
        self.depth = 0  # open tags of that name, the container's own included
        self.images = []  # image sources inside the container, in order
        self.stack = []
        self.tops = []
        self.feed(source)
        self.close()

    def here(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.container is None:
            if "slides" in (a.get("class") or "").split():
                self.container, self.depth = tag, 1
            return
        if not self.depth:
            return
        if tag in ("img", "image", "source", "object", "embed", "section"):
            if tag == "section":
                src = a.get("data-background-image")
            elif tag == "object":
                src = a.get("data")
            else:
                src = a.get("src") or a.get("data-src") or a.get("href") or a.get("xlink:href")
            if src and src.strip():
                self.images.append(src.strip())
        if tag == self.container:
            self.depth += 1
        elif tag == "section":
            slide = Slide(self.here(), a)
            (self.stack[-1].children if self.stack else self.tops).append(slide)
            self.stack.append(slide)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == self.container:
            self.depth -= 1
        elif tag == "section" and self.stack:
            close = self.source.find(">", self.here())
            self.stack.pop().end = close + 1 if close >= 0 else len(self.source)

    def handle_data(self, data):
        if self.stack and data.strip():
            self.stack[-1].text.append(data.strip())


def slides(source):
    """[(fragment, slide)] in reveal order."""
    deck = Deck(source)
    if deck.container is None:
        raise SystemExit("no element with class `slides`: is this a reveal.js deck?")
    for top in deck.tops:
        for s in [top] + top.children:
            if s.end is None:
                raise SystemExit(f"the section starting at character {s.start} has no closing "
                                 "</section> inside the slides container")
    out = []
    for h, top in enumerate(t for t in deck.tops if not t.hidden):
        children = [c for c in top.children if not c.hidden]
        if children:
            out += [(f"#/{h}/{v}", child) for v, child in enumerate(children)]
        else:
            out.append((f"#/{h}", top))
    for frag, s in out:
        if s.markdown:
            print(f"warning: slide {frag} is a data-markdown section, which reveal splits into "
                  "slides at load time: fragments from here on may not match the live deck; "
                  "check them in a browser", file=sys.stderr)
    return out


def horizontal(frag):
    return int(frag.split("/")[1])


def cmd_map(args, source):
    rows = slides(source)
    print(f"TOTAL horizontal slides: {len({horizontal(f) for f, _ in rows})} | "
          f"slides: {len(rows)}")
    for frag, s in rows:
        text = re.sub(r"\s+", " ", " ".join(s.text))[:90]
        print(f"{frag}\t{s.id or ''}\t{text}")


def image_rows(source, base, folder):
    """[(src, url, local path)] for the deck's images, and [warnings]."""
    deck = Deck(source)
    if deck.container is None:
        raise SystemExit("no element with class `slides`: is this a reveal.js deck?")
    here = urllib.parse.urljoin(base, ".")
    rows, warnings, seen = [], [], set()
    for src in deck.images:
        if src in seen:
            continue
        seen.add(src)
        if CONTROL.search(src):
            warnings.append(f"skipped {src[:60]!r}: a control character in its src")
            continue
        url = urllib.parse.urljoin(base, src)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            warnings.append(f"skipped {src[:60]}: not an http(s) URL")
            continue
        url = urllib.parse.urlunsplit(parts._replace(
            path=urllib.parse.quote(parts.path, safe=URL_SAFE),
            query=urllib.parse.quote(parts.query, safe=QUERY_SAFE), fragment=""))
        clean = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        if clean.startswith(here):
            rel = clean[len(here):]
        else:
            rel = f"_abs/{parts.netloc}{parts.path}"
        rel = posixpath.normpath(urllib.parse.unquote(rel))
        if rel in (".", "") or rel.startswith(("/", "..")) or "/../" in f"/{rel}/":
            warnings.append(f"skipped {src[:60]}: its path would leave {folder}/")
            continue
        if CONTROL.search(url) or CONTROL.search(rel):
            warnings.append(f"skipped {src[:60]}: a control character in its URL or path")
            continue
        if GLOB.search(rel):
            warnings.append(f"skipped {src[:60]}: a character curl globs ({{}}[]#) in its path")
            continue
        rows.append((src, url, f"{folder}/{rel}"))
    return rows, warnings


def cmd_images(args, source):
    stem = os.path.splitext(os.path.basename(args.deck))[0]
    folder = os.path.join(os.path.dirname(args.deck), f"{stem}_files")
    rows, warnings = image_rows(source, args.base, folder)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.writelines("\t".join(row) + "\n" for row in rows)
    print(f"wrote {args.out}: {len(rows)} images, {len(warnings)} skipped")


def cmd_slice(args, source):
    skip = {int(x) for x in args.skip.split(",") if x.strip()}
    chunks = []
    for frag, s in slides(source):
        if not args.first <= horizontal(frag) <= args.last or horizontal(frag) in skip:
            continue
        chunks.append(f"<!-- ===== SLIDE {frag} (cite as {args.base}{frag}) ===== -->\n"
                      + source[s.start:s.end])
    if not chunks:
        raise SystemExit(f"no slides in #/{args.first} to #/{args.last}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n\n".join(chunks) + "\n")
    print(f"wrote {args.out}: {len(chunks)} slides, {sum(len(c) for c in chunks)} chars")


def main(argv=None):
    p = argparse.ArgumentParser(description="Map and slice a reveal.js deck's raw HTML.")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="list every slide with its fragment")
    m.add_argument("deck")
    s = sub.add_parser("slice", help="write a range of slides' raw HTML")
    s.add_argument("deck")
    s.add_argument("--from", dest="first", type=int, required=True)
    s.add_argument("--to", dest="last", type=int, required=True)
    s.add_argument("--skip", default="", help="horizontal indexes to leave out, comma-separated")
    s.add_argument("--base", default="", help="the deck's URL, so headers cite <base>#/h/v")
    s.add_argument("-o", "--out", required=True)
    i = sub.add_parser("images", help="list the images the slides use, with local paths")
    i.add_argument("deck")
    i.add_argument("--base", required=True, help="the deck's URL, which relative src resolve against")
    i.add_argument("-o", "--out", required=True)
    args = p.parse_args(argv)
    with open(args.deck, encoding="utf-8") as f:
        source = f.read()
    {"map": cmd_map, "slice": cmd_slice, "images": cmd_images}[args.cmd](args, source)


if __name__ == "__main__":
    sys.exit(main())
