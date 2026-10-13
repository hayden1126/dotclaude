"""md_render: the markdown Claude writes, rendered for a terminal with ANSI styles (stdlib only).

tmux/pass-last (the Ctrl-b Up popup, through less -R) and hooks/pass_banner.py (the banner after a
/pass) load this file by path; they never put hooks/ on sys.path. Keep the source ASCII: build
non-ASCII characters with chr().

  render(text, width, color=True, reset="full")   the text as terminal lines, joined by newlines
  wrap_plain(text, width)                         plain text (a prompt) word-wrapped, no markup
  cut(line, nbytes, reset="own")                  a rendered line cut to nbytes, styles closed
  paint(text, style, color=True, reset="full")    text in one style (the letters of STYLES)

What render handles: **bold**, *italic*, code spans, [text](url) links (the text, underlined),
# headings, -, * and 1. lists with a hanging indent (nested indentation kept), fenced code (a
dim bar, not wrapped), pipe tables drawn with box lines when they fit the width (else the raw
rows, dim), and --- rules. A line break stays a line break (as Claude Code and GitHub comments
show one; a reply's "Done: ...\nNext: ..." lines stay apart), and each line wraps at word
boundaries by terminal cells: a wide (W or F) character is 2 cells, a combining or format
character 0. A word longer than the line is broken by cells. A list item's indented lines keep
its hanging indent, which leaves at least half the width for the text.

Its time stays near linear in the text, since a reply can hold anything (a 64 KiB line of
openers took seconds to minutes before; the comment above INLINE has the cases), and so does
its size: each input character yields at most a fixed amount of output (a 4-character rule
draws a 40-cell line, an empty line in a fence gets its bar), within 40 times the input's
bytes. A line over
INLINE_MAX (4,096) characters shows its markup raw, and a table wider than the width or with
more than TABLE_CELLS cells shows as its raw rows, dim.

Control characters (C0 but tab and newline, DEL, C1) are dropped before any escape is added, so
an escape sequence in the text never reaches the terminal. Every style opened on a line closes
on that line, so lines can be dropped or kept whole without leaving a style open. reset="full"
closes a style with 0m; reset="own" closes each with its own reset (22m bold and dim, 23m
italic, 24m underline) and a color by going back to BANNER_FG, and never emits 0m: Claude Code
draws a SessionStart systemMessage in that gray, and 0m or 39m (the terminal's default color)
would drop the gray for the rest of the line (PLAN.md, spike A9).
With color=False the markup is stripped and no escape is added; the layout is the same.

tests/setup/test_md_render.py holds the cases.
"""
import re
import unicodedata

CSI = chr(27) + "["
BULLET, BAR, HLINE = chr(0x2022), chr(0x2502), chr(0x2500)
# The box corners and joints of a table: top, middle (under the header), bottom.
BOX = {"top": (chr(0x250C), chr(0x252C), chr(0x2510)),
       "mid": (chr(0x251C), chr(0x253C), chr(0x2524)),
       "bot": (chr(0x2514), chr(0x2534), chr(0x2518))}
# A style is a string of these letters: (SGR on, its own reset).
STYLES = {"b": ("1", "22"), "d": ("2", "22"), "i": ("3", "23"), "u": ("4", "24"),
          "c": ("36", "39"), "y": ("33", "39"), "m": ("35", "39"), "g": ("32", "39")}
COLORS = "cymg"
BANNER_FG = "38;5;246"  # the gray Claude Code draws a SessionStart systemMessage in (spike A9)
CONTROL = re.compile("[%s]" % re.escape("".join(map(chr, [*range(0, 9), *range(11, 32),
                                                          *range(127, 160)]))))
SGR = re.compile(re.escape(CSI) + r"[0-9;]*m")
MIN_WIDTH = 20

INLINE = re.compile(
    r"\\(?P<esc>[!-/:-@\[-`{-~])"                       # a backslash escape: the char itself
    r"|(?<!`)(?P<tick>`+)(?!`)(?P<code>.+?)(?<!`)(?P=tick)(?!`)"   # a code span, literal inside
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|\[(?P<ltext>[^\[\]]+)\]\((?P<url>[^()\s]*)\)"
    r"|(?<![\w*])\*(?![\s*])(?P<ital>[^*]+?)(?<!\s)\*(?![\w*])")
