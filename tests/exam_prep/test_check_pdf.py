"""skills/exam-prep/scripts/check_pdf.py on PDFs written here, by the real pdfinfo, pdffonts and
mutool: no browser.

Each PDF is built by hand: pages of a given size and rotation, text drawn at a font size, a
text-matrix scale and a distance from the left edge, in base-14 Helvetica (not embedded) or in
DejaVu Sans Mono embedded whole under any name. The sheet's HTML and the layout file beside it are
written here too, in print_sheet.mjs's shape. Pages, paper and rotation; embedding, with a font
name longer than pdffonts' column; the floor measured at the printed size (a scaled matrix counts,
Chromium's 4.995 for 5 passes); text too near an edge; the section sign, the word "notes" and
--forbid text (required), in the PDF and the HTML; and every layout rule: a layout from another
print, a sheet changed or gone since, a remote request, a clipped side, a box wider than its
column, a side split across pages, the fill warnings, a malformed or missing file, and
--no-layout."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECK_PDF = os.path.join(REPO, "skills", "exam-prep", "scripts", "check_pdf.py")
TTF = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"  # monospace: one width fits every glyph
TOOLS = ("pdfinfo", "pdffonts", "mutool")
HAVE_TOOLS = all(shutil.which(t) for t in TOOLS)
LETTER = (792, 612)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def esc(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252")


def write_pdf(path, pages, embed=True, font="DejaVuSansMono"):
    """pages: [(width, height, rotate, [(size, scale, text[, x]), ...])]; each text on its own
    line, 40 pt in from the left unless x says otherwise. An embedded font gets the name `font`."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    if embed:
        with open(TTF, "rb") as f:
            ttf = f.read()
        widths = " ".join(["602"] * 224)
        objs[3] = (b"<< /Type /Font /Subtype /TrueType /BaseFont /" + font.encode() + b" /FirstChar 32 "
                   b"/LastChar 255 /Widths [" + widths.encode() + b"] /Encoding /WinAnsiEncoding "
                   b"/FontDescriptor 4 0 R >>")
        objs[4] = (b"<< /Type /FontDescriptor /FontName /" + font.encode() + b" /Flags 33 /FontBBox "
                   b"[-1021 -463 1793 1232] /ItalicAngle 0 /Ascent 928 /Descent -236 "
                   b"/CapHeight 729 /StemV 80 /FontFile2 5 0 R >>")
        objs[5] = (f"<< /Length {len(ttf)} /Length1 {len(ttf)} >>\nstream\n".encode() + ttf
                   + b"\nendstream")
    else:
        objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    kids = []
    for k, (w, h, rot, texts) in enumerate(pages):
        page_id, content_id = 6 + 2 * k, 7 + 2 * k
        kids.append(f"{page_id} 0 R")
        ops, y = [], h - 40
        for size, scale, text, *x in texts:
            ops.append(b"BT /F1 %g Tf %g 0 0 %g %g %d Tm (" % (size, scale, scale, (x or [40])[0], y)
                       + esc(text)
                       + b") Tj ET")
            y -= 20
        body = b"\n".join(ops)
        objs[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Rotate {rot} "
                         f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>").encode()
        objs[content_id] = f"<< /Length {len(body)} >>\nstream\n".encode() + body + b"\nendstream"
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    top = max(objs)
    offsets = {}
    for i in range(1, top + 1):
        if i in objs:
            offsets[i] = len(out)
            out += f"{i} 0 obj\n".encode() + objs[i] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {top + 1}\n0000000000 65535 f \n".encode()
    for i in range(1, top + 1):
        out += (f"{offsets[i]:010d} 00000 n \n" if i in offsets else "0000000000 65535 f \n").encode()
    out += f"trailer\n<< /Size {top + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as f:
        f.write(out)


def side(fill=(5, 0.9), overflow=False, columns=5, wide=()):
    return {"id": "s", "columns": columns, "overflow": overflow, "wide": list(wide),
            "fill": None if fill is None else {"col": fill[0], "bottom": fill[1]}}


@unittest.skipUnless(HAVE_TOOLS and os.path.isfile(TTF), "needs pdfinfo, pdffonts, mutool and DejaVu Sans Mono")
class CheckPdfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.pdf = os.path.join(self.tmp, "sheet.pdf")
        self.html = os.path.join(self.tmp, "sheet.html")

    def sheet(self, pages=None, embed=True, layout="match", sides=None, remote=(), source="<p>x</p>"):
        """Write the PDF, the sheet's HTML (source) and, unless layout is None, the layout file
        ("match": this PDF's hash)."""
        if pages is None:
            pages = [(*LETTER, 0, [(6, 1, "Side one text")]), (*LETTER, 0, [(6, 1, "Side two")])]
        write_pdf(self.pdf, pages, embed=embed)
        with open(self.html, "w", encoding="utf-8") as f:
            f.write(source)
        if layout is not None:
            sha = sha256(self.pdf) if layout == "match" else layout
            data = {"pdf_sha256": sha, "sheet": "sheet.html", "sheet_sha256": sha256(self.html),
                    "remote": list(remote),
                    "pages": sides if sides is not None else [side() for _ in pages]}
            self.layout(data)

    def layout(self, data, raw=None):
        with open(self.pdf[:-4] + ".layout.json", "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(data))

    def run_check(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", CHECK_PDF, self.pdf, "--floor", "6",
                               "--forbid", "Nobody Here", *args],
                              capture_output=True, text=True, env=env)

    def passes(self, *args):
        r = self.run_check(*args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL CHECKS PASS", r.stdout)
        return r.stdout

    def fails(self, want, *args):
        r = self.run_check(*args)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(want, r.stdout)
        return r.stdout

    def bad(self, want, *args, env=None):
        r = self.run_check(*args, env=env)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(want, r.stderr)

    # The PDF alone

    def test_a_good_sheet_passes(self):
        self.sheet()
        out = self.passes()
        self.assertIn("2 pages", out)
        self.assertIn("fonts: DejaVuSansMono", out)
        self.assertIn("page 1: smallest text 6.00 pt", out)
        self.assertNotIn("WARN", out)

    def test_page_count(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "only side")])])
        self.fails("1 pages, want 2")
        self.passes("--pages", "1")

    def test_portrait_fails_and_a_turned_portrait_page_passes(self):
        self.sheet(pages=[(612, 792, 0, [(6, 1, "a")]), (*LETTER, 0, [(6, 1, "b")])])
        self.fails("page 1 is 612 x 792 pt, want letter landscape")
        self.sheet(pages=[(612, 792, 90, [(6, 1, "a")]), (612, 792, 270, [(6, 1, "b")])])
        self.passes()

    def test_paper(self):
        a4 = (841.89, 595.28, 0, [(6, 1, "a4 side")])
        self.sheet(pages=[a4, a4])
        self.fails("want letter landscape (792 x 612)")
        self.passes("--paper", "a4")
        self.sheet()
        self.fails("want a4 landscape", "--paper", "a4")
        # Letter's width with A4's height.
        self.sheet(pages=[(792, 595.28, 0, [(6, 1, "a")]), (*LETTER, 0, [(6, 1, "b")])])
        self.fails("page 1 is 792 x 595.28 pt, want letter landscape")

    def test_an_unembedded_font_fails(self):
        self.sheet(embed=False)
        self.fails("font Helvetica is not embedded")

    def test_the_floor_is_measured_at_the_printed_size(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "body"), (5.5, 1, "small")]),
                          (*LETTER, 0, [(6, 1, "fine")])])
        self.fails("page 1: 5.50 pt is below the 6 pt floor, in: small")
        # A 12 pt font drawn at half scale prints at 5.4 pt, as scaled SVG text does.
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "body")]), (*LETTER, 0, [(12, 0.45, "scaled")])])
        self.fails("page 2: 5.40 pt is below the 6 pt floor, in: scaled")
        # Chromium prints a 6 pt superscript as 5.995.
        self.sheet(pages=[(*LETTER, 0, [(5.995, 1, "sup")]), (*LETTER, 0, [(6, 1, "x")])])
        self.passes()

    def test_blank_runs_dont_set_the_floor(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "text"), (3, 1, "   ")]), (*LETTER, 0, [(6, 1, "x")])])
        self.passes()

    def test_a_section_sign_fails(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "see §4.4")]), (*LETTER, 0, [(6, 1, "x")])])
        self.fails("page 1: a section sign points into the notes (FB-134): see §4.4")

    def test_the_word_notes_warns(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "as in the Notes")]),
                          (*LETTER, 0, [(6, 1, "footnotes and a notebook")])])
        out = self.passes()
        self.assertIn("WARN page 1: says \"notes\"", out)
        self.assertNotIn("page 2: says", out)

    def test_forbid_matches_across_lines_and_case_and_isnt_echoed(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "Name: Ada"), (6, 1, "LOVELACE  id")]),
                          (*LETTER, 0, [(6, 1, "x")])])
        # run_check's own --forbid is #1.
        out = self.fails('page 1 prints --forbid #2 (1 match): "Name: [#2] id" (FB-132)',
                         "--forbid", "ada  lovelace")
        self.assertNotIn("lovelace", out.lower())
        self.passes("--forbid", "Grace")

    def test_a_hit_shows_its_words_with_every_forbid_masked(self):
        # A surname that is also a word: the masked line tells the theorem from the name.
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "By Green's theorem, Ada Green wrote")]),
                          (*LETTER, 0, [(6, 1, "x")])])
        out = self.fails("page 1 prints --forbid #2 (2 matches): \"By [#2]'s theorem, [#3] [#2] wrote\"",
                         "--forbid", "Green", "--forbid", "Ada")
        self.assertIn("page 1 prints --forbid #3 (1 match)", out)
        self.assertNotIn("green", out.lower())

    def test_a_shorter_form_listed_first_shows_no_part_of_a_longer_one(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "notes by Ada Lovelace, and by Ada Bell Smith")]),
                          (*LETTER, 0, [(6, 1, "x")])])
        out = self.fails('"notes by [#3], and by [#5]"', "--forbid", "Lovelace", "--forbid", "Ada Lovelace",
                         "--forbid", "Ada Bell", "--forbid", "Bell Smith")
        for part in ("ada", "lovelace", "bell", "smith"):
            self.assertNotIn(part, out.split("fonts:")[1].lower().replace("dejavusansmono", ""))

    def test_every_match_is_counted_and_shown(self):
        # Six ordinary words, then the name: the name's match is shown too.
        texts = [(6, 1, f"a bell curve {k}") for k in range(6)] + [(6, 1, "from A. Bell, HW3")]
        self.sheet(pages=[(*LETTER, 0, texts), (*LETTER, 0, [(6, 1, "x")])])
        out = self.fails('page 1 prints --forbid #2 (7 matches): "a [#2] curve 0', "--forbid", "Bell")
        shown = out.split("(7 matches): ")[1].split(" (FB-132)")[0].split("; ")
        self.assertEqual(len(shown), 7)
        self.assertIn("from A. [#2], HW3", shown[-1])
        words = set(" ".join(f"a [#2] curve {k}" for k in range(6)).split()) | set("from A. [#2], HW3".split())
        for w in shown:
            # Whole words only: no word and no mask cut in half at either end.
            self.assertLessEqual(set(w.strip('"').split()), words, w)

    def test_a_name_across_a_line_break_is_masked_in_every_message(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "see §2, Ada"), (5, 1, "Lovelace notes")]),
                          (*LETTER, 0, [(6, 1, "x")])])
        out = self.fails("page 1: a section sign points into the notes (FB-134): see §2, [#2]",
                         "--forbid", "Ada Lovelace")
        self.assertIn("below the 6 pt floor, in: [#2] notes", out)
        self.assertIn('the exam (FB-134): [#2] notes', out)
        self.assertNotIn("lovelace", out.lower())
        self.assertNotIn("ada", out.lower().replace("dejavusansmono", ""))

    def test_forbid_matches_whole_words(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "a linear list, Lin's lemma")]),
                          (*LETTER, 0, [(6, 1, "x")])])
        self.passes("--forbid", "Li", "--forbid", "lemm")
        self.fails("page 1 prints --forbid #3", "--forbid", "Li", "--forbid", "Lin")

    def test_a_long_font_name_is_read_from_the_right(self):
        # pdffonts pads names to 36 characters but never cuts a longer one.
        name = "AAAAAA+DejaVuSansCondensed-BoldOblique"
        write_pdf(self.pdf, [(*LETTER, 0, [(6, 1, "a")]), (*LETTER, 0, [(6, 1, "b")])], font=name)
        out = self.passes("--no-layout")
        self.assertIn(f"fonts: {name}", out)

    def test_text_near_the_edge_fails(self):
        self.sheet(pages=[(*LETTER, 0, [(6, 1, "edge", 5)]), (*LETTER, 0, [(6, 1, "fine", 20)])])
        out = self.fails("page 1: text 5.0 pt from the page's edge, where printers clip")
        self.assertNotIn("page 2: text", out)

    def test_no_output_ever_shows_a_forbid_text(self):
        # The invariant, over every message that quotes the sheet: the name sits in a small line,
        # a section-sign line, a "notes" line (split across a break), a wide box, a remote URL and
        # every part of the HTML, listed short form first.
        self.sheet(pages=[(*LETTER, 0, [(5, 1, "tiny Lovelace"), (6, 1, "see §2, Ada"),
                                        (6, 1, "Lovelace notes"), (6, 1, "al1234 here")]),
                          (*LETTER, 0, [(6, 1, "by A. Lovelace")])],
                   sides=[side(wide=['column 1: p "Ada Lovelace al1234"']), side()],
                   remote=["https://x.example/al1234/Lovelace.png"],
                   source='<title>Ada Lovelace</title><!-- al1234 --><img alt="A. Lovelace" src="x">')
        out = self.fails("FB-132", "--forbid", "Lovelace", "--forbid", "Ada Lovelace",
                         "--forbid", "A. Lovelace", "--forbid", "al1234")
        for kind in ("below the 6 pt floor", "a section sign", 'says "notes"', "wider than its column",
                     "the sheet requested", "page 1 prints", "page 2 prints", "sheet.html holds"):
            self.assertIn(kind, out)
        for form in ("lovelace", "al1234"):
            self.assertNotIn(form, out.lower())
        self.assertNotRegex(out.lower().replace("dejavusansmono", ""), r"(?<!\w)ada(?!\w)")

    # The layout file

    def test_a_layout_from_another_print_fails(self):
        self.sheet(layout="0" * 64)
        self.fails("measured another print: run print_sheet.mjs again")

    def test_a_remote_request_fails(self):
        self.sheet(remote=["https://fonts.example.com/x.css"])
        self.fails("the sheet requested https://fonts.example.com/x.css: it must print offline")

    def test_a_clipped_side_fails(self):
        self.sheet(sides=[side(overflow=True), side()])
        self.fails("side 1 clips content past its last column or its foot (FB-138)")
        self.sheet(sides=[side(), side(fill=(7, 0.3))])
        self.fails("side 2 clips content past its last column")
        self.sheet(sides=[side(fill=(2, 1.02)), side(fill=(5, 1.0))])
        out = self.fails("side 1 clips content past its last column or its foot")
        self.assertNotIn("side 2 clips", out)

    def test_a_box_wider_than_its_column_fails(self):
        self.sheet(sides=[side(), side(wide=['column 2: table.c "n a b c d e f"'])])
        self.fails('side 2, column 2: table.c "n a b c d e f": wider than its column (FB-138)')

    def test_box_text_and_urls_are_masked(self):
        self.sheet(sides=[side(), side(wide=['column 2: p "by Ada Lovelace"'])],
                   remote=["https://x.example/~al1234/fig.png"])
        out = self.fails('side 2, column 2: p "by [#2]": wider than its column', "--forbid", "Ada Lovelace",
                         "--forbid", "al1234")
        self.assertIn("the sheet requested https://x.example/~[#3]/fig.png", out)
        self.assertNotIn("lovelace", out.lower())
        self.assertNotIn("al1234", out)

    def test_the_sheets_html_is_checked_for_forbid_text(self):
        css = "<style>.page { background: gray; } li { color: white; } .fill { margin: 0 }</style>"
        cases = [
            ("<title>Ada&#32;Lovelace</title>", "its text"),
            ('<img alt="by Ada Lovelace" src="x.png">', "the alt attribute of a <img>"),
            ("<!-- made by ada lovelace -->", "a comment"),
            ("<p>Ada\n  LOVELACE</p>", "its text"),
        ]
        for source, where in cases:
            with self.subTest(source=source):
                self.sheet(source=css + source + "<p>clean</p>")
                out = self.fails(f"sheet.html holds --forbid #2 (1 match): in {where}: ",
                                 "--forbid", "ada lovelace")
                self.assertNotIn("page 1 prints", out)
                self.assertNotIn("lovelace", out.lower())
        # Every match, across the HTML's parts.
        self.sheet(source="<title>Ada Lovelace</title><!-- by Ada Lovelace --><p>x</p>")
        self.fails('sheet.html holds --forbid #2 (2 matches): in its text: "[#2]"; in a comment: "by [#2]"',
                   "--forbid", "ada lovelace")
        # The CSS's words aren't the sheet's: a student named Gray, White or Li passes.
        self.sheet(source=css + "<p>a gray area</p>".replace("gray", "grey"))
        self.passes("--forbid", "Gray", "--forbid", "White", "--forbid", "Li", "--forbid", "margin")
        # Nor are its class names, ids or SVG geometry: a student named Page or Ed passes.
        self.sheet(source='<div class="page" id="side1"><svg viewBox="0 0 9 9"><line class="ed" '
                          'x1="1"/></svg><p class="foot">ok</p></div>')
        self.passes("--forbid", "Page", "--forbid", "Ed", "--forbid", "side1", "--forbid", "foot")
        # But the attributes that carry words are read.
        for attr in ('aria-label="Ada Lovelace"', 'data-who="Ada Lovelace"', 'title="Ada Lovelace"'):
            with self.subTest(attr=attr):
                self.sheet(source=f"<figure {attr}><p>x</p></figure>")
                self.fails(f"(1 match): in the {attr.split('=')[0]} attribute of a <figure>: \"[#2]\"",
                           "--forbid", "ada lovelace")

    def test_a_changed_or_missing_sheet_fails(self):
        self.sheet()
        with open(self.html, "a", encoding="utf-8") as f:
            f.write("<p>later edit</p>")
        self.fails("sheet.html changed since it was printed: run print_sheet.mjs again")
        os.remove(self.html)
        self.fails("the sheet sheet.html is gone")

    def test_sides_must_match_pages(self):
        self.sheet(sides=[side()])
        self.fails("the layout has 1 sides and the PDF 2 pages")

    def test_fill_warnings(self):
        self.sheet(sides=[side(fill=(4, 0.95)), side(fill=(5, 0.6))])
        out = self.passes()
        self.assertIn("side 1: content ends in column 4 of 5, 0.95 down", out)
        self.assertIn("WARN side 1 ends in column 4 of 5, 0.95 down: room for a larger body", out)
        self.assertIn("WARN side 2 ends in column 5 of 5, 0.6 down", out)
        self.sheet(sides=[side(fill=(5, 0.84)), side(fill=None)])
        out = self.passes()
        self.assertNotIn("WARN side 1", out)
        self.assertIn("WARN side 2 ends in empty", out)

    def test_a_named_layout_file(self):
        self.sheet(layout=None)
        self.bad("no layout file at")
        os.mkdir(os.path.join(self.tmp, "logs"))
        other = os.path.join(self.tmp, "logs", "elsewhere.json")
        with open(other, "w", encoding="utf-8") as f:
            json.dump({"pdf_sha256": sha256(self.pdf), "sheet": "../sheet.html",
                       "sheet_sha256": sha256(self.html), "remote": [], "pages": [side(), side()]}, f)
        self.passes("--layout", other)

    def test_no_layout_warns_and_skips(self):
        self.sheet(layout=None)
        out = self.passes("--no-layout")
        self.assertIn("WARN no layout file: overflow and fill unchecked", out)
        r = self.run_check("--no-layout", "--layout", "x.json")
        self.assertEqual(r.returncode, 2)

    def test_malformed_layout_files(self):
        self.sheet()
        good = {"pdf_sha256": "0" * 64, "sheet": "sheet.html", "sheet_sha256": "0" * 64,
                "remote": [], "pages": [side(), side()]}
        cases = [
            "[]", "{", "[" * 100000 + "]" * 100000,
            json.dumps({**good, "pdf_sha256": 5}),
            json.dumps({k: v for k, v in good.items() if k != "sheet"}),
            json.dumps({**good, "sheet": ["sheet.html"]}),
            json.dumps({**good, "sheet_sha256": None}),
            json.dumps({**good, "pages": [{**side(), "wide": "x"}, side()]}),
            json.dumps({**good, "pages": [{**side(), "wide": [3]}, side()]}),
            json.dumps({**good, "pages": [{k: v for k, v in side().items() if k != "wide"}, side()]}),
            json.dumps({**good, "remote": "x"}),
            json.dumps({**good, "remote": [1]}),
            json.dumps({**good, "pages": {}}),
            json.dumps({**good, "pages": ["x", side()]}),
            json.dumps({**good, "pages": [side(columns=True), side()]}),
            json.dumps({**good, "pages": [side(columns=0), side()]}),
            json.dumps({**good, "pages": [{**side(), "overflow": 0}, side()]}),
            json.dumps({**good, "pages": [{**side(), "fill": {"col": 1.5, "bottom": 1}}, side()]}),
            json.dumps({**good, "pages": [{**side(), "fill": {"col": 1, "bottom": "1"}}, side()]}),
            json.dumps({**good, "pages": [{**side(), "fill": {"col": 1, "bottom": True}}, side()]}),
            json.dumps({**good, "pages": [{**side(), "fill": {"col": 1}}, side()]}),
            json.dumps({**good, "pages": [{**side(), "fill": [1, 2]}, side()]}),
            json.dumps(good).replace('"bottom": 0.9', '"bottom": NaN', 1),
            json.dumps(good).replace('"bottom": 0.9', '"bottom": 1e999', 1),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:60]):
                self.layout(None, raw=raw)
                self.bad("layout file")

    # Usage

    def test_usage(self):
        self.sheet()
        for args in (["--floor", "0"], ["--pages", "0"], ["--paper", "a3"], ["--forbid", " "]):
            with self.subTest(args=args):
                self.assertEqual(self.run_check(*args).returncode, 2)
        for args in ([], ["--floor", "6"], ["--forbid", "x"]):
            with self.subTest(args=args):
                r = subprocess.run([sys.executable, "-I", CHECK_PDF, self.pdf, *args],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 2)
        self.pdf = os.path.join(self.tmp, "missing.pdf")
        self.bad("no PDF at")

    def test_an_unreadable_pdffonts_row_is_refused(self):
        self.sheet()
        bin_dir = os.path.join(self.tmp, "bin")
        os.mkdir(bin_dir)
        for t in ("pdfinfo", "mutool"):
            os.symlink(shutil.which(t), os.path.join(bin_dir, t))
        fake = os.path.join(bin_dir, "pdffonts")
        with open(fake, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho 'name type emb'\necho '---- ---- ---'\necho 'Odd TrueType maybe'\n")
        os.chmod(fake, 0o755)
        self.bad("pdffonts printed a row this can't read: Odd TrueType maybe", env={"PATH": bin_dir})

    def test_a_missing_tool_names_its_package(self):
        self.sheet()
        bin_dir = os.path.join(self.tmp, "bin")
        os.mkdir(bin_dir)
        for t in ("pdfinfo", "pdffonts"):
            os.symlink(shutil.which(t), os.path.join(bin_dir, t))
        self.bad("install mupdf-tools", env={"PATH": bin_dir})


if __name__ == "__main__":
    unittest.main()
