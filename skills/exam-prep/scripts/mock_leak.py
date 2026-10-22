#!/usr/bin/env python3
"""The leak check (08-practice, FB-154): a page the student reads before a mock holds no key.

  mock_leak.py [--no-markers] <page> practice/*-key.md

The page is a built mock page, the notes (_build/notes.html, or notes/combined.md when the notes
are plain text), a sheet (its HTML, or the student's .tex) or the cram order
(practice/cram-order.md). A .tex page is read as LaTeX text (its % comments dropped, its known
wrappers unwrapped), and again with every other command dropped, never as HTML; a .md page as
Markdown four ways: its blockquote marks dropped and its links read as their text, then its marks
dropped with and without underscore emphasis, as written, and as HTML (its inline tags and
entities read as a browser shows them; each copy of an answer counts once). Any other page is read as HTML from the file, so every view
counts, the hidden ones too, and so do comments, scripts and every attribute value (an aria-label
is read aloud), each read as text of its own. The page fails when it holds the phrase "answer
key" or "quarantined key" (a key's title and STOP line), or any answer of 8 or more characters in
the keys it is given, as a whole phrase: case, entities and runs of whitespace don't matter, and
neither phrasing tags (<span class=...>, <a href=...>, <em> and the like), soft hyphens and
zero-width characters, nor a Markdown page's emphasis and code marks split a phrase. A
shorter value ("6", "True") would match by chance, so it isn't checked; the last line names those
parts. With --no-markers the page is itself a key (an earlier mock's, which the student reads
before the later attempts), so the two phrases aren't searched. Every key counts, not only the
page's own: all the mock pages publish before any attempt. A
key's answers are its `**(x)** Answer: <value>` lines, each under a `## Question N` heading
(MOCK.md); the values file mock_key.py writes (practice/mock-values-key.md) has `- Q2(a): <value>`
lines.

Its output names the key and the part and where the page holds it (a view and a part id, or
none), never the answer: the student may read it before the attempt. Exit 0 clean, 1 on a leak, 2 on bad usage (a missing file, a key
with no answers, an Answer: line outside a bare ## Question N block, or a file that isn't UTF-8).
Stdlib only."""
import bisect
import html.parser
import os
import re
import sys

MARKERS = ("answer key", "quarantined key")
MIN_LEN = 8
QUESTION = re.compile(r"^## Question (\d+)$")
ANSWER = re.compile(r"^\*\*\(([a-z])\)\*\* Answer:\s*(.*)$")
VALUE = re.compile(r"^- (Q\d+\([a-z]\)): (.*)$")
# A true-or-false answer's witness: after the verdict, its punctuation, a lead-in ("e.g.",
# "counterexample") and wrapping parentheses dropped.
VERDICT = re.compile(r"^(?:true|false)\b\W*(?:(?:e\.g\.|(?:for example|for instance|counterexample|because|since)\b)\W*)?"
                     r"(.+?)\W*$", re.I)
# The phrasing tags: a browser shows the text around them as one run, so they don't split a phrase.
INLINE = {"a", "abbr", "acronym", "b", "bdi", "bdo", "big", "button", "cite", "code", "data", "del",
          "dfn", "em", "font", "i", "ins", "kbd", "label", "mark", "nobr", "output", "q", "rb", "rp", "rt",
          "ruby", "s", "samp", "small", "span", "strike", "strong", "sub", "sup", "time", "tspan", "tt", "u",
          "var", "wbr"}
# The places a hit names: only the page's own view and part ids, so no attribute's text is printed.
VIEW = re.compile(r"view-(paper|type|topic)")
PART = re.compile(r"Q\d+\([a-z]\)")
# Characters a browser shows as nothing, so they don't split a phrase: every format character
# (Unicode's Cf: a soft hyphen, the zero-width and bidi controls, the tag characters), the
# combining grapheme joiner, the variation selectors and the Hangul fillers.
INVISIBLE = re.compile("[\xad\u034f\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2\u115f\u1160\u180b-\u180f"
                       "\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0"
                       "\ufff9-\ufffb\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3"
                       "\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f\U000e0100-\U000e01ef]")
# Foreign content, where a browser reads a CDATA section as text; elsewhere it is a comment.
FOREIGN = {"svg", "math"}


