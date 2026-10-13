"""hooks/md_render.py: markdown to terminal lines with ANSI styles, for the replies popup
(tmux/pass-last) and the banner after a /pass (hooks/pass_banner.py). Stdlib only."""
import importlib.util
import os
import re
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("md_render",
                                              os.path.join(REPO, "hooks", "md_render.py"))
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

E = chr(27) + "["
BULLET, BAR = chr(0x2022), chr(0x2502)
CJK = chr(0x65E5) + chr(0x672C) + chr(0x8A9E)   # three wide characters: 6 cells


def plain(text, width=80):
    return md.render(text, width, color=False)


def strip(text):
    return re.sub(re.escape(E) + r"[0-9;]*m", "", text)


class Inline(unittest.TestCase):
    def test_bold_italic_code_and_links(self):
        out = md.render("a **b** *i* `c` [t](http://x) z", 80)
        self.assertEqual(out, f"a {E}1mb{E}0m {E}3mi{E}0m {E}36mc{E}0m {E}4mt{E}0m z")
        self.assertEqual(plain("a **b** *i* `c` [t](http://x) z"), "a b i c t z")

    def test_styles_nest(self):
        out = md.render("**bold `code` end**", 80, reset="own")
        self.assertEqual(out, f"{E}1mbold{E}22m {E}1;36mcode{E}22;38;5;246m {E}1mend{E}22m")

    def test_a_star_inside_a_word_or_alone_is_not_italic(self):
        self.assertEqual(plain("2 * 3 and a*b*c and snake_case_name"),
                         "2 * 3 and a*b*c and snake_case_name")

    def test_markup_inside_a_code_span_stays_literal(self):
        self.assertEqual(plain("run `**not bold**` now"), "run **not bold** now")

    def test_a_backslash_escape_shows_the_character(self):
        self.assertEqual(plain(r"a \*literal\* star"), "a *literal* star")

    def test_punctuation_after_a_span_stays_on_its_word(self):
        # `code`, is one word: a wrap never leaves the comma at the start of a line.
        out = plain("xxxxxxxxxxxxxxxx `code`, next", 21).split("\n")
        self.assertEqual(out, ["xxxxxxxxxxxxxxxx", "code, next"])


class Blocks(unittest.TestCase):
    def test_headings_are_bold_magenta_without_hashes(self):
        self.assertEqual(md.render("## Two **x** ##", 80), f"{E}1;35mTwo{E}0m {E}1;35mx{E}0m")
        self.assertEqual(plain("# One"), "One")

    def test_lists_hang_and_keep_nesting(self):
        text = ("- first item that is long enough to wrap\n"
                "  - nested item\n"
                "1. one\n"
                "10. ten wraps here too ok\n"
                "* star")
        self.assertEqual(plain(text, 24).split("\n"), [
            "  " + BULLET + " first item that is",
            "    long enough to wrap",
            "    " + BULLET + " nested item",
            "  1. one",
            "  10. ten wraps here too",                     # 24 cells: fits exactly
            "      ok",
            "  " + BULLET + " star"])

    def test_an_indented_line_keeps_its_list_items_hanging_indent(self):
        self.assertEqual(plain("- one\n  more of one\n- two"),
                         "  " + BULLET + " one\n    more of one\n  " + BULLET + " two")

    def test_line_breaks_stay_and_blank_runs_collapse(self):
        self.assertEqual(plain("\n\nDone: one\nNext: two\n\n\n\nthree\n\n"),
                         "Done: one\nNext: two\n\nthree")

    def test_fenced_code_has_a_dim_bar_and_never_wraps(self):
        long = "x" * 50
        text = "before\n```bash\n" + long + "\n  **kept** `as is`\n```\nafter"
        self.assertEqual(plain(text, 20).split("\n"),
                         ["before", BAR + " " + long, BAR + "   **kept** `as is`", "after"])
        out = md.render("```\ncode\n```", 80, reset="own")
        self.assertEqual(out, f"{E}2m{BAR} {E}22m{E}33mcode{E}38;5;246m")

    def test_an_unclosed_fence_runs_to_the_end(self):
        self.assertEqual(plain("```\na\nb"), BAR + " a\n" + BAR + " b")

    def test_a_table_that_fits_gets_box_lines(self):
        text = "| Name | N |\n|---|--:|\n| `a` | 1 |\n| bb | 22 |"
        out = plain(text, 40).split("\n")
        corners = [chr(0x250C), chr(0x251C), chr(0x2514)]
        self.assertEqual([line[0] for line in out],
                         [corners[0], BAR, corners[1], BAR, BAR, corners[2]])
        self.assertEqual(out[1], BAR + " Name " + BAR + "  N " + BAR)   # aligned as its column
        self.assertEqual(out[3], BAR + " a    " + BAR + "  1 " + BAR)   # right-aligned column
        self.assertEqual(len({md.cells(line) for line in out}), 1)
        colored = md.render(text, 40)
        self.assertIn(f"{E}1mName{E}0m", colored)                    # the header is bold
        self.assertIn(f"{E}36ma{E}0m", colored)

    def test_a_table_too_wide_falls_back_to_dim_raw_rows(self):
        rows = ["| a long first cell | another long cell |", "|---|---|",
                "| x | y |"]
        self.assertEqual(plain("\n".join(rows), 30), "\n".join(rows))
        self.assertEqual(md.render("\n".join(rows), 30).split("\n")[0],
                         f"{E}2m{rows[0]}{E}0m")

    def test_a_rule(self):
        self.assertEqual(plain("a\n\n---\n\nb", 30), "a\n\n" + chr(0x2500) * 30 + "\n\nb")


