#!/usr/bin/env python3
"""Build the mock page from a mock exam in MOCK.md's format (08-practice), from the hub root.

  mockpage.py <mock.md> [--out _build/mock.html] [--backbone _build/backbone.md]

It reads the one mock file it is given and never a key (FB-154): it refuses a path ending in
`-key.md`, and a file holding a key's title, STOP line or `Answer:` lines. It parses the mock line
by line and refuses anything outside the format (exit 1, naming the line): a heading or part out of
order or without its points, parts that don't sum to their question, questions that don't sum to
the header's total, a header points table that disagrees with the questions, a type outside the
closed list, a topic the backbone doesn't number, a part left with no type or topic, a heading
below `##`, a link or image, a TODO-VERIFY, a control character or a line break other than a
newline, a math macro that makes HTML (\\href, \\style, \\class, \\cssId, \\data,
\\mmlToken, \\require, \\bbox) on any line, titles included, or a figure block with anything but
SVG's drawing tags, end tags too, nested strictly (no event, href or style attribute, no url()
but url(#id) naming an id of its own figure, no image-set(), no backslash in an attribute but
aria-label, no attribute twice on a tag, no tag inside <title> or <desc> and none but <tspan>
inside <text>, no raw `<` in its text, no comment, CDATA or declaration a browser reads
differently, no tag, quote or comment left open at its end) or with an id another figure, a copy
of one or the page itself uses.

It writes the page from the skill's templates/mock-page.html: the header, then the same parts in
three views (FB-153): by paper, in question order; by question type; by topic, a part in several
topics shown in each. Every part carries `data-part="Q2(a)"`; only the paper view's copies carry
ids. Each figure is written back from what the check read, never copied raw, so a browser reads
what the check did; its ids and url(#...) references get a suffix per copy (`-ty1`, `-to2s`), so
no id repeats. Text is escaped, so stray HTML shows as text; math is left for MathJax.

Exit 0 when written, 1 on a format error (a mock that isn't UTF-8 among them), 2 on bad usage (a
key's path, a missing mock or backbone, a backbone that isn't UTF-8, or a backbone section title
holding such a macro, among them). Stdlib only."""
import argparse
import html
import html.parser
import os
import re
import sys

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "mock-page.html")
TYPES = {"trace": "Trace", "compute": "Compute", "table": "Table", "justify": "Justify", "prove": "Prove",
         "classify": "Classify", "true-false": "True or false", "formulate": "Formulate",
         "design": "Design"}
TIME = re.compile(r"\*\*Time:\*\*\s*([0-9]+)\s*minutes?\.\s*\*\*Total:\*\*\s*([0-9]+)\s*points?\.")
QUESTION = re.compile(r"^## Question ([1-9][0-9]*): (.+) \(([0-9]+) points?\)$")
PART = re.compile(r"^\*\*\(([a-z])\) \(([0-9]+) pts?\)\*\*\s*(.*)$")
TAG = re.compile(r"^(Type|Topic):\s*(.*)$")
TOPIC = re.compile(r"^§([0-9]+)$")
KEYISH = re.compile(r"^\s*(# ANSWER KEY\b|> \*\*STOP\b)|\*\*\([a-z]\)\*\* Answer:")
TEX_HTML = re.compile(r"\\(href|style|class|cssId|data|mmlToken|require|bbox)(?![A-Za-z])")
# Every character but tab and newline below 0x20, DEL and C1, and the ones str.splitlines()
# breaks a line at: the key checker splits at newlines alone, so both must read the same lines.
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]")
BACKBONE_SECTION = re.compile(r"^## §([0-9]+) (.+?) \(`sec-")
SVG_TAGS = {"svg", "g", "line", "circle", "ellipse", "rect", "path", "polygon", "polyline", "text",
            "tspan", "title", "desc", "defs", "marker"}
ANSWER_SPACE = "_(answer space)_"
URL_REF = re.compile(r"""url\(\s*(['"]?)#([^)'"\s]+)\1\s*\)""", re.I)  # CSS reads URL( too
PAGE_ID = re.compile(r"^(q\d+[a-z]?|view-.*|main|themeBtn|MathJax-script|MJX-.*)$")
ENTITIES = {"lt", "gt", "amp", "quot", "apos"}


