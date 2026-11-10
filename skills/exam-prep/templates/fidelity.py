#!/usr/bin/env python3
r"""Fidelity: each HTML fragment says what its Markdown notes file says, checked by script.

exam-prep template fidelity.py, baseline as of 2026-11-10; changes only via `12-retro`.
Copy it to _build/verify/fidelity.py; it needs no filling. Run from the hub root:

  python3 -I _build/verify/fidelity.py --self-test   first: exit 0 only on SELF-TEST OK
  python3 -I _build/verify/fidelity.py [secN ...]    every fragment, or the ones named; exit 0
                                                     only on FIDELITY OK

It pairs each `notes/*.md` whose first line is `# §N <title>` with `_build/frag/secN.html`, reads
both the way CONVERT.md maps one onto the other, and compares, in order:
- the text: words, numbers and symbols, markup aside. Dropped on both sides: a `Step N:` label
  and a Markdown list number (the CSS draws them), a callout's label (`**Pitfall:**` and its
  `.lab`, and the `Definition` and `Key rule` labels a converter adds), `{#id}` anchors, link
  targets, citations (compared on their own) and figures (the notes' FIG markers, the fragment's
  `<figure>`). Math meets on one form: `\le` and `<=` are both ≤ (and the like), `\(n^2\)` and a
  plain `n^2` give the same tokens, `−` is `-`, a curly quote is straight;
- the headings: level, id and text (`#` is the `<h2>`, `##` an `<h3>`, `###` an `<h4>`);
- the citations, `[D5 p.23]` against `<a class="slink">D5 p.23</a>`;
- the in-page links' targets, `[text](#id)` against `<a class="xref" href="#id">`;
- the callouts: each worked example (its id and number), Pitfall, Not on <exam>, Unverified,
  Background, How it's tested, Connects to and Depth;
- the list items and steps, with their ids: a `Step N:` line against an `<li>` of
  `<ol class="steps">`, a `-`, `*` or `1.` item against any other `<li>`.
Each difference prints one line: the fragment, the section (the nearest heading's id) and what
differs. A notes file with no fragment, or a fragment with no notes file, is a difference too.

--self-test first checks a built-in clean pair, which uses every mapping above, and requires it to
pass. Then it plants a dropped sentence, a changed number, two swapped steps and a dropped
citation into an in-memory copy of that pair's fragment and of each hub fragment that has the
part to change, and requires each plant to be caught. A plant that leaves its copy unchanged
fails as PLANT DID NOTHING: a no-op replace once passed vacuously."""
import difflib
import glob
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.dirname(os.path.dirname(HERE))
FRAG_DIR = os.path.join(HUB, "_build", "frag")

H1 = re.compile(r"^# §(\d+)(?=\s|$)")
FRAG = re.compile(r"sec(\d+)\.html$")
QUOTE = re.compile(r"^(?:\s*>)+ ?")
FENCE = re.compile(r"^\s*(```|~~~)")
COMMENT = re.compile(r"<!--.*?-->")
RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
ANCHOR = re.compile(r"\{#([\w-]+)\}")
CITE = re.compile(r"(?<!\\)\[([A-Za-z][\w.-]*\s[^\]]*)\](?!\()")
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
STEP = re.compile(r"^\s*(?:\*\*)?Step\s+\d+\s*[:.](?:\*\*)?\s*")
LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
WEX = re.compile(r"^\s*\*\*Worked example\s+(\d+(?:\.\d+)*)\s*:\s*")
LABEL = re.compile(r"^\s*\*\*(Pitfall|Not on [^*:]+|Unverified|Background)\s*:\s*\*\*")
CONNECTS = re.compile(r"^\s*\*\*(How it['’]s tested|Connects to|Depth)\s*:\s*\*\*")
WARN = ("Pitfall", "Not on", "Unverified")