# Kept linear on a 64 KiB line, since a reply can hold anything. Link text holds no "[" and
# italic text no "*", so an unclosed opener's scan stops at the next one (a line of "[" or "*a "
# took 7 s). A code span opens and closes only on whole backtick runs, as in CommonMark, so a
# long run isn't retried at every shorter length (a line of backticks took minutes). A link's
# URL holds no "(" (a line of "[a](" took 3 s). Accepted, both rare: italic around a "*"
# (*a * b*, or around a code span holding one) keeps its asterisks, and a code span right after
# an escaped backtick (\``code`) doesn't open (letting it open made "x" + "\``" * 20000 take
# 7 s). The backstop: text over INLINE_MAX characters gets no inline markup at all, so a pattern
# missed here costs at most a bounded square, not seconds.
INLINE_MAX = 4096
TABLE_CELLS = 4000     # a table with more cells than this shows as its raw rows
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})")
LIST = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")   # heading_text() drops a closing # run
# (in code: "(.*?)(\s+#+)?\s*$" took minutes on a heading with a long run of spaces)
HRULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
SEPARATOR = re.compile(r"^\s*:?-+:?\s*$")


def clean(text: str) -> str:
    """text as valid UTF-8 (a lone surrogate becomes '?'), CRLF as LF, no control characters."""
    text = text.encode("utf-8", "replace").decode("utf-8")
    return CONTROL.sub("", text.replace("\r\n", "\n"))


def cells(text: str) -> int:
    """Terminal cells: a wide or full-width character is 2, a combining or format one 0."""
    n = 0
    for ch in text:
        if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return n


def visible(line: str) -> str:
    """A rendered line without its escapes."""
    return SGR.sub("", line)


def _codes(style: str, reset: str) -> tuple[str, str]:
    """The (open, close) escapes for a style; the last color letter wins."""
    color = [c for c in style if c in COLORS][-1:]
    letters = [c for c in dict.fromkeys(style) if c not in COLORS] + color
    if not letters:
        return "", ""
    on = CSI + ";".join(STYLES[c][0] for c in letters) + "m"
    if reset == "full":
        return on, CSI + "0m"
    return on, CSI + ";".join(dict.fromkeys(_own(STYLES[c][1]) for c in letters)) + "m"


def _own(off: str) -> str:
    """A style's own reset for the banner: a color goes back to BANNER_FG, not to 39m."""
    return BANNER_FG if off == "39" else off


def paint(text: str, style: str, color: bool = True, reset: str = "full") -> str:
    """text in style, closed at its end; text itself with no color, style or text."""
    if not (color and style and text):
        return text
    on, off = _codes(style, reset)
    return on + text + off


def heading_text(text: str) -> str:
    """A heading's text without a closing run of #s (one after a blank, or the whole text)."""
    text = text.rstrip()
    bare = text.rstrip("#")
    if bare != text and (not bare or bare[-1].isspace()):
        return bare.rstrip()
    return text


def spans(text: str, style: str = "") -> list[tuple[str, str]]:
    """[(text, style)] for one paragraph's inline markdown; bold, italic and link text nest.
    Text over INLINE_MAX characters stays as it is (the backstop above INLINE)."""
    if len(text) > INLINE_MAX:
        return [(text, style)]
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], style))
        if m.group("esc") is not None:
            out.append((m.group("esc"), style))
        elif m.group("code") is not None:
            out.append((m.group("code"), style + "c"))
        elif m.group("bold") is not None:
            out.extend(spans(m.group("bold"), style + "b"))
        elif m.group("ltext") is not None:
            out.extend(spans(m.group("ltext"), style + "u"))
        else:
            out.extend(spans(m.group("ital"), style + "i"))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], style))
    return out


