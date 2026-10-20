"""skills/exam-prep/scripts: reveal_slice.py and render_pdf.sh, on synthetic sources.

The deck is a made-up reveal.js page with the shapes real decks have: a vertical stack, an
unclosed <p>, a section tag inside a script string, hidden slides, nested divs, comments between
slides and a section after the slides container. The PDF is
built by hand here (three pages, one of them nearly empty), so no course material is involved.
render_pdf.sh's tests skip without poppler-utils."""
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, "skills", "exam-prep", "scripts")
RENDER = os.path.join(SCRIPTS, "render_pdf.sh")

_spec = importlib.util.spec_from_file_location("reveal_slice",
                                               os.path.join(SCRIPTS, "reveal_slice.py"))
reveal_slice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reveal_slice)

DECK = """<!doctype html>
<html><head><title>Synthetic deck</title>
</head><body>
<div class="reveal"><div class="slides">
  <!-- ===== TITLE ===== -->
  <section id="s-title"><h1>Widgets 101</h1><p>Lecture 1</section>
  <script>var tpl = "<section id='not-a-slide'>x</section>";</script>
  <section id="s-stack">
    <section id="s-a"><h2>Stacked A</h2><p>first<li>loose item</section>
    <section id="s-cut-child" data-visibility="hidden"><h2>Cut child</h2></section>
    <section><h2>Stacked B</h2><div class="fragment"><div>nested</div></div></section>
  </section>
  <section id="s-cut" data-visibility="hidden"><h2>Cut</h2></section>
  <!-- between slides -->
  <section id="s-last"><h2>Last</h2>
    <p>Formula: a &lt; b</p>
  </section>
</div></div>
<section id="after-the-deck">Not a slide</section>
<script>Reveal.initialize();</script>
</body></html>
"""


def make_pdf(path, pages):
    """A minimal valid PDF, one Helvetica text page per entry (lines split on newlines)."""
    n = len(pages)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [%s] /Count %d >>"
            % (" ".join(f"{4 + 2 * i} 0 R" for i in range(n)), n),
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        body = " ".join(f"({line}) Tj T*" for line in text.split("\n"))
        stream = f"BT /F1 12 Tf 72 720 Td 14 TL {body} ET"
        objs.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    with open(path, "wb") as f:
        f.write(out)