SYMBOLS = {
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠", "Rightarrow": "⇒",
    "implies": "⇒", "Leftrightarrow": "⇔", "iff": "⇔", "rightarrow": "→", "to": "→",
    "leftarrow": "←", "gets": "←", "times": "×", "cdot": "·", "infty": "∞", "pm": "±",
    "approx": "≈", "in": "∈", "notin": "∉", "subseteq": "⊆", "subset": "⊂", "cup": "∪",
    "cap": "∩", "emptyset": "∅", "varnothing": "∅", "neg": "¬", "lnot": "¬", "land": "∧",
    "wedge": "∧", "lor": "∨", "vee": "∨", "forall": "∀", "exists": "∃", "ldots": "…",
    "dots": "…", "cdots": "…", "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π", "sigma": "σ",
    "tau": "τ", "phi": "φ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ",
    "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Omega": "Ω",
}
DIGRAPHS = [("<=>", "⇔"), ("<=", "≤"), (">=", "≥"), ("!=", "≠"), ("=>", "⇒"), ("->", "→"),
            ("...", "…"), ("−", "-"), ("’", "'"), ("‘", "'"),
            ("“", '"'), ("”", '"')]
LATEX = re.compile(r"\\([A-Za-z]+)")
TOKEN = re.compile(r"[A-Za-z]+|\d+(?:\.\d+)*|[^\sA-Za-z0-9.,;:!?()\[\]{}*_`'\"|\\]")


def tokens(text):
    for a, b in DIGRAPHS:
        text = text.replace(a, b)
    text = LATEX.sub(lambda m: SYMBOLS.get(m.group(1), "\\" + m.group(1)), text)
    return TOKEN.findall(text)


def words(text):
    return " ".join(tokens(text))


class Doc:
    """One side, as lists of (value, section label) to diff."""

    def __init__(self):
        self.text, self.headings, self.cites, self.links = [], [], [], []
        self.callouts, self.items = [], []


# ---- the Markdown side ----------------------------------------------------------------------

def read_md(md):
    doc, label, item, fence = Doc(), "top", False, False
    for raw in md.split("\n"):
        q = QUOTE.match(raw)
        body = raw[q.end():] if q else raw
        if FENCE.match(body):
            fence, item = not fence, False
            continue
        if fence:
            doc.text += [(t, label) for t in tokens(body)]
            continue
        body = COMMENT.sub(" ", body)
        if not body.strip():
            item = False
            continue
        if RULE.match(body) or TABLE_SEP.match(body):
            continue
        h = HEADING.match(body)
        if h and not q:
            ids = ANCHOR.findall(h.group(2))
            title = words(LINK.sub(r"\1", ANCHOR.sub(" ", h.group(2))))
            level = len(h.group(1)) + 1
            m = H1.match(body)
            label = ids[0] if ids else (f"sec-{m.group(1)}" if m else label)
            doc.headings.append(((level, ids[0] if ids else "", title), label))
            item = False
            continue
        ids = ANCHOR.findall(body)
        body = ANCHOR.sub(" ", body)
        m = WEX.match(body)
        if m:
            doc.callouts.append((("example", ids[0] if ids else "",
                                  f"Worked example {m.group(1)}"), label))
            body = body[m.end():]
        elif LABEL.match(body):
            m = LABEL.match(body)
            kind = "warn" if m.group(1).startswith(WARN) else "background"
            doc.callouts.append(((kind, "", words(m.group(1))), label))
            body = body[m.end():]
        elif CONNECTS.match(body):
            doc.callouts.append((("connects", "", words(CONNECTS.match(body).group(1))), label))
        step, lst = STEP.match(body), LIST.match(body)
        if step or lst:
            kind = "step" if step else "li"
            doc.items.append(((kind, ids[0] if ids else ""), label))
            body = body[(step or lst).end():]
            item = True
        elif not (item and raw.startswith("  ")):
            item = False
        for c in CITE.finditer(body):
            doc.cites.append((" ".join(c.group(1).split()), label))
        body = CITE.sub(" ", body)
        for link in LINK.finditer(body):
            if link.group(2).startswith("#"):
                doc.links.append((link.group(2), label))
        body = LINK.sub(r"\1", body)
        doc.text += [(t, label) for t in tokens(body)]
    return doc