class PageText(html.parser.HTMLParser):
    """The page as one string, with where each stretch of it sits: the view and the part the
    parser was in when it read it. The text a browser shows runs on in order; attribute values,
    comments and script or style bodies, which it doesn't show inside a phrase, follow as
    stretches of their own (finish)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.starts, self.places, self.aside = [], [], [], []
        self.size, self.view, self.part, self.views, self.hidden = 0, "", "", False, ""
        self.foreign, self.svgtext = 0, 0
        self.cdata()

    def cdata(self):
        """A CDATA section only in SVG or MathML, as in a browser, where this parser can switch
        (3.12.3 and later); elsewhere it reads `<![CDATA[` as a comment ending at the first >."""
        if hasattr(self, "_set_support_cdata"):
            self._set_support_cdata(self.foreign > 0)

    def here(self):
        return ", ".join(p for p in (self.view, self.part and f"in {self.part}") if p) or "the header"

    def add(self, s, gap=False, place=None):
        s = INVISIBLE.sub("", s)
        if gap:
            s = f" {s} "
        if not s:
            return
        self.starts.append(self.size)
        self.places.append(place or self.here())
        self.text.append(s)
        self.size += len(s)

    def finish(self):
        for s, place in self.aside:
            self.add(s, gap=True, place=place)
        self.joined = "".join(self.text)
        return self

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs)
        if tag in FOREIGN:
            self.foreign += 1
            self.cdata()
        if tag == "text":
            self.svgtext += 1

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs)

    def start(self, tag, attrs):
        a = dict(attrs)
        if VIEW.fullmatch(a.get("id") or ""):
            self.view, self.part, self.views = a["id"], "", True
        if a.get("data-part"):
            self.part = a["data-part"] if PART.fullmatch(a["data-part"]) else "a part"
        # SVG's <text> draws its runs as one line: a child tag adds no gap.
        if tag not in INLINE and not self.svgtext:
            self.add(" ")
        if tag in ("script", "style"):
            self.hidden = tag
        self.aside += [(value, self.here()) for _, value in attrs if value]

    def handle_endtag(self, tag):
        if tag in FOREIGN and self.foreign:
            self.foreign -= 1
            self.cdata()
        if tag == "text" and self.svgtext:
            self.svgtext -= 1
        if tag == "article":
            self.part = ""
        if tag == self.hidden:
            self.hidden = ""
        if tag not in INLINE and not self.svgtext:
            self.add(" ")

    def handle_data(self, data):
        if self.hidden:
            self.aside.append((data, self.here()))
        elif getattr(self, "cdata_elem", None) in ("title", "textarea") and "<" in data:
            # Read as RCDATA here (3.12.3 and later), but inside SVG a browser parses a <title>'s
            # markup, its CDATA sections included: read it again that way.
            inner = PageText()
            inner.foreign = 1
            inner.cdata()
            try:
                inner.feed(data)
                inner.close()
                self.add("".join(inner.text))
                self.aside += [(s, self.here()) for s, _ in inner.aside]
            except (AssertionError, NotImplementedError):  # a malformed <![: the tags dropped instead
                self.add(re.sub(r"<[^>]*>", "", data))
            self.aside.append((data, self.here()))
        else:
            self.add(data)

    def handle_comment(self, data):
        self.aside.append((data, self.here()))

    def unknown_decl(self, data):
        # Inside SVG or MathML a browser shows a CDATA section's text in place; elsewhere it reads
        # `<![CDATA[` as a comment that ends at the first >, and shows the rest, `]]>` too (a
        # parser that can't switch CDATA off, before 3.12.3's backports, still gives it here).
        if not data.startswith("CDATA["):
            self.aside.append((data, self.here()))
        elif self.foreign:
            self.add(data[6:])
        else:
            hidden, gt, shown = data[6:].partition(">")
            self.aside.append((hidden, self.here()))
            if gt:
                self.add(shown + "]]>")

    def handle_decl(self, decl):
        self.aside.append((decl, self.here()))

    def handle_pi(self, data):
        self.aside.append((data, self.here()))

    def where(self, offset):
        """The place of the stretch that holds the original offset; a page with no views (the
        notes, the cram order) is one place."""
        if not self.views:
            return "the page"
        return self.places[max(0, bisect.bisect_right(self.starts, offset) - 1)]


def normalize(s):
    return re.sub(r"\s+", " ", INVISIBLE.sub("", s)).strip().lower()


class KeyFormat(Exception):
    pass


def demark(s, underscores=True):
    """Markdown read as mockpage.py renders it: code spans and math kept as written (their
    backticks dropped), and outside them the emphasis marks (`**x**`, `*x*`, and with underscores
    `__x__` and `_x_`) dropped in pairs, a lone `**` kept, and `\\_` read as `_`. mockpage.py has
    no underscore emphasis while other Markdown does, so a key's answer is searched in both
    readings."""
    kept = []

    def keep(m):
        kept.append(m.group(1) if m.group(1) is not None else m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    s = re.sub(r"`([^`]+)`|\\\(.+?\\\)|\\\[.+?\\\]", keep, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    if underscores:
        s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
    if underscores:
        s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", s)
    s = s.replace("\\_", "_")
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], s)


def delatex(s):
    """A LaTeX sheet's text: a % comment dropped with its line's end and the next line's leading
    blanks, \\textbf{x}, {\\bf x}, \\textcolor{c}{x}, {\\color{c} x} and their kin unwrapped, \\-, \\allowbreak and {} dropped, ~,
    \\\\, \\, and the other spacing commands read as spaces, and \\_, \\&, \\%, \\#, \\$, \\{ and
    \\} as the characters they escape."""
    s = re.sub(r"(?<!\\)((?:\\\\)*)%[^\n]*\n?[ \t]*", r"\1", s)
    unwrap = re.compile(r"\\(?:textbf|textit|textsl|textsf|textrm|texttt|textsc|textup|textmd|textnormal|emph"
                        r"|underline|uline|hl|mbox|text)\{([^{}]*)\}"
                        r"|\\(?:textcolor|colorbox)\{[^{}]*\}\{([^{}]*)\}|\\fcolorbox\{[^{}]*\}\{[^{}]*\}\{([^{}]*)\}"
                        r"|\{\\(?:(?:bf|it|em|sl|sf|rm|tt|sc)\s+|color\{[^{}]*\}\s*)([^{}]*)\}")
    while unwrap.search(s):
        s = unwrap.sub(lambda m: next(g for g in m.groups() if g is not None), s)
    s = re.sub(r"\\\\|\\[,;: ]|\\q?quad\b|\\enspace\b|\\thinspace\b", " ", s)
    s = re.sub(r"\\-|\\allowbreak\b|\{\}", "", s)
    s = re.sub(r"\\([_&%#$}{])", r"\1", s)
    return s.replace("~", " ")


def bare_tex(s):
    """delatex's text with every command it doesn't know dropped, and the braces: a wrapper it
    doesn't name (\\foo{x}) leaves its argument."""
    return re.sub(r"[{}]", "", re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", "", s))


def unquote(s):
    """A Markdown page as rendered: blockquote marks dropped from each line, and a link or image,
    [text](url) or [text][ref], read as its text."""
    s = re.sub(r"(?m)^[ \t]*(?:>[ \t]?)+", "", s)
    return re.sub(r"!?\[([^\]]*)\](?:\([^)]*\)|\[[^\]]*\])", r"\1", s)


def plain(s, underscores=True):
    return demark(s, underscores).rstrip(".").strip()


def answers(path):
    """[(key name, part, value)] from a key's `**(x)** Answer:` lines, each under a `## Question N` heading
    (one outside is refused: it would go unchecked), and from the values file's `- Q2(a): <value>`
    lines under their mock's `## <slug>` heading, each as written (main reads it as demark() does). A key with none is
    refused; the values file (titled `# KEY VALUES:`) may hold none, for mocks of proofs alone."""
    out, q, heading, name, values_file = [], None, "", os.path.basename(path), False
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            t = line.strip()
            if n == 1 and t.startswith("# KEY VALUES:"):
                values_file = True
            if t.startswith("## "):
                m = QUESTION.match(t)
                q, heading = (m.group(1) if m else None), t[3:].strip()
                continue
            m = ANSWER.match(t)
            if m:
                if not q:
                    raise KeyFormat(f"{path}:{n}: an Answer: line outside a bare ## Question N block "
                                    f"(MOCK.md: a key's question headings have no title)")
                out.append((name, f"Q{q}({m.group(1)})", m.group(2)))
                continue
            m = VALUE.match(t)
            if m:
                out.append((name, f"{heading} {m.group(1)}", m.group(2)))
    if not out and not values_file:
        raise KeyFormat(f"{path} has no **(x)** Answer: lines under ## Question N headings")
    return out


def find(page, phrase):
    """The offsets in the page text where the phrase sits as a whole phrase, in any case."""
    phrase = normalize(phrase)
    words = [re.escape(w) for w in phrase.split(" ")]
    pattern = (r"(?<!\w)" if re.match(r"\w", phrase) else "") + r"\s+".join(words) + \
              (r"(?!\w)" if re.search(r"\w$", phrase) else "")
    return [m.start() for m in re.finditer(pattern, page.joined, re.I)]


def search(readings, phrases):
    """Where the phrases sit in the reading of the page that holds them most often: a Markdown
    page is read four ways, and each copy on it counts once."""
    best, page = [], readings[0]
    for reading in readings:
        found = sorted({o for v in phrases for o in find(reading, v)})
        if len(found) > len(best):
            best, page = found, reading
    return [page.where(o) for o in best]


def text_page(s):
    page = PageText()
    page.add(s)
    return page.finish()


def html_page(s):
    """The text read as HTML, or None where html.parser can't read it."""
    page = PageText()
    try:
        page.feed(s)
        page.close()
    except (AssertionError, NotImplementedError):  # html.parser's on a malformed <![ (before 3.10: the latter)
        return None
    return page.finish()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    markers = not (argv and argv[0] == "--no-markers")
    argv = argv if markers else argv[1:]
    if len(argv) < 2:
        print("usage: mock_leak.py [--no-markers] <page> <key.md>...", file=sys.stderr)
        return 2
    page_path, key_paths = argv[0], argv[1:]
    reading = page_path
    try:
        with open(page_path, encoding="utf-8") as f:
            raw = f.read()
        keyed = []
        for reading in key_paths:
            keyed += answers(reading)
    except UnicodeDecodeError:
        print(f"mock_leak: {reading} isn't UTF-8 text", file=sys.stderr)
        return 2
    except (OSError, KeyFormat) as e:
        print(f"mock_leak: {e}", file=sys.stderr)
        return 2
    # Text, not HTML: a < in math would open a "tag". Markdown is read both ways and as written.
    if page_path.endswith(".tex"):
        readings = [text_page(delatex(raw)), text_page(bare_tex(delatex(raw)))]
    elif page_path.endswith(".md"):
        md = unquote(raw)
        readings = [text_page(demark(md)), text_page(demark(md, underscores=False)), text_page(raw)]
        # Inline HTML a renderer passes through (a <br> in a table cell, &shy;) as a browser shows it.
        readings += [r for r in [html_page(demark(md))] if r]
    else:
        page = html_page(raw)
        if not page:
            print(f"mock_leak: {page_path}: a <![ section html.parser can't read", file=sys.stderr)
            return 2
        readings = [page]

    hits = []
    for marker in MARKERS if markers else ():
        hits += [f'the key\'s phrase "{marker}" is in the page ({w})' for w in search(readings, [marker])]
    short = {}
    for name, part, raw_value in keyed:
        # Its Markdown read both ways, and as written (a page may show the marks themselves).
        forms = {plain(raw_value), plain(raw_value, underscores=False), raw_value.strip().rstrip(".").strip()}
        long = [v for v in forms if len(normalize(v)) >= MIN_LEN]
        if not long:
            short.setdefault(name, []).append(part)
            continue
        found = search(readings, long)
        hits += [f"{name} {part}: its answer is in the page ({w})" for w in found]
        witnesses = [w.group(1) for w in map(VERDICT.match, forms) if w and len(normalize(w.group(1))) >= MIN_LEN]
        if not found and witnesses:
            hits += [f"{name} {part}: its answer's witness is in the page ({w})" for w in search(readings, witnesses)]
    for h in hits:
        print(f"mock_leak: {h}", file=sys.stderr)
    checked = len(keyed) - sum(len(v) for v in short.values())
    tail = (f"; under {MIN_LEN} characters, not checked: " + "; ".join(f"{k} {', '.join(v)}" for k, v in short.items())
            if short else "")
    if hits:
        print(f"LEAK: {len(hits)} found; {checked} answers checked{tail}")
        return 1
    print(f"LEAK OK: {checked} answers checked{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