def png_width(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return int.from_bytes(head[16:20], "big")


class RevealMap(unittest.TestCase):
    def test_fragments_follow_reveal_numbering(self):
        rows = reveal_slice.slides(DECK)
        self.assertEqual([(frag, s.id) for frag, s in rows],
                         [("#/0", "s-title"), ("#/1/0", "s-a"), ("#/1/1", None),
                          ("#/2", "s-last")])

    def test_a_section_in_a_script_hidden_or_after_the_container_is_not_a_slide(self):
        ids = [s.id for _, s in reveal_slice.slides(DECK)]
        for sid in ("not-a-slide", "s-cut", "s-cut-child", "after-the-deck"):
            self.assertNotIn(sid, ids)

    def test_the_container_ends_at_its_own_close(self):
        rows = reveal_slice.slides('<div class="slides"><section>A</section></div>'
                                   '<section>after the deck</section></div>')
        self.assertEqual([f for f, _ in rows], ["#/0"])

    def test_a_markdown_section_warns(self):
        deck = ('<div class="slides"><section id="m" data-markdown><textarea data-template>'
                "## A\n---\n## B</textarea></section><section>C</section></div>")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rows = reveal_slice.slides(deck)
        self.assertEqual([f for f, _ in rows], ["#/0", "#/1"])
        self.assertIn("slide #/0 is a data-markdown section", err.getvalue())

    def test_spans_cover_each_section_exactly(self):
        rows = dict(reveal_slice.slides(DECK))
        self.assertTrue(DECK[rows["#/0"].start:rows["#/0"].end].startswith('<section id="s-title">'))
        self.assertTrue(DECK[rows["#/0"].start:rows["#/0"].end].endswith("</section>"))
        last = DECK[rows["#/2"].start:rows["#/2"].end]
        self.assertIn("a &lt; b", last)
        self.assertNotIn("between slides", last)

    def test_not_a_reveal_deck(self):
        with self.assertRaises(SystemExit):
            reveal_slice.slides("<html><body><section>x</section></body></html>")

    def test_unclosed_slide_is_refused(self):
        for deck in ('<div class="slides"><section><p>open',
                     '<div class="slides"><section>open</div><section>later</section>',
                     '<div class="slides"><section data-visibility="hidden">open'):
            with self.assertRaises(SystemExit, msg=deck):
                reveal_slice.slides(deck)


class RevealCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.deck = os.path.join(self.tmp.name, "deck.html")
        with open(self.deck, "w", encoding="utf-8") as f:
            f.write(DECK)

    def run_script(self, *args):
        return subprocess.run(["python3", "-I", os.path.join(SCRIPTS, "reveal_slice.py"), *args],
                              capture_output=True, text=True)

    def test_map(self):
        r = self.run_script("map", self.deck)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "TOTAL horizontal slides: 3 | slides: 4")
        self.assertEqual(lines[2], "#/1/0\ts-a\tStacked A first loose item")

    def test_slice_with_skip_and_base(self):
        out = os.path.join(self.tmp.name, "_build", "slices", "chunk.html")  # a new directory
        r = self.run_script("slice", self.deck, "--from", "1", "--to", "2", "--skip", "2",
                            "--base", "https://example.edu/deck.html", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("<!-- ===== SLIDE #/1/0 (cite as https://example.edu/deck.html#/1/0) =====",
                      text)
        self.assertIn("SLIDE #/1/1 ", text)
        self.assertNotIn("s-title", text)
        self.assertNotIn("s-last", text)
        self.assertIn("wrote", r.stdout)

    def test_images_resolve_against_the_deck_and_stay_in_its_folder(self):
        deck = os.path.join(self.tmp.name, "sources", "lectures", "d2.html")
        os.makedirs(os.path.dirname(deck))
        with open(deck, "w", encoding="utf-8") as f:
            f.write('<img src="logo.png"><div class="slides">'
                    '<section><img src="img/a b.png"><img data-src="img/lazy.png"></section>'
                    '<section><img src="/static/root.png"><img src="https://cdn.example.org/x.svg">'
                    '<img src="data:image/png;base64,AAAA"><img src="../../../../etc/x.png">'
                    '<svg><image href="img/a b.png"/></svg></section>'
                    '<section data-background-image="img/bg.jpg"><object data="img/o.svg"></object>'
                    '<embed src="img/e.pdf"></section></div>')
        out = os.path.join(self.tmp.name, "_build", "slices", "d2-images.tsv")
        r = self.run_script("images", deck, "--base", "https://example.edu/c/lec/d2.html",
                            "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = os.path.join(os.path.dirname(deck), "d2_files")
        with open(out, encoding="utf-8") as f:
            rows = [line.rstrip("\n").split("\t") for line in f]
        self.assertEqual(rows, [
            ["img/a b.png", "https://example.edu/c/lec/img/a%20b.png", f"{folder}/img/a b.png"],
            ["img/lazy.png", "https://example.edu/c/lec/img/lazy.png", f"{folder}/img/lazy.png"],
            ["/static/root.png", "https://example.edu/static/root.png",
             f"{folder}/_abs/example.edu/static/root.png"],
            ["https://cdn.example.org/x.svg", "https://cdn.example.org/x.svg",
             f"{folder}/_abs/cdn.example.org/x.svg"],
            ["../../../../etc/x.png", "https://example.edu/etc/x.png",
             f"{folder}/_abs/example.edu/etc/x.png"],
            ["img/bg.jpg", "https://example.edu/c/lec/img/bg.jpg", f"{folder}/img/bg.jpg"],
            ["img/o.svg", "https://example.edu/c/lec/img/o.svg", f"{folder}/img/o.svg"],
            ["img/e.pdf", "https://example.edu/c/lec/img/e.pdf", f"{folder}/img/e.pdf"]])
        self.assertIn("skipped data:image/png", r.stderr)
        self.assertIn("8 images, 1 skipped", r.stdout)

    def test_a_src_cannot_smuggle_rows_into_the_tsv(self):
        deck = os.path.join(self.tmp.name, "d3.html")
        with open(deck, "w", encoding="utf-8") as f:
            f.write('<div class="slides"><section>'
                    '<img src="img/a.png&#10;x&#9;https://example.edu/p.png&#9;CLAUDE.md&#10;img/b">'
                    '<img src="img/c%0Ax%09https:%2F%2Fexample.edu%2Fp.png%09CLAUDE.md">'
                    '<img src="img/ok.png"></section></div>')
        out = os.path.join(self.tmp.name, "d3.tsv")
        r = self.run_script("images", deck, "--base", "https://example.edu/c/d3.html", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual(lines[0].split("\t")[0], "img/ok.png")
        self.assertNotIn("CLAUDE.md", "\n".join(lines))
        self.assertIn("a control character in its src", r.stderr)
        self.assertIn("a control character in its URL or path", r.stderr)
        self.assertIn("1 images, 2 skipped", r.stdout)

    def test_no_row_lets_curl_glob_its_way_out_of_the_folder(self):
        deck = os.path.join(self.tmp.name, "d4.html")
        with open(deck, "w", encoding="utf-8") as f:
            f.write('<div class="slides"><section>'
                    '<img src="img/a%231?{/../../../../../CLAUDE.md}">'
                    '<img src="img/b[1-2].png"><img src="img/c.png?v={1,2}#top">'
                    '</section></div>')
        out = os.path.join(self.tmp.name, "d4.tsv")
        r = self.run_script("images", deck, "--base", "https://example.edu/c/d4.html", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding="utf-8") as f:
            rows = [line.rstrip("\n").split("\t") for line in f]
        for src, url, dest in rows:
            self.assertNotRegex(url, r"[{}\[\]#]", src)
            self.assertNotRegex(dest, r"[{}\[\]#]", src)
        self.assertEqual([row[1] for row in rows],
                         ["https://example.edu/c/img/c.png?v=%7B1,2%7D"])
        self.assertIn("a character curl globs", r.stderr)

    def test_the_fetch_loop_turns_globbing_off_and_spares_zsh_path(self):
        with open(os.path.join(SCRIPTS, "..", "workflows", "01-ingest.md"), encoding="utf-8") as f:
            loop = next(l for l in f if "reveal_slice.py images" in l)
        self.assertIn('curl -g -fsSL --create-dirs "$url" -o "$dest"', loop)
        self.assertNotIn("read -r src url path", loop)

    def test_empty_range_fails(self):
        r = self.run_script("slice", self.deck, "--from", "7", "--to", "9",
                            "-o", os.path.join(self.tmp.name, "x.html"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no slides", r.stderr)


@unittest.skipUnless(all(shutil.which(t) for t in ("pdfinfo", "pdftoppm", "pdftotext")),
                     "poppler-utils not installed")
class RenderPdf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pdf = os.path.join(self.tmp.name, "lecture.pdf")
        dense = "\n".join(f"Line {i} of the dense page with plenty of words on it" for i in range(8))
        make_pdf(self.pdf, ["Title page\n" + dense, "x", dense])

    def run_script(self, *args, env=None):
        return subprocess.run(["bash", RENDER, *args], cwd=self.tmp.name, capture_output=True,
                              text=True, env=env)

    def path(self, *parts):
        return os.path.join(self.tmp.name, "_build", *parts)

    def test_renders_every_page_and_names_thin_ones(self):
        r = self.run_script(self.pdf, "D1")
        self.assertEqual(r.returncode, 0, r.stderr)
        for n in (1, 2, 3):
            self.assertGreater(os.path.getsize(self.path("pages", "D1", f"p-00{n}.png")), 0)
        with open(self.path("text", "D1", "p-003.txt"), encoding="utf-8") as f:
            self.assertIn("Line 7 of the dense page", f.read())
        self.assertIn("D1: pages 1-3 of 3 rendered at 100 dpi", r.stdout)
        self.assertIn("D1: 1 thin pages (under 200 characters; view their images): 2", r.stdout)

    def test_no_temp_files_are_left(self):
        self.assertEqual(self.run_script(self.pdf, "D1").returncode, 0)
        for sub in ("pages", "text"):
            left = [n for n in os.listdir(self.path(sub, "D1")) if n.startswith(".")]
            self.assertEqual(left, [], sub)

    def test_rerun_skips_rendered_pages(self):
        self.assertEqual(self.run_script(self.pdf, "D1").returncode, 0)
        png = self.path("pages", "D1", "p-001.png")
        os.utime(png, (1, 1))
        self.assertEqual(self.run_script(self.pdf, "D1").returncode, 0)
        self.assertEqual(os.stat(png).st_mtime, 1)

    def test_range_renders_only_those_pages(self):
        r = self.run_script(self.pdf, "D2", "2", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.path("pages", "D2", "p-001.png")))
        self.assertTrue(os.path.exists(self.path("pages", "D2", "p-003.png")))

    def test_a_dpi_override_renders_again_into_its_own_directory(self):
        self.assertEqual(self.run_script(self.pdf, "D1").returncode, 0)
        png = self.path("pages", "D1", "p-001.png")
        os.utime(png, (1, 1))
        r = self.run_script(self.pdf, "D1", "1", "1", env=dict(os.environ, RENDER_DPI="50"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rendered at 50 dpi into _build/pages/D1@50dpi/", r.stdout)
        self.assertEqual(os.stat(png).st_mtime, 1)
        # A US-letter page is 612 points wide: 850 px at 100 dpi, 425 px at 50.
        self.assertEqual(png_width(png), 850)
        self.assertEqual(png_width(self.path("pages", "D1@50dpi", "p-001.png")), 425)
        self.assertEqual(os.listdir(self.path("pages", "D1@50dpi")), ["p-001.png"])

    def test_a_bad_dpi_is_refused(self):
        for bad in ("abc", "0", "5", "100; rm -rf x"):
            r = self.run_script(self.pdf, "D1", env=dict(os.environ, RENDER_DPI=bad))
            self.assertEqual(r.returncode, 2, bad)
            self.assertIn("RENDER_DPI must be a number", r.stderr)

    def test_refusals(self):
        for args, msg in [((self.pdf, "D1", "0", "2"), "outside 1-3"),
                          ((self.pdf, "D1", "2", "9"), "outside 1-3"),
                          ((self.pdf, "../up"), "bad doc id"),
                          ((os.path.join(self.tmp.name, "none.pdf"), "D1"), "no such file"),
                          ((self.pdf,), "usage")]:
            r = self.run_script(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn(msg, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "up")))


if __name__ == "__main__":
    unittest.main()