# ---- the HTML side --------------------------------------------------------------------------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
        "track", "wbr"}


class FragReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doc, self.stack, self.label = Doc(), [], "top"

    def inside(self, key):
        return next((e for e in reversed(self.stack) if key in e), None)

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        e = {"tag": tag}
        self.stack.append(e)
        if tag in ("figure", "svg") or self.inside("hide"):
            e["hide"] = True
            return
        if tag == "section" and a.get("id"):
            self.label = a["id"]
        if tag in ("h2", "h3", "h4"):
            e["heading"], e["id"] = [], a.get("id", "")
            if a.get("id"):
                self.label = a["id"]
        if "lab" in cls:
            e["lab"] = []
        if tag == "a" and "slink" in cls:
            e["slink"] = []
        if tag == "a" and "xref" in cls:
            self.doc.links.append((a.get("href", ""), self.label))
        if tag == "details" and "callout" in cls:
            e["callout"] = ["example", a.get("id", ""), None]
            self.doc.callouts.append((e["callout"], self.label))
        elif tag == "div" and "callout" in cls and not {"def", "key"} & set(cls):
            e["callout"] = ["warn" if "warn" in cls else "background", "", None]
            self.doc.callouts.append((e["callout"], self.label))
        elif tag == "div" and "callout" in cls:
            e["callout"] = ["ignored", "", None]
        if tag == "p" and "connects" in cls:
            e["callout"] = ["connects", "", None]
            e["strong"] = True
            self.doc.callouts.append((e["callout"], self.label))
        owner = self.inside("strong")
        if tag == "strong" and owner is not None and owner["callout"][2] is None:
            e["capture"] = []
        if tag == "li":
            parent = next((x for x in reversed(self.stack[:-1]) if x["tag"] in ("ol", "ul")), None)
            kind = "step" if parent and "steps" in parent.get("cls", ()) else "li"
            self.doc.items.append(((kind, a.get("id", "")), self.label))
        e["cls"] = cls

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            e = self.stack.pop()
            if "heading" in e:
                level = int(e["tag"][1])
                self.doc.headings.append(((level, e["id"], words("".join(e["heading"]))),
                                          self.label))
            if "lab" in e:
                owner = self.inside("callout")
                if owner is not None and owner["callout"][2] is None:
                    owner["callout"][2] = words("".join(e["lab"]))
            if "slink" in e:
                self.doc.cites.append((" ".join("".join(e["slink"]).split()), self.label))
            if "capture" in e:
                owner = self.inside("strong")
                owner["callout"][2] = words("".join(e["capture"]))
            if e["tag"] == tag:
                break

    def handle_data(self, data):
        if self.inside("hide"):
            return
        for key in ("lab", "slink"):
            e = self.inside(key)
            if e is not None:
                e[key].append(data)
                return
        e = self.inside("capture")
        if e is not None:
            e["capture"].append(data)
        e = self.inside("heading")
        if e is not None:
            e["heading"].append(data)
            return
        self.doc.text += [(t, self.label) for t in tokens(data)]


def read_html(html):
    r = FragReader()
    r.feed(html)
    r.close()
    for i, (c, label) in enumerate(r.doc.callouts):
        r.doc.callouts[i] = (tuple(c[:2]) + (c[2] or "",), label)
    r.doc.callouts = [c for c in r.doc.callouts if c[0][0] != "ignored"]
    return r.doc


# ---- the comparison -------------------------------------------------------------------------

def show(what, values):
    if what == "text":
        more = " ..." if len(values) > 14 else ""
        return "'" + " ".join(values[:14]) + more + "'"
    return "; ".join(" ".join(str(p) for p in v if p) if isinstance(v, tuple) else str(v)
                     for v in values[:6]) + (" ..." if len(values) > 6 else "")