class Cells(unittest.TestCase):
    def test_wide_characters_count_two_cells(self):
        self.assertEqual(md.cells(CJK), 6)
        self.assertEqual(md.cells("e" + chr(0x0301)), 1)            # a combining accent
        self.assertEqual(md.cells("a" + chr(0x200D) + "b"), 2)      # a format character

    def test_wrap_by_cells_with_a_cjk_string(self):
        out = plain(" ".join([CJK] * 6), 20).split("\n")
        self.assertEqual(out, [" ".join([CJK] * 3)] * 2)            # 6+1+6+1+6 = 20 cells
        self.assertEqual(md.wrap([(" ".join([CJK] * 6), "")], 19), [" ".join([CJK] * 2)] * 3)
        for line in out:
            self.assertLessEqual(md.cells(line), 20)

    def test_a_word_longer_than_the_line_breaks_by_cells(self):
        out = plain(CJK * 5, 20).split("\n")                         # 30 cells
        self.assertEqual([md.cells(line) for line in out], [20, 10])
        self.assertEqual(plain("x" * 45, 20).split("\n"), ["x" * 20, "x" * 20, "x" * 5])

    def test_every_line_fits_the_width(self):
        text = "word " * 100 + "\n\n- " + "item " * 60 + "\n\n" + (CJK + " ") * 40
        for width in (20, 33, 80):
            for line in md.render(text, width).split("\n"):
                self.assertLessEqual(md.cells(strip(line)), width, (width, line))

    def test_wrap_plain_keeps_line_breaks_and_markup(self):
        self.assertEqual(md.wrap_plain("fix **this**\n\nthen that one thing here", 20),
                         ["fix **this**", "", "then that one thing", "here"])


class Escapes(unittest.TestCase):
    def test_color_off_adds_no_escapes(self):
        text = "# H\n\n**b** *i* `c`\n\n- x\n\n```\ny\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |"
        self.assertNotIn(chr(27), plain(text))

    def test_own_resets_never_emit_a_full_reset(self):
        text = "# H **x**\n\n**b** *i* `c` [l](u)\n\n- `x`\n\n```\ny\n```\n\n" \
               "| a | b |\n|---|---|\n| **1** | 2 |\n\n---"
        out = md.render(text, 80, reset="own")
        self.assertIn(chr(27), out)
        self.assertNotIn(E + "0m", out)
        self.assertNotIn(E + "m", out)

    def test_every_line_closes_what_it_opens(self):
        text = "**a long bold run that wraps across several lines here** and `code span`"
        for reset in ("own", "full"):
            for line in md.render(text, 20, reset=reset).split("\n"):
                self.assertEqual(md.cut(line + "x", len(line.encode()), reset), line)  # all closed

    def test_control_characters_are_dropped_before_any_escape(self):
        text = "red " + chr(27) + "[31mtext" + chr(7) + chr(0x9B) + chr(0x85) + chr(0x7F) \
               + " **b**"
        self.assertEqual(plain(text), "red [31mtext b")
        out = md.render(text, 80, reset="own")
        self.assertEqual(out, f"red [31mtext {E}1mb{E}22m")
        self.assertEqual(md.wrap_plain("a" + chr(27) + "b\r\nc", 20), ["ab", "c"])

    def test_a_lone_surrogate_becomes_a_question_mark(self):
        self.assertEqual(plain("a" + chr(0xD800) + "b"), "a?b")


class Cut(unittest.TestCase):
    def test_a_cut_closes_open_styles_and_never_splits_an_escape(self):
        line = md.render("**" + "b" * 30 + "** " + "`" + "c" * 30 + "`", 200, reset="own")
        for n in range(len(line.encode())):
            out = md.cut(line, n)
            self.assertLessEqual(len(out.encode()), n)
            self.assertNotIn(E + "0m", out)
            # no torn escape: every ESC starts a whole SGR
            self.assertEqual(strip(out).count(chr(27)), 0)
            opened = out.count(E + "1m") + out.count(E + "36m")
            closed = out.count(E + "22m") + out.count(E + "38;5;246m")
            self.assertEqual(opened, closed, out)

    def test_a_cut_keeps_characters_whole(self):
        out = md.cut(chr(0x00E9) * 10, 5)
        self.assertEqual(out, chr(0x00E9) * 2)

    def test_a_full_reset_cut(self):
        line = md.render("**" + "b" * 20 + "**", 80)
        self.assertEqual(md.cut(line, 12, reset="full"), f"{E}1mbbbb{E}0m")   # 4 + 4 + 4 bytes

    def test_a_line_that_fits_is_unchanged(self):
        self.assertEqual(md.cut("short", 100), "short")