class FormatError(Exception):
    def __init__(self, line, msg):
        super().__init__(f"{line}: {msg}" if line else msg)


class SvgCheck(html.parser.HTMLParser):
    """Refuses a figure block holding anything but SVG's drawing tags, nested strictly, and keeps
    what it read as tokens: the page gets the figure written back from them (serialize), never
    the raw block, so a browser reads what this check read. <title> and <desc> hold text only (a
    browser reads markup inside them as HTML), and a raw `<` in any text is refused (write
    `&lt;`)."""

    def __init__(self, line):
        super().__init__(convert_charrefs=False)
        self.line, self.roots, self.root_attrs, self.ids, self.shape = line, 0, {}, [], []
        self.open, self.refs = [], []

    def bad(self, msg):
        raise FormatError(self.line, f"figure: {msg}")

    def start(self, tag, attrs, closed):
        if tag not in SVG_TAGS:
            self.bad(f"<{tag}> isn't one of SVG's drawing tags")
        if self.open and self.open[-1] in ("title", "desc"):
            self.bad(f"<{tag}> inside <{self.open[-1]}>, which holds text only")
        # A browser draws a <text>'s runs as one line and skips a child it doesn't draw, where
        # the leak check would read two words.
        if self.open and self.open[-1] in ("text", "tspan") and tag != "tspan":
            self.bad(f"<{tag}> inside <{self.open[-1]}>, which holds text and <tspan> only")
        if not self.open and (tag != "svg" or self.roots):
            self.bad("one <svg> per figure block, holding everything")
        names = [name for name, _ in attrs]
        if len(set(names)) != len(names):  # a browser keeps the first, this check the last
            self.bad(f"<{tag}> names an attribute twice")
        for name, value in attrs:
            if name.startswith("on") or name in ("href", "xlink:href", "style", "src"):
                self.bad(f"<{tag}> has the attribute {name}")
            if name == "id":
                self.ids.append(value or "")
            self.refs += [m.group(2) for m in URL_REF.finditer(value or "")]
            if len(re.findall(r"url\s*\(", value or "", re.I)) != len(URL_REF.findall(value or "")) \
                    or re.search(r"image-set", value or "", re.I):
                self.bad(f"<{tag}> has a url() that isn't url(#id), or an image-set(): a figure loads nothing")
            if "\\" in (value or "") and name != "aria-label":  # a CSS escape can spell url(
                self.bad(f"<{tag}>'s {name} holds a backslash")
        if tag == "svg":
            self.roots += 1
            self.root_attrs = dict(attrs)
        self.shape.append(("startend" if closed else "start", tag, tuple(attrs)))
        if not closed:
            self.open.append(tag)

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, True)

    def handle_endtag(self, tag):
        if tag not in SVG_TAGS:
            self.bad(f"</{tag}> isn't one of SVG's drawing tags")
        if not self.open or self.open[-1] != tag:
            self.bad(f"</{tag}> where " + (f"<{self.open[-1]}> is open" if self.open else "nothing is open"))
        self.open.pop()
        self.shape.append(("end", tag, ()))

    def handle_data(self, data):
        if "<" in data:
            self.bad("a raw < in its text (write &lt;)")
        if not self.open and data.strip():
            self.bad("text outside its <svg>")
        self.shape.append(("text", html.escape(data, quote=False), ()))

    def handle_charref(self, name):
        self.bad(f"&#{name}; in its text: write the character itself")

    def handle_entityref(self, name):
        if name not in ENTITIES:
            self.bad(f"&{name}; in its text: only &lt;, &gt;, &amp;, &quot; and &apos;")
        self.shape.append(("text", f"&{name};", ()))

    def handle_comment(self, data):
        self.bad("an HTML comment")

    def unknown_decl(self, data):
        self.bad("a CDATA section or declaration")

    def handle_decl(self, decl):
        self.bad("a declaration")

    def handle_pi(self, data):
        self.bad("a processing instruction")