def diff(name, what, xs, ys):
    out = []
    a, b = [x[0] for x in xs], [y[0] for y in ys]
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        if op == "insert" and j1 < len(ys):
            label = ys[j1][1]
        elif i1 < len(xs):
            label = xs[i1][1]
        else:
            label = xs[-1][1] if xs else "top"
        if op == "replace":
            msg = (f"the fragment has {show(what, b[j1:j2])} where the notes have "
                   f"{show(what, a[i1:i2])}")
        elif op == "delete":
            msg = f"the fragment drops {show(what, a[i1:i2])}"
        else:
            msg = f"the fragment adds {show(what, b[j1:j2])}"
        out.append(f"{name} {label}: {what}: {msg}")
    return out


def compare_pair(md, html, name):
    """Every difference between one notes file and its fragment, a line each."""
    a, b = read_md(md), read_html(html)
    out = []
    for what in ("headings", "text", "cites", "links", "callouts", "items"):
        out += diff(name, "citations" if what == "cites" else what,
                    getattr(a, what), getattr(b, what))
    return out


# ---- self-test ------------------------------------------------------------------------------

SAMPLE_MD = r"""# §1 Sample

Search order matters. It sets every trace, as [§1.1 Order](#sec-1-order) shows.

## 1.1 Order {#sec-1-order}

**Depth:** Use (inferred: a sample with no format statement).

A frontier is the set of generated, unexpanded nodes [D1 p.2]. A cost of n^2 grows fast, and g(n) <= h(n) is the test `if a < b`.

Step 1: Pop the cheapest node.
Step 2: Expand it [D1 p.3].

> **Worked example 1.1: Two pops** {#ex-1-pops}
> Setup: costs 4 and 9.
> Step 1: pop 4.
> Step 2: pop 9.
> **Result:** 4, then 9.
> **Conclusion:** the cheaper node goes first.

1. **Pop:** the cheapest first ([Worked example 1.1](#ex-1-pops)).
2. **Ties:** alphabetical.

| Pop | Cost |
| --- | --- |
| 1 | 4 |

**How it's tested:** give the pop order. Practice: [HW1 Q2c].

> **Pitfall:** a stale entry still pops; skip it.

> **Background:** only [D1 p.9] has the proof; no practice question asks for it. The heap keeps the minimum at its root.

<!-- FIG fig-1-heap: a heap of 4 and 9 -->

### Members

- a) **Push:** add a node. {#set-ops-a}
- b) **Pop:** remove the cheapest. {#set-ops-b}
"""
SAMPLE_HTML = r"""<section class="note" id="sec-1">
  <h2><span class="n">§1</span> Sample</h2>
  <p>Search order matters. It sets every trace, as <a class="xref" href="#sec-1-order">§1.1 Order</a> shows.</p>
  <h3 id="sec-1-order">1.1 Order</h3>
  <p class="connects"><strong>Depth:</strong> Use (inferred: a sample with no format statement).</p>
  <div class="callout def"><div class="lab">Definition</div><p>A frontier is the set of generated, unexpanded nodes <a class="slink">D1 p.2</a>.</p></div>
  <p>A cost of \(n^2\) grows fast, and \(g(n) \le h(n)\) is the test <code>if a &lt; b</code>.</p>
  <ol class="steps"><li>Pop the cheapest node.</li><li>Expand it <a class="slink">D1 p.3</a>.</li></ol>
  <details class="callout example wex" id="ex-1-pops">
  <summary><span class="lab">Worked example 1.1</span><span class="wex-t">Two pops</span></summary>
  <p>Setup: costs 4 and 9.</p>
  <ol class="steps"><li>pop 4.</li><li>pop 9.</li></ol>
  <p><strong>Result:</strong> 4, then 9.</p>
  <p><strong>Conclusion:</strong> the cheaper node goes first.</p>
  </details>
  <ol><li><strong>Pop:</strong> the cheapest first (<a class="xref" href="#ex-1-pops">Worked example 1.1</a>).</li><li><strong>Ties:</strong> alphabetical.</li></ol>
  <div class="tbl-wrap"><table><thead><tr><th>Pop</th><th>Cost</th></tr></thead><tbody><tr><td>1</td><td>4</td></tr></tbody></table></div>
  <p class="connects"><strong>How it’s tested:</strong> give the pop order. Practice: <a class="slink">HW1 Q2c</a>.</p>
  <div class="callout warn"><div class="lab">Pitfall</div><p>a stale entry still pops; skip it.</p></div>
  <div class="callout"><div class="lab">Background</div><p>only <a class="slink">D1 p.9</a> has the proof; no practice question asks for it. The heap keeps the minimum at its root.</p></div>
  <figure id="fig-1-heap"><svg viewBox="0 0 200 80" role="img" aria-label="A heap of 4 and 9"><rect class="bx fill-surf" x="80" y="10" width="40" height="24"/><text x="100" y="27" class="mono">4</text></svg>
  <figcaption>Fig 1.1. A heap of 4 and 9.</figcaption></figure>
  <h4>Members</h4>
  <ul><li id="set-ops-a"><strong>a)</strong> <strong>Push:</strong> add a node.</li><li id="set-ops-b"><strong>b)</strong> <strong>Pop:</strong> remove the cheapest.</li></ul>
</section>
"""