class Pathological(unittest.TestCase):
    def test_a_64_kib_line_of_unclosed_openers_renders_fast(self):
        # An unclosed "*" or "[" used to scan to the line's end (7 s), and a run of backticks
        # was retried at every shorter length (minutes). The "x" keeps a line of backticks from
        # reading as a fence.
        # Each regex is linear on its own (the backstop off), and the backstop holds too.
        rising = "x" + "".join("`" * k + "a" for k in range(1, 340))
        texts = ("*a " * 21000, "[" * 60000, "[a " * 21000, "**a " * 16000, "**a" * 21000,
                 "x" + "`" * 60000, "x" + "` a" * 20000, rising, "[a](" * 16000,
                 "[a](b" * 13000, "x" + "\\``" * 20000, "**[`*" * 13000,
                 # line-level patterns
                 "# a" + " " * 65000 + "b", "# " + "#" * 65000 + " x", " " * 65000 + "x",
                 "-" + " -" * 30000 + "x", "|" + "a|" * 30000, "- " + "*a " * 21000,
                 # layout: a table padded to its widest row, a deep list indent
                 "|" + "a|" * 16000 + "\n|" * 16000, "| a | b |\n|---|---|\n" + "| x | y |\n" * 6000,
                 " " * 32000 + "- " + "x" * 32000, "\t" * 16000 + "- " + "x" * 48000)
        for inline_max in (md.INLINE_MAX, 10 ** 9):
            for text in texts:
                with self.subTest(text=text[:5], inline_max=inline_max), \
                        mock.patch.object(md, "INLINE_MAX", inline_max):
                    start = time.monotonic()
                    out = md.render(text, 80)
                    self.assertLess(time.monotonic() - start, 1.0)
                    self.assertLess(len(out), 4 * len(text) + 1000)   # no blow-up in size

    def test_text_over_inline_max_gets_no_inline_markup(self):
        long = "**b** " + "x" * md.INLINE_MAX
        self.assertTrue(md.render(long, 10 ** 5, color=False).startswith("**b** x"))
        self.assertTrue(md.render(long[:md.INLINE_MAX], 10 ** 5, color=False).startswith("b x"))

    def test_a_headings_closing_hashes_go(self):
        for text, want in (("# Title ##", "Title"), ("# Title#", "Title#"), ("# ###", ""),
                           ("## a # b", "a # b"), ("#  spaced   ", "spaced")):
            with self.subTest(text=text):
                self.assertEqual(md.render(text, 80, color=False), want)

    def test_links_and_the_accepted_code_span_limit(self):
        self.assertEqual(md.render("see [x](http://a.b/c) and [f(x)](u)", 80, color=False),
                         "see x and f(x)")
        # Accepted for linear time: a code span right after an escaped backtick doesn't open.
        self.assertEqual(md.render("\\``code`", 80, color=False), "``code`")

    def test_nested_and_plain_markup_still_render(self):
        self.assertEqual(md.render("*it* and [link](u) and **b *i* b**", 80, color=False),
                         "it and link and b i b")
        self.assertEqual(md.render("a ``b ` c`` d `e`", 80, color=False), "a b ` c d e")
        # Accepted for linear time: italic around a "*" keeps its asterisks.
        self.assertEqual(md.render("*a * b*", 80, color=False), "*a * b*")

    def test_a_tab_in_a_table_cell_keeps_the_borders_aligned(self):
        out = md.render("| a\tb | c |\n|---|---|\n| x | y |", 80, color=False).split("\n")
        self.assertEqual(len({md.cells(line) for line in out}), 1, out)

    def test_a_deep_list_indent_keeps_room_for_the_text(self):
        out = md.render(" " * 200 + "- an item long enough to wrap twice here", 40,
                        color=False).split("\n")
        self.assertLessEqual(max(md.cells(line) for line in out), 40)
        self.assertLessEqual(len(out), 3, out)

    def test_a_table_too_wide_or_too_big_shows_its_raw_rows(self):
        wide = "|" + "a|" * 30
        self.assertEqual(md.render(wide, 80, color=False), wide)
        big = "| a | b |\n" + "| x | y |\n" * md.TABLE_CELLS
        self.assertEqual(md.render(big, 80, color=False).split("\n")[0], "| a | b |")
        small = md.render("| a | b |\n|---|---|\n| x | y |", 80, color=False)
        self.assertTrue(small.startswith(chr(0x250C)), small)


if __name__ == "__main__":
    unittest.main()