def quoted(value):
    """An attribute value escaped for double quotes: &, <, > and " only."""
    return html.escape(value, quote=False).replace('"', "&quot;")


def serialize(shape, suffix=""):
    """The figure written back from its tokens, each id and url(#id) reference given the suffix:
    attribute values escaped and quoted, text escaped, every tag as the check read it."""
    out = []
    for kind, tag, attrs in shape:
        if kind == "text":
            out.append(tag)
        elif kind == "end":
            out.append(f"</{tag}>")
        else:
            values = "".join(f' {k}="{quoted(suffixed(k, v or "", suffix))}"' for k, v in attrs)
            out.append(f"<{tag}{values}{'/' if kind == 'startend' else ''}>")
    return "".join(out)


def check_svg(block, line, seen=None):
    """The parsed figure, or FormatError for a bad one; with seen ({id: line}, the paper view's
    pass), also for an id another figure of the mock already defines or the page uses itself."""
    p = SvgCheck(line)
    try:
        p.feed(block)
    except (AssertionError, NotImplementedError):  # html.parser's on a malformed <![ (before 3.10: the latter)
        raise FormatError(line, "figure: a <![ section html.parser can't read") from None
    if p.rawdata.strip():  # close() drops it unread; a browser reads on into the page
        raise FormatError(line, "figure: a tag, quote or comment left open runs past its </svg>")
    p.close()
    if p.open:
        raise FormatError(line, f"figure: <{p.open[-1]}> is never closed")
    if p.roots != 1:
        raise FormatError(line, "figure: one <svg> per figure block")
    if p.root_attrs.get("role") != "img" or not (p.root_attrs.get("aria-label") or "").strip():
        raise FormatError(line, 'figure: the <svg> needs role="img" and an aria-label')
    for r in p.refs:
        if r not in p.ids:  # its copies give each reference their own suffix
            raise FormatError(line, f"figure: url(#{r}) names no id of its own figure: each figure defines "
                                    f"the markers it uses")
    for i in p.ids if seen is not None else []:
        if i in seen:
            raise FormatError(line, f"figure: id {i!r} again (line {seen[i]}): ids are unique in a mock")
        if PAGE_ID.match(i or ""):
            raise FormatError(line, f"figure: id {i!r} is one the page uses itself")
        seen[i] = line
    return p


# ---- inline Markdown ----

def inline(text, line):
    """One run of Markdown text as HTML: escaped, math kept for MathJax, then code, bold, italic."""
    stash = []

    def keep(fragment):
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    # One pass, leftmost first, as mock_leak.py's demark() reads it: math inside a code span is code.
    text = re.sub(r"`([^`]+)`|\\\(.+?\\\)|\\\[.+?\\\]",
                  lambda m: keep(f"<code>{html.escape(m.group(1), quote=False)}</code>" if m.group(1) is not None
                                 else html.escape(m.group(0), quote=False)), text)
    if re.search(r"\[[^\]]*\]\([^)]*\)", text):
        raise FormatError(line, "a link or image: the mock has none (MOCK.md)")
    text = html.escape(text, quote=False).replace("\\_", "\x01")
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = text.replace("\x01", "_")
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def suffixed(name, value, suffix):
    """An attribute's value in a figure's copy: an id gets the suffix, and so does each url(#id)."""
    if value is None:
        return None
    if name.lower() == "id":
        return value + suffix
    return URL_REF.sub(lambda m: f"url({m.group(1)}#{m.group(2)}{suffix}{m.group(1)})", value)