class TextNodes(HTMLParser):
    """Each text node's offset in the raw HTML, outside figures, headings, labels and citations."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.starts = [0]
        for line in html.split("\n"):
            self.starts.append(self.starts[-1] + len(line) + 1)
        self.stack, self.nodes = [], []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            cls = (dict(attrs).get("class") or "").split()
            self.stack.append("off" if tag in ("figure", "svg", "h2", "h3", "h4")
                              or {"lab", "slink"} & set(cls) else tag)

    def handle_endtag(self, tag):
        if tag not in VOID and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if "off" not in self.stack:
            line, col = self.getpos()
            self.nodes.append((self.starts[line - 1] + col, data))


def splice(text, start, end, new):
    """`text` with [start, end) replaced by `new`."""
    return text[:start] + new + text[end:]


SENTENCE = re.compile(r"[A-Z][^.!?]*[.!?](?=\s|$)")
NUMBER = re.compile(r"(?<![\w.])\d+(?!\.?\d)(?![A-Za-z])")
STEPS = re.compile(r"<ol\b[^>]*\bclass=\"[^\"]*\bsteps\b[^\"]*\"[^>]*>(.*?)</ol>", re.S)
ITEM = re.compile(r"<li\b[^>]*>.*?</li>", re.S)
TAG = re.compile(r"<[^>]*>")
SLINK = re.compile(r"<a\b[^>]*\bclass=\"[^\"]*\bslink\b[^\"]*\"[^>]*>.*?</a>", re.S)


def plant_sentence(html):
    for at, data in TextNodes(html).nodes:
        for m in SENTENCE.finditer(data):
            if len(tokens(m.group(0))) >= 3:
                return splice(html, at + m.start(), at + m.end(), ""), repr(m.group(0)[:40])
    return None, "no sentence of three words or more"


def plant_number(html):
    for at, data in TextNodes(html).nodes:
        m = NUMBER.search(data)
        if m:
            new = str(int(m.group(0)) + 1)
            return (splice(html, at + m.start(), at + m.end(), new),
                    f"{m.group(0)} to {new} in {data.strip()[:30]!r}")
    return None, "no number in the text"


def plant_swap(html):
    for ol in STEPS.finditer(html):
        lis = list(ITEM.finditer(html, ol.start(1), ol.end(1)))
        for x, y in zip(lis, lis[1:]):
            if words(TAG.sub("", x.group(0))) != words(TAG.sub("", y.group(0))):
                between = html[x.end():y.start()]
                return (splice(html, x.start(), y.end(), y.group(0) + between + x.group(0)),
                        f"two steps at offset {x.start()}")
    return None, "no two different steps"


def plant_cite(html):
    m = SLINK.search(html)
    if m:
        return splice(html, m.start(), m.end(), ""), TAG.sub("", m.group(0))
    return None, "no citation"


PLANTS = (("a dropped sentence", plant_sentence), ("a changed number", plant_number),
          ("two swapped steps", plant_swap), ("a dropped citation", plant_cite))


def self_test(pairs):
    fails = []

    def report(ok, msg):
        print(f"{'PASS' if ok else 'FAIL'}  {msg}", flush=True)
        if not ok:
            fails.append(msg)

    clean = compare_pair(SAMPLE_MD, SAMPLE_HTML, "sample")
    report(not clean, "the clean sample pair passes"
           + ("" if not clean else ": " + " | ".join(clean[:3])))
    corpora = [("sample", SAMPLE_MD, SAMPLE_HTML)] + [(n, md, html) for n, md, html in pairs]
    if not pairs:
        print("SKIP  the hub: no fragment with its notes file yet")
    for name, md, html in corpora:
        base = set(compare_pair(md, html, name))
        for what, planter in PLANTS:
            planted, where = planter(html)
            if planted is None:
                if name == "sample":
                    report(False, f"sample: nowhere to plant {what}: {where}")
                else:
                    print(f"SKIP  {name}: {what}: {where}")
            elif planted == html:
                report(False, f"{name}: PLANT DID NOTHING: {what} ({where}) left the copy "
                              "as it was")
            else:
                new = [p for p in compare_pair(md, planted, name) if p not in base]
                report(bool(new), f"{name}: {what} ({where}): "
                       + (f"caught ({new[0]})" if new else "NOT CAUGHT"))
    print("SELF-TEST OK" if not fails else f"SELF-TEST FAILED: {len(fails)} of the checks")
    return 1 if fails else 0


def load(only):
    """([(fragment name, notes text, fragment text)], [problems with the pairing])."""
    notes, problems, pairs = {}, [], []
    for p in sorted(glob.glob(os.path.join(HUB, "notes", "*.md"))):
        with open(p, encoding="utf-8") as f:
            text = f.read()
        m = H1.match(text.split("\n", 1)[0])
        if m:
            notes[m.group(1)] = (os.path.relpath(p, HUB), text)
    frags = {}
    for p in sorted(glob.glob(os.path.join(FRAG_DIR, "sec*.html"))):
        m = FRAG.search(os.path.basename(p))
        if m:
            frags[m.group(1)] = p
    want = {re.sub(r"\D", "", o) for o in only}
    for n in sorted(set(notes) | set(frags), key=int):
        if want and n not in want:
            continue
        if n not in frags:
            problems.append(f"{notes[n][0]}: no _build/frag/sec{n}.html")
        elif n not in notes:
            problems.append(f"_build/frag/sec{n}.html: no notes file opens with # §{n}")
        else:
            with open(frags[n], encoding="utf-8") as f:
                pairs.append((f"sec{n}.html", notes[n][1], f.read()))
    return pairs, problems


def main(argv):
    if argv == ["--self-test"]:
        return self_test(load([])[0])
    if any(a.startswith("-") for a in argv):
        print("usage: fidelity.py [--self-test | secN ...]", file=sys.stderr)
        return 2
    pairs, problems = load(argv)
    for name, md, html in pairs:
        problems += compare_pair(md, html, name)
    for p in problems:
        print(p)
    if not pairs and not problems:
        print("fidelity.py: no fragment to check")
        return 1
    print(f"FIDELITY OK: {len(pairs)} fragments" if not problems
          else f"{len(problems)} DIFFERENCES")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