def words(pieces: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Words: runs of pieces with no whitespace between, so `code`, stays one word."""
    out, cur = [], []
    for seg, style in pieces:
        for part in re.split(r"(\s+)", seg):
            if not part:
                continue
            if part.isspace():
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append((part, style))
    if cur:
        out.append(cur)
    return out


def _split_word(word: list[tuple[str, str]], room: int) -> list[list[tuple[str, str]]]:
    """A word wider than room, broken into chunks of at most room cells (at least 1 char)."""
    chunks, cur, n = [], [], 0
    for seg, style in word:
        buf = ""
        for ch in seg:
            w = cells(ch)
            if n + w > room and n:
                if buf:
                    cur.append((buf, style))
                chunks.append(cur)
                cur, n, buf = [], 0, ""
            buf += ch
            n += w
        if buf:
            cur.append((buf, style))
    if cur:
        chunks.append(cur)
    return chunks


def wrap(pieces, width: int, first: tuple[str, int] = ("", 0), rest: tuple[str, int] = ("", 0),
         color: bool = True, reset: str = "full") -> list[str]:
    """Styled pieces word-wrapped to width cells. first and rest are (prefix, its cells) for the
    first line and the lines after (a list item's bullet and its hanging indent)."""
    lines, (cur, n), start = [], first, first[1]
    for word in words(pieces):
        size = sum(cells(s) for s, _ in word)
        room = width - rest[1]
        if size > room:                 # too long for any line: break it by cells
            parts = _split_word(word, max(room, 1))
        else:
            parts = [word]
        for part in parts:
            size = sum(cells(s) for s, _ in part)
            gap = 1 if n > start else 0
            if n + gap + size > width and n > start:
                lines.append(cur)
                (cur, n), start, gap = rest, rest[1], 0
            cur += " " * gap + "".join(paint(s, st, color, reset) for s, st in part)
            n += gap + size
    lines.append(cur)
    return [line.rstrip(" ") if not visible(line).strip() else line for line in lines]


def wrap_plain(text: str, width: int) -> list[str]:
    """Plain text (no markup) word-wrapped to width cells, each line on its own; blank lines
    kept, control characters dropped."""
    width = max(width, MIN_WIDTH)
    out = []
    for line in clean(text).expandtabs(4).split("\n"):
        out.extend(wrap([(line, "")], width, color=False))
    return out


def _row(line: str) -> list[str]:
    """A table row's cells: the outer pipes dropped, split on unescaped pipes."""
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") and not line.endswith("\\|") else line
    return [c.strip().replace("\\|", "|").expandtabs(4) for c in re.split(r"(?<!\\)\|", line)]


def table(rows: list[str], width: int, color: bool, reset: str) -> list[str]:
    """Pipe-table rows drawn with box lines (the header bold, under the separator row) when they
    fit width; else the raw rows, dim."""
    cellrows = [_row(r) for r in rows]
    header = len(cellrows) > 1 and all(SEPARATOR.match(c) for c in cellrows[1]) and cellrows[1]
    align = [("r" if c.strip().endswith(":") and not c.strip().startswith(":") else
              "c" if c.strip().startswith(":") and c.strip().endswith(":") else "l")
             for c in cellrows[1]] if header else []
    body = [r for k, r in enumerate(cellrows) if not (header and k == 1)]
    ncol = max(len(r) for r in body)
    if 3 * ncol + 1 > width or ncol * len(body) > TABLE_CELLS:
        # Too wide even with empty cells, or too big to draw: decided before padding, since
        # padding every row to ncol grew with the square of a crafted reply.
        return [paint(r.strip().expandtabs(4), "d", color, reset) for r in rows]
    body = [r + [""] * (ncol - len(r)) for r in body]
    align += ["l"] * (ncol - len(align))
    styled = [[spans(c, "b" if header and k == 0 else "") for c in r]
              for k, r in enumerate(body)]
    w = [max(cells("".join(s for s, _ in r[i])) for r in styled) for i in range(ncol)]
    if sum(w) + 3 * ncol + 1 > width:
        return [paint(r.strip().expandtabs(4), "d", color, reset) for r in rows]

    def line(kind):
        left, mid, right = BOX[kind]
        return paint(left + mid.join(HLINE * (x + 2) for x in w) + right, "d", color, reset)

    bar = paint(BAR, "d", color, reset)
    out = [line("top")]
    for k, r in enumerate(styled):
        cols = []
        for i, pieces in enumerate(r):
            pad = w[i] - cells("".join(s for s, _ in pieces))
            lead = pad if align[i] == "r" else pad // 2 if align[i] == "c" else 0
            text = "".join(paint(s, st, color, reset) for s, st in pieces)
            cols.append(" " * (lead + 1) + text + " " * (pad - lead + 1))
        out.append(bar + bar.join(cols) + bar)
        if k == 0 and header:
            out.append(line("mid"))
    out.append(line("bot"))
    return out


def _starts_block(line: str) -> bool:
    return bool(FENCE.match(line) or LIST.match(line) or HEADING.match(line)
                or HRULE.match(line) or line.lstrip().startswith("|"))


def render(text: str, width: int, color: bool = True, reset: str = "full") -> str:
    """text (markdown) as terminal lines width cells wide, joined by newlines; code blocks and
    tables that don't fit are not wrapped. Runs of blank lines become one, and the ends have
    none."""
    width = max(width, MIN_WIDTH)
    lines = clean(text).split("\n")
    out, i = [], 0

    def para(pieces, first=("", 0), rest=("", 0)):
        out.extend(wrap(pieces, width, first, rest, color, reset))

    while i < len(lines):
        line = lines[i]
        fence = FENCE.match(line)
        if fence:
            indent, mark = len(fence.group(1)), fence.group(2)
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(mark):
                code = lines[i]
                code = code[min(indent, len(code) - len(code.lstrip(" "))):]
                out.append(paint(BAR + " ", "d", color, reset)
                           + paint(code.expandtabs(4), "y", color, reset))
                i += 1
            i += 1
            continue
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.extend(table(rows, width, color, reset))
            continue
        if HRULE.match(line):
            out.append(paint(HLINE * min(width, 40), "d", color, reset))
            i += 1
            continue
        m = HEADING.match(line)
        if m:
            para(spans(heading_text(m.group(2)), "bm"))
            i += 1
            continue
        m = LIST.match(line)
        if m:
            # The hanging indent leaves at least half the width for the text: a deep one left
            # no room and put one character per line, each line carrying the whole indent.
            mark = BULLET if m.group(2) in "-*+" else m.group(2)
            indent = min(len(m.group(1).expandtabs(4)) + 2,
                         max(0, width - width // 2 - len(mark) - 1))
            item = [m.group(3).strip()]
            i += 1
            while (i < len(lines) and lines[i].strip() and lines[i][:1].isspace()
                   and not _starts_block(lines[i])):
                item.append(lines[i].strip())
                i += 1
            first = " " * indent + mark + " "
            hang = (" " * cells(first), cells(first))
            para(spans(item[0]), (first, cells(first)), hang)
            for more in item[1:]:
                para(spans(more), hang, hang)
            continue
        if not line.strip():
            out.append("")
            i += 1
            continue
        para(spans(line.strip()))
        i += 1
    squeezed = []
    for line in out:
        if line or (squeezed and squeezed[-1]):
            squeezed.append(line)
    while squeezed and not squeezed[-1]:
        squeezed.pop()
    return "\n".join(squeezed)


def _closer(open_codes: list[str], reset: str) -> str:
    if not open_codes:
        return ""
    if reset == "full":
        return CSI + "0m"
    resets = {on: off for on, off in STYLES.values()}
    return CSI + ";".join(dict.fromkeys(_own(resets[c]) for c in open_codes)) + "m"


def cut(line: str, nbytes: int, reset: str = "own") -> str:
    """A rendered line cut to at most nbytes of UTF-8: never inside an escape or a character,
    and every style still open closed at the cut (with reset's kind of close)."""
    if len(line.encode("utf-8")) <= nbytes:
        return line
    resets = {on: off for on, off in STYLES.values()}
    out, used, open_codes = [], 0, []
    for tok in re.findall(re.escape(CSI) + r"[0-9;]*m|.", line, re.S):
        now = list(open_codes)
        if tok.startswith(CSI):
            codes = tok[len(CSI):-1].split(";")
            while codes:
                code = codes.pop(0) or "0"
                if code == "38":   # an extended color (BANNER_FG): it ends the open color
                    del codes[:2 if codes[:1] == ["5"] else 4]
                    code = "39"
                if code == "0":
                    now = []
                elif code in resets:
                    now.append(code)
                else:
                    now = [c for c in now if resets.get(c) != code]
        size = len(tok.encode("utf-8"))
        if used + size + len(_closer(now, reset).encode("utf-8")) > nbytes:
            break
        out.append(tok)
        used += size
        open_codes = now
    return "".join(out) + _closer(open_codes, reset)