def blocks(lines, suffix="", seen=None):
    """[(line number, text)] of Markdown as HTML: paragraphs, lists, pipe tables, fenced code,
    figure blocks and answer spaces."""
    out, i = [], 0
    while i < len(lines):
        n, text = lines[i]
        s = text.strip()
        if not s:
            i += 1
        elif s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j][1].strip().startswith("```"):
                j += 1
            if j == len(lines):
                raise FormatError(n, "a code block with no closing ```")
            code = "\n".join(t for _, t in lines[i + 1:j])
            out.append(f"<pre><code>{html.escape(code, quote=False)}</code></pre>")
            i = j + 1
        elif s.startswith("<svg"):
            j = i
            while j < len(lines) and not lines[j][1].rstrip().endswith("</svg>"):
                j += 1
            if j == len(lines):
                raise FormatError(n, "a figure with no closing </svg>")
            svg = "\n".join(t for _, t in lines[i:j + 1])
            original = check_svg(svg, n, None if suffix else seen)
            for fid in original.ids if suffix and seen is not None else []:
                if fid + suffix in seen or PAGE_ID.match(fid + suffix):
                    raise FormatError(n, f"figure: its id {fid!r} becomes {fid + suffix!r} in another "
                                         f"view, an id the page already has: rename it")
                seen[fid + suffix] = n
            copy = serialize(original.shape, suffix)
            out.append(f"<figure>{copy}</figure>")
            i = j + 1
        elif s == ANSWER_SPACE:
            out.append('<div class="answer" role="img" aria-label="Answer space"></div>')
            i += 1
        elif s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i][1].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(table(rows))
        elif re.match(r"^(- |\d+\. )", s):
            ordered = not s.startswith("- ")
            items = []
            while i < len(lines) and re.match(r"^(- |\d+\. )", lines[i][1].strip()):
                m, item = lines[i][0], re.sub(r"^(- |\d+\. )", "", lines[i][1].strip())
                items.append(f"<li>{inline(item, m)}</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
        elif s.startswith("#"):
            raise FormatError(n, "a heading inside a question (only ## Question N headings)")
        else:
            para = []
            while i < len(lines):
                t = lines[i][1].strip()
                if not t or t.startswith(("```", "<svg", "|", "#")) or t == ANSWER_SPACE \
                        or re.match(r"^(- |\d+\. )", t):
                    break
                para.append(t)
                i += 1
            out.append(f"<p>{inline(' '.join(para), n)}</p>")
    return "\n".join(out)


def table(rows):
    def cells(text):
        return [c.strip() for c in text.strip().strip("|").split("|")]
    n = rows[0][0]
    if len(rows) < 2 or not re.match(r"^\|?\s*:?-{3,}", rows[1][1].strip()):
        raise FormatError(n, "a table needs a | --- | line under its header row")
    head = "".join(f"<th>{inline(c, n)}</th>" for c in cells(rows[0][1]))
    body = "".join("<tr>" + "".join(f"<td>{inline(c, m)}</td>" for c in cells(t)) + "</tr>"
                   for m, t in rows[2:])
    return f'<div class="tbl-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# ---- the mock ----

def parse_tags(kind, value, line, topics):
    values = [v.strip() for v in re.split(r"[|,]", value) if v.strip()]
    if not values:
        raise FormatError(line, f"{kind}: with no value")
    for v in values:
        if kind == "Type" and v not in TYPES:
            raise FormatError(line, f"type {v!r} isn't one of: {', '.join(TYPES)}")
        if kind == "Topic":
            m = TOPIC.match(v)
            if not m:
                raise FormatError(line, f"topic {v!r} isn't a section number like §2")
            if m.group(1) not in topics:
                raise FormatError(line, f"topic {v} isn't a section of the backbone")
    return values


def verbatim(lines, path):
    """The positions in lines that sit in a fenced code block or a figure block, the fence and
    tag lines included, as blocks() reads them: a `---`, part or tag line there is content. One
    left open would swallow the rest of the mock, so it is refused at its first line."""
    out, inside, start = set(), None, None
    for k, (n, t) in enumerate(lines):
        s = t.strip()
        if inside == "code":
            out.add(k)
            inside = None if s.startswith("```") else inside
        elif inside == "svg":
            out.add(k)
            inside = None if t.rstrip().endswith("</svg>") else inside
        elif s.startswith("```"):
            out.add(k)
            inside, start = "code", n
        elif s.startswith("<svg"):
            out.add(k)
            inside, start = (None if t.rstrip().endswith("</svg>") else "svg"), n
    if inside:
        raise FormatError(f"{path}:{start}", "a code block with no closing ```" if inside == "code"
                          else "a figure with no closing </svg>")
    return out


def parse(path, topics):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        raise FormatError(path, "not UTF-8 text") from None
    bad = CONTROL.search(text)
    if bad:
        n = text.count("\n", 0, bad.start()) + 1
        raise FormatError(f"{path}:{n}", "a control character or a line break other than a newline")
    lines = list(enumerate(text.splitlines(), 1))  # only newlines are left to split at
    for n, t in lines:
        if KEYISH.search(t):
            raise FormatError(f"{path}:{n}", "this reads like an answer key: the page never reads one (FB-154)")
        if "TODO-VERIFY" in t:
            raise FormatError(f"{path}:{n}", "a TODO-VERIFY is left")
        if TEX_HTML.search(t):
            raise FormatError(f"{path}:{n}", f"\\{TEX_HTML.search(t).group(1)} makes HTML inside math")
    shield = verbatim(lines, path)
    seps = [k for k, (_, t) in enumerate(lines) if t.strip() == "---" and k not in shield]
    if not seps:
        raise FormatError(path, "no --- line ends the header")
    head = lines[:seps[0]]
    first = next((k for k, (_, t) in enumerate(head) if t.strip()), None)
    if first is None or not head[first][1].startswith("# "):
        raise FormatError(f"{path}:1", "the mock starts with its # title line")
    title = head[first][1][2:].strip()
    timing = next((TIME.search(t) for _, t in head if TIME.search(t)), None)
    if not timing:
        raise FormatError(path, "the header has no **Time:** N minutes. **Total:** P points. line")
    minutes, total = int(timing.group(1)), int(timing.group(2))
    head_body = head[first + 1:]

    questions, bounds = [], seps + [len(lines)]
    for a, b in zip(bounds, bounds[1:]):
        chunk = [x for x in lines[a + 1:b]]
        if not any(t.strip() for _, t in chunk):
            continue
        questions.append(parse_question(path, chunk, len(questions) + 1, topics))
    if not questions:
        raise FormatError(path, "no questions")
    got = sum(q["points"] for q in questions)
    if got != total:
        raise FormatError(path, f"the questions sum to {got} points, the header says {total}")
    check_points_table(path, head_body, questions, total)
    return {"title": title, "minutes": minutes, "total": total, "head": head_body, "questions": questions}


def check_points_table(path, head, questions, total):
    """The header's points table: a row per question whose first cell is its number and last its
    points, and a Total row, each matching the questions (run B's table kept a stale total)."""
    k = next((i for i, (_, t) in enumerate(head) if t.strip().startswith("|")), None)
    if k is None:
        raise FormatError(path, "the header has no points table")
    rows = []
    for n, t in head[k + 2:]:
        if not t.strip().startswith("|"):
            break
        rows.append((n, [c.strip().strip("*").strip() for c in t.strip().strip("|").split("|")]))
    listed = set()
    for n, cells in rows:
        first, last = cells[0], cells[-1]
        if re.fullmatch(r"[0-9]+", first):  # isdigit() takes "²", which int() refuses
            number = int(first)
            if not 1 <= number <= len(questions):
                raise FormatError(f"{path}:{n}", f"the points table lists question {number}, which the mock lacks")
            want = questions[number - 1]["points"]
        elif any(c.lower() == "total" for c in cells):
            number, want = "total", total
        else:
            continue
        if last != str(want):
            raise FormatError(f"{path}:{n}", f"the points table gives {'the total' if number == 'total' else f'question {number}'} "
                                             f"{last or 'nothing'}, the mock {want}")
        listed.add(number)
    missing = [str(q["n"]) for q in questions if q["n"] not in listed] + ([] if "total" in listed else ["Total"])
    if missing:
        raise FormatError(path, f"the points table has no row for {', '.join(missing)}")


def parse_question(path, chunk, number, topics):
    chunk = [(n, t) for n, t in chunk]
    while chunk and not chunk[0][1].strip():
        chunk.pop(0)
    n0, first = chunk[0]
    m = QUESTION.match(first.strip())
    if not m:
        raise FormatError(f"{path}:{n0}", "a question starts with ## Question N: <title> (P points)")
    if int(m.group(1)) != number:
        raise FormatError(f"{path}:{n0}", f"question {m.group(1)} where question {number} belongs")
    q = {"n": number, "title": m.group(2).strip(), "points": int(m.group(3)), "types": [], "topics": [],
         "stem": [], "parts": []}
    current, shield = None, verbatim(chunk, path)
    for k, (n, t) in enumerate(chunk[1:], 1):
        tag, part = TAG.match(t.strip()), PART.match(t.strip())
        if k in shield:
            (current["body"] if current else q["stem"]).append((n, t))
        elif part:
            letter = part.group(1)
            want = chr(ord("a") + len(q["parts"]))
            if letter != want:
                raise FormatError(f"{path}:{n}", f"part ({letter}) where ({want}) belongs")
            current = {"letter": letter, "points": int(part.group(2)), "types": [], "topics": [],
                       "body": [(n, part.group(3))] if part.group(3) else []}
            q["parts"].append(current)
        elif tag:
            values = parse_tags(tag.group(1), tag.group(2), f"{path}:{n}", topics)
            target = current if current else q
            target["types" if tag.group(1) == "Type" else "topics"].extend(values)
        elif re.match(r"^\*\*\([a-z]\)", t.strip()):
            raise FormatError(f"{path}:{n}", "a part starts with **(x) (k pts)**: its points are missing")
        else:
            (current["body"] if current else q["stem"]).append((n, t))
    if not q["parts"]:
        q["parts"].append({"letter": "a", "points": q["points"], "types": [], "topics": [],
                           "body": q["stem"]})
        q["stem"] = []
    got = sum(p["points"] for p in q["parts"])
    if got != q["points"]:
        raise FormatError(f"{path}:{n0}", f"question {number}'s parts sum to {got} points, not {q['points']}")
    for p in q["parts"]:
        p["types"] = list(dict.fromkeys(p["types"] or q["types"]))
        p["topics"] = list(dict.fromkeys(p["topics"] or q["topics"]))
        p["id"] = f"Q{number}({p['letter']})"
        if not p["types"] or not p["topics"]:
            raise FormatError(f"{path}:{n0}", f"{p['id']} has no {'Type' if not p['types'] else 'Topic'}: line, "
                                              f"on the question or the part")
    return q


# ---- the page ----

def chips(types, topics, names):
    out = [f'<span class="chip type">{TYPES[t]}</span>' for t in types]
    out += [f'<span class="chip topic">{html.escape(names.get(t, t))}</span>' for t in topics]
    return f'<span class="chips">{"".join(out)}</span>'


def pts(k):
    return f"{k} pt" if k == 1 else f"{k} pts"


def part_html(q, p, names, suffix, with_stem, seen=None):
    pid = f' id="q{q["n"]}{p["letter"]}"' if not suffix else ""
    stem = ""
    if with_stem and q["stem"]:
        stem = (f'<details class="ctx"><summary>Question {q["n"]}: {html.escape(q["title"])}</summary>'
                f'{blocks(q["stem"], suffix + "s", seen)}</details>')
    return (f'<article class="part" data-part="{p["id"]}"{pid}><header><span class="pid">{p["id"]}</span>'
            f'<span class="pts">{pts(p["points"])}</span>{chips(p["types"], p["topics"], names)}</header>'
            f'{stem}{blocks(p["body"], suffix, seen)}</article>')


def render(mock, names):
    seen = {}
    head = (f'<header class="mockhead"><h1>{html.escape(mock["title"])}</h1>'
            f'{blocks(mock["head"], seen=seen)}</header>')
    paper = []
    for q in mock["questions"]:
        qtags = chips(q["types"], q["topics"], names) if q["types"] or q["topics"] else ""
        stem = blocks(q["stem"], seen=seen)
        parts = "\n".join(part_html(q, p, names, "", False, seen) for p in q["parts"])
        paper.append(f'<section class="q" id="q{q["n"]}"><h2>Question {q["n"]}: {html.escape(q["title"])}'
                     f'<span class="pts">{q["points"]} points</span>{qtags}</h2>{stem}\n{parts}</section>')
    counter = [0]

    def group_view(key, order, label):
        groups = {}
        for q in mock["questions"]:
            for p in q["parts"]:
                for v in p[key]:
                    groups.setdefault(v, []).append((q, p))
        out = []
        for v in sorted(groups, key=order):
            members = groups[v]
            body = []
            for q, p in members:
                counter[0] += 1
                body.append(part_html(q, p, names, f"-{key[:2]}{counter[0]}", True, seen))
            k = len(members)
            out.append(f'<section class="grp"><h2>{html.escape(label(v))}<span class="pts">{k} part'
                       f'{"" if k == 1 else "s"} · {sum(p["points"] for _, p in members)} pts</span></h2>'
                       + "\n".join(body) + "</section>")
        return "\n".join(out)

    types = group_view("types", lambda t: list(TYPES).index(t), lambda t: TYPES[t])
    topics = group_view("topics", lambda t: int(t[1:]), lambda t: names.get(t, t))
    views = (f'<div id="view-paper">\n{"".join(paper)}\n</div>\n'
             f'<div id="view-type" hidden>\n{types}\n</div>\n'
             f'<div id="view-topic" hidden>\n{topics}\n</div>')
    return head, views


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the mock page (08-practice).")
    ap.add_argument("mock")
    ap.add_argument("--out", default=os.path.join("_build", "mock.html"))
    ap.add_argument("--backbone", default=os.path.join("_build", "backbone.md"))
    args = ap.parse_args(argv)
    if args.mock.endswith("-key.md"):
        print(f"mockpage: {args.mock} is a key: the page never reads one (FB-154)", file=sys.stderr)
        return 2
    if not os.path.isfile(args.mock):
        print(f"mockpage: no mock at {args.mock}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.backbone):
        print(f"mockpage: no backbone at {args.backbone}: run from the hub root, or pass --backbone",
              file=sys.stderr)
        return 2
    try:
        with open(args.backbone, encoding="utf-8") as f:
            backbone = f.readlines()
    except UnicodeDecodeError:
        print(f"mockpage: {args.backbone} isn't UTF-8 text", file=sys.stderr)
        return 2
    names = {}
    for line in backbone:
        m = BACKBONE_SECTION.match(line)
        if m and TEX_HTML.search(m.group(2)):
            print(f"mockpage: {args.backbone}: §{m.group(1)}'s title holds "
                  f"\\{TEX_HTML.search(m.group(2)).group(1)}, which makes HTML inside math", file=sys.stderr)
            return 2
        if m:
            names[f"§{m.group(1)}"] = f"§{m.group(1)} {m.group(2).strip()}"
    if not names:
        print(f"mockpage: {args.backbone} has no ## §N <title> (`sec-N` ...) section lines", file=sys.stderr)
        return 2
    topics = {k[1:] for k in names}
    try:
        mock = parse(args.mock, topics)
        head, views = render(mock, names)
    except FormatError as e:
        where = f"{args.mock}:" if re.match(r"\d+: ", str(e)) else ""  # the render's errors carry a bare line
        print(f"mockpage: {where}{e}", file=sys.stderr)
        return 1
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read()
    page = re.sub(r"\A<!--.*?-->\n", "", page, count=1, flags=re.S)
    page = page.replace("{{TITLE}}", html.escape(mock["title"]), 1)
    page = page.replace("<!-- MOCK HEADER -->", head, 1).replace("<!-- MOCK VIEWS -->", views, 1)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    parts = [p for q in mock["questions"] for p in q["parts"]]
    print(f"wrote {args.out}: {len(mock['questions'])} questions, {len(parts)} parts, {mock['total']} points, "
          f"{mock['minutes']} minutes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
