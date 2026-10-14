"""tmux/tmux-tab-bar: the grouped multi-row tab bar (stdlib only).

The pure parts (classify, group_windows, lay_out, render, the source-file quoting) run
in-process. `layout` runs as a subprocess against a fake tmux (a stateful Python stub that
answers the list commands from a JSON file and runs `source-file -` through a model of tmux's
config lexer), and against real tmux servers on private sockets, which the Bash sandbox blocks:
that class skips there."""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "tmux-tab-bar")
CONF = os.path.join(REPO, "tmux", "claude.conf")


def load():
    loader = importlib.machinery.SourceFileLoader("tmux_tab_bar", SCRIPT)
    spec = importlib.util.spec_from_loader("tmux_tab_bar", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


tb = load()
Group = tb.Group

# Every character a generated row may hold: the template's own text, digits and window ids.
ALPHABET = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
               " #{}[]=,:;|/@?^()\\*+-_.!$…◐✳★▸│┃♯·")   # · from the title strip

HOSTILE = "#(touch x)%,}\n\x1b[31m#{E:pwn}"   # cleans to "(touch x)%,}[31m{E:pwn}"
BENIGN = "abcdefghijklmnopqrstuvwxyz"


def tabs(*indexes):
    return [(f"@{i}", i) for i in indexes]


def tab_ids(row):
    return [item[1] for item in row if item[0] == "tab"]


# --- repos on disk ------------------------------------------------------------------------------

def make_repo(root, name, lanes=(), others=(), records=None):
    """A main checkout root/name with a .git dir; each lane and other worktree at
    root/<id> with a .git file. Lanes get <common>/lanes/<id>/lane.json naming their path
    (records: id -> raw bytes to write instead). Returns the lead's path."""
    lead = os.path.join(root, name)
    common = os.path.join(lead, ".git")
    os.makedirs(common)
    for wt in list(lanes) + list(others):
        path = os.path.join(root, wt)
        os.makedirs(os.path.join(common, "worktrees", wt))
        os.makedirs(path)
        with open(os.path.join(path, ".git"), "w") as f:
            f.write(f"gitdir: {common}/worktrees/{wt}\n")
    for lane in lanes:
        os.makedirs(os.path.join(common, "lanes", lane))
        raw = (records or {}).get(lane)
        if raw is None:
            raw = json.dumps({"id": lane, "path": os.path.join(root, lane)}).encode()
        with open(os.path.join(common, "lanes", lane, "lane.json"), "wb") as f:
            f.write(raw)
    return lead


class Classify(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def test_lead_lane_and_agent_worktree(self):
        lead = make_repo(self.root, "dotclaude", lanes=["tab-bar"], others=["agent-a5b6"])
        t = tb.classify(lead)
        self.assertEqual((t.kind, t.name, t.repo_name), ("lead", "lead", "dotclaude"))
        self.assertEqual(t.repo, os.path.join(lead, ".git"))
        t = tb.classify(os.path.join(self.root, "tab-bar"))
        self.assertEqual((t.kind, t.name, t.repo_name), ("lane", "tab-bar", "dotclaude"))
        self.assertEqual(t.repo, os.path.join(lead, ".git"))
        t = tb.classify(os.path.join(self.root, "agent-a5b6"))
        self.assertEqual((t.kind, t.name), ("other", "agent-a5b6"))

    def test_a_subdir_of_a_lane_is_the_lane(self):
        make_repo(self.root, "dotclaude", lanes=["tab-bar"])
        sub = os.path.join(self.root, "tab-bar", "tmux", "deep")
        os.makedirs(sub)
        self.assertEqual(tb.classify(sub).kind, "lane")

    def test_only_closed_lanes_is_not_laned(self):
        lead = make_repo(self.root, "karaoke")
        os.makedirs(os.path.join(lead, ".git", "lanes", "_closed"))
        with open(os.path.join(lead, ".git", "lanes", "_closed", "lane.json"), "w") as f:
            json.dump({"path": lead}, f)
        t = tb.classify(lead)
        self.assertEqual((t.kind, t.name, t.repo), ("shared", "karaoke:", ""))

    def test_a_repo_without_lanes_is_shared(self):
        lead = make_repo(self.root, "hq")
        self.assertEqual(tb.classify(lead), tb.Tab("shared", "", "hq", "hq:"))

    def test_bad_lane_records_leave_their_worktree_other(self):
        # The repo is still laned (a record exists), but no record names the worktree.
        records = {"a": json.dumps({"path": 42}).encode(), "b": b"{}",
                   "c": json.dumps({"path": os.path.join(self.root, "c") + " " * 70000}).encode(),
                   "d": b"[" * 30000 + b"]" * 30000,     # under the cap, too deep for json
                   "e": b"not json",
                   "f": json.dumps({"path": "relative/e"}).encode(),
                   "g": json.dumps(["path"]).encode()}
        make_repo(self.root, "repo", lanes=list(records), records=records)
        for lane in records:
            with self.subTest(lane=lane):
                self.assertEqual(tb.classify(os.path.join(self.root, lane)).kind, "other")

    def test_a_huge_record_is_not_read_past_its_cap(self):
        path = os.path.join(self.root, "big")
        with open(path, "wb") as f:
            f.write(b"x" * (tb.RECORD_MAX + 1))
        self.assertIsNone(tb.read_small(path, tb.RECORD_MAX))
        with open(path, "wb") as f:
            f.write(b"x" * tb.RECORD_MAX)
        self.assertEqual(len(tb.read_small(path, tb.RECORD_MAX)), tb.RECORD_MAX)

    def test_a_plain_dir_is_shared_by_its_name(self):
        d = os.path.join(self.root, "notes")
        os.makedirs(d)
        self.assertEqual(tb.classify(d), tb.Tab("shared", "", "notes", "notes:"))

    def test_no_cwd_is_shared_with_no_name(self):
        for cwd in ("", "relative", "/x\0y"):
            with self.subTest(cwd=cwd):
                self.assertEqual(tb.classify(cwd), tb.Tab("shared", "", "", ""))

    def test_an_unreadable_git_file_is_shared(self):
        if os.geteuid() == 0:
            self.skipTest("root reads a mode-000 file")
        make_repo(self.root, "repo", lanes=["l1"])
        dotgit = os.path.join(self.root, "l1", ".git")
        os.chmod(dotgit, 0)
        self.addCleanup(os.chmod, dotgit, 0o644)
        self.assertEqual(tb.classify(os.path.join(self.root, "l1")),
                         tb.Tab("shared", "", "l1", "l1:"))

    def test_a_git_fifo_does_not_hang(self):
        d = os.path.join(self.root, "odd")
        os.makedirs(d)
        os.mkfifo(os.path.join(d, ".git"))
        self.assertEqual(tb.classify(d).kind, "shared")

    def test_a_long_lane_id_is_cut_to_12_cells(self):
        make_repo(self.root, "dotclaude", lanes=["fix-pass-last-recursion"])
        t = tb.classify(os.path.join(self.root, "fix-pass-last-recursion"))
        self.assertEqual((t.kind, t.name), ("lane", "fix-pass-la…"))
        self.assertEqual(tb.text_width(t.name), 12)
        self.assertEqual(tb.clean("漢字漢字漢字漢字"), "漢字漢字漢…")   # wide cells count twice

    def test_hostile_names_are_cleaned(self):
        name = tb.clean(HOSTILE + "-long-tail")
        self.assertNotRegex(name, r"[#\x00-\x1f\x7f-\x9f]")
        self.assertEqual(tb.text_width(name), 12)


# --- lay out ------------------------------------------------------------------------------------

DOTCLAUDE = Group("dotclaude", tabs(4, 6, 7, 8))   # lead, 3 lanes
SHARED5 = tabs(1, 2, 3, 5, 9)


class LayOut(unittest.TestCase):
    def check_fits(self, lay, width):
        """Every row's gutter, slots, separators, dividers and +N fit its width; no slot is
        over the default width; a header fits the gutter."""
        for r, (row, slot) in enumerate(zip(lay.rows, lay.slots)):
            avail = width - lay.gutter - (lay.right if r == 0 else 0)
            fixed = sum(lay.head_w[i[1]] if i[0] == "div" else i[2]
                        for i in row if i[0] in ("div", "more"))
            if row[0][0] == "head":
                self.assertLessEqual(lay.head_w[row[0][1]], lay.head)
            self.assertLessEqual(fixed + len(tab_ids(row)) * slot + tb.separators(row), avail,
                                 (r, row))
            self.assertLessEqual(slot, tb.DEFAULT_SLOT)

    def test_one_laned_group_and_a_shared_row(self):
        lay = tb.lay_out([Group("dotclaude", tabs(2, 3))], tabs(1, 4), 188, "@1", 28, 16)
        self.assertEqual(lay.rows, [[("head", 0, False), ("tab", "@2", 2), ("tab", "@3", 3)],
                                    [("tab", "@1", 1), ("tab", "@4", 4)]])
        self.assertEqual(lay.slots, [32, 32])       # room for more: the default width
        self.assertEqual((lay.phone, lay.hidden, lay.heads), (False, 0, ["dotclaude"]))
        self.check_fits(lay, 188)

    def test_the_live_shape_on_the_desktop(self):
        # claude.conf: status-left-length 8, status-right-length 22. G = 8 + "dotclaude▸ " = 19.
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 8, 22)
        self.assertEqual([tab_ids(r) for r in lay.rows],
                         [["@4", "@6", "@7", "@8"], ["@1", "@2", "@3", "@5", "@9"]])
        self.assertEqual((lay.left, lay.head, lay.gutter), (8, 11, 19))
        self.assertEqual(lay.slots, [32, 32])       # a row of 4 at 188: 32 each, left-justified
        self.check_fits(lay, 188)

    def test_the_gutter_is_status_left_plus_the_widest_shown_header(self):
        groups = [Group("ab", tabs(1)), Group("longername", tabs(2))]
        lay = tb.lay_out(groups, tabs(3), 188, "@1", 8, 22)
        self.assertEqual((lay.head, lay.gutter), (12, 20))
        lay = tb.lay_out([], tabs(1, 2), 188, "@1", 8, 22)         # no laned row: H = 0
        self.assertEqual((lay.head, lay.gutter), (0, 8))
        lay = tb.lay_out(groups, tabs(3), 45, "@1", 8, 22)          # phone: PHONE_LEFT + "lon▸ "
        self.assertEqual((lay.left, lay.head, lay.gutter), (tb.PHONE_LEFT, 5, tb.PHONE_LEFT + 5))

    def test_a_row_too_full_for_the_default_width_splits_evenly(self):
        # 9 shared: row 0 (144 cells after status-left and -right) holds 7 at 18 + 6
        # separators, so 5+4; 5 tabs get (144 - 4) // 5 = 28, the row of 4 gets 32.
        lay = tb.lay_out([], tabs(*range(1, 10)), 188, "@1", 28, 16)
        self.assertEqual([len(tab_ids(r)) for r in lay.rows], [5, 4])
        self.assertEqual(lay.slots, [28, 32])
        self.check_fits(lay, 188)
        lay = tb.lay_out([], tabs(*range(1, 11)), 188, "@1", 0, 0)    # 10 in 188: 17 < 18
        self.assertEqual([len(tab_ids(r)) for r in lay.rows], [5, 5])
        self.assertEqual(lay.slots, [32, 32])

    def test_the_live_shape_on_the_phone_spreads_the_lanes_evenly(self):
        # G = PHONE_LEFT + "dot▸ " = 11, leaving 34 a row: 3 tabs at 9 + 2 separators, so 4
        # dotclaude tabs go 2+2 at 16, and the 5 shared 3+2.
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 45, "@4", 8, 22)
        self.assertTrue(lay.phone)
        self.assertEqual(lay.heads, ["dot"])
        self.assertEqual(lay.rows[1][0], ("head", 0, True))     # the overflow header, dimmed
        self.assertEqual([tab_ids(r) for r in lay.rows],
                         [["@4", "@6"], ["@7", "@8"], ["@1", "@2", "@3"], ["@5", "@9"]])
        self.assertEqual(lay.slots, [16, 16, 10, 16])
        self.assertEqual((lay.left, lay.right), (tb.PHONE_LEFT, 0))
        self.check_fits(lay, 45)

    def test_spread_matrix(self):
        cases = [(4, [3, 4], [2, 2]), (5, [3, 4], [3, 2]), (5, [2, 4], [2, 3]),
                 (7, [3, 4, 4], [3, 2, 2]), (9, [3, 4, 4], [3, 3, 3]), (1, [5], [1]),
                 (6, [1, 10], [1, 5]), (10, [10], [10]), (11, [10, 10], [6, 5])]
        for n, caps, want in cases:
            with self.subTest(n=n, caps=caps):
                got = tb.spread(n, caps)
                self.assertEqual(got, want)
                self.assertEqual(sum(got), n)
                self.assertTrue(all(g <= c for g, c in zip(got, caps)))

    def test_every_kind_spreads_over_its_rows(self):
        # 11 shared at a width that holds 10 a row: 6+5, not 10+1; the same for a group.
        lay = tb.lay_out([], tabs(*range(1, 12)), 180, "@1", 0, 0)
        self.assertEqual([len(tab_ids(r)) for r in lay.rows], [6, 5])
        lay = tb.lay_out([Group("big", tabs(*range(1, 12)))], [], 180, "@1", 0, 0)
        self.assertEqual([len(tab_ids(r)) for r in lay.rows], [6, 5])
        self.check_fits(lay, 180)

    def test_four_groups_pack_the_smallest_onto_the_shared_rows(self):
        groups = [Group("alpha", tabs(1, 2)), Group("bravo", tabs(3, 4, 5)),
                  Group("charlie", tabs(6, 7, 8)), Group("delta", tabs(9, 10, 11))]
        shared = tabs(*range(12, 26))      # 14 shared: two rows by themselves
        lay = tb.lay_out(groups, shared, 188, "@1", 28, 16)
        self.assertLessEqual(len(lay.rows), tb.MAX_ROWS)
        self.assertEqual(lay.hidden, 0)
        self.assertIn(("div", 0), [i for row in lay.rows for i in row])   # alpha, the smallest
        self.assertNotIn(("head", 0, False), [i for row in lay.rows for i in row])
        shown = sorted(w for row in lay.rows for w in tab_ids(row))
        self.assertEqual(shown, sorted(f"@{i}" for i in range(1, 26)))
        self.check_fits(lay, 188)

    def test_past_5_rows_ends_in_plus_n_and_keeps_the_current_window(self):
        groups = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 11))) for k in range(6)]
        for current in ("@1", "@60"):
            with self.subTest(current=current):
                lay = tb.lay_out(groups, [], 188, current, 28, 16)
                self.assertEqual(len(lay.rows), tb.MAX_ROWS)
                last = lay.rows[-1][-1]
                self.assertEqual(last[0], "more")
                self.assertGreater(lay.hidden, 0)
                self.assertEqual(last[1], lay.hidden)
                shown = [w for row in lay.rows for w in tab_ids(row)]
                self.assertEqual(len(shown) + lay.hidden, 60)
                self.assertIn(current, shown)
                self.assertEqual(len(set(shown)), len(shown))
                # Packing these saves no row, so none is packed: every row keeps its header.
                self.assertTrue(all(row[0][0] == "head" for row in lay.rows))
                self.check_fits(lay, 188)

    def test_the_current_window_moves_nothing_while_nothing_is_hidden(self):
        a = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 28, 16)
        b = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@9", 28, 16)
        self.assertEqual(a, b)
        self.assertEqual(tb.render(a), tb.render(b))

    def test_a_wide_row_has_no_tab_cap(self):
        # Rows go to tmux through source-file, which has no 16 KB command limit.
        lay = tb.lay_out([], tabs(*range(1, 16)), 400, "@1", 28, 16)
        self.assertEqual([len(tab_ids(r)) for r in lay.rows], [15])   # (400 - 44 + 1) // 19
        self.assertEqual(lay.slots, [22])                              # (356 - 14) // 15

    def test_every_rows_first_tab_starts_at_the_same_column(self):
        # Drawn cells per item: what the renderer pads each piece to. Every row's first tab
        # starts at G + 1, and with equal slots the separators line up across rows.
        for width, slots in ((188, [32, 32]), (45, None)):
            with self.subTest(width=width):
                lay = tb.lay_out([DOTCLAUDE], SHARED5, width, "@4", 8, 22)
                if slots:
                    self.assertEqual(lay.slots, slots)
                starts, seps = [], []
                for row, slot in zip(lay.rows, lay.slots):
                    col, row_seps = lay.gutter + 1, []
                    tab_cols = []
                    for k, item in enumerate(row):
                        if item[0] == "head":
                            continue                    # drawn in the gutter
                        if item[0] == "tab" and k and row[k - 1][0] == "tab":
                            row_seps.append(col)
                            col += 1
                        if item[0] == "tab":
                            tab_cols.append(col)
                            col += slot
                        elif item[0] == "div":
                            col += lay.head_w[item[1]]
                    starts.append(tab_cols[0])
                    seps.append(row_seps)
                self.assertEqual(set(starts), {lay.gutter + 1})
                if slots:
                    common = min(len(s) for s in seps)
                    self.assertEqual({tuple(s[:common]) for s in seps}, {tuple(seps[0][:common])})
        self.check_fits(lay, 400)

    def test_a_tiny_client_still_shows_one_tab_a_row(self):
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 12, "@4", 28, 16)
        self.assertTrue(all(len(tab_ids(r)) >= 1 for r in lay.rows))
        tb.render(lay)                     # widths clamp: nothing raises


# --- render -------------------------------------------------------------------------------------

class Render(unittest.TestCase):
    def test_a_dim_separator_between_two_tabs_and_nowhere_else(self):
        # Packed: alpha's divider follows a shared tab, so no separator before it or its tab.
        groups = [Group("alpha", tabs(1, 2)), Group("bravo", tabs(3, 4, 5)),
                  Group("charlie", tabs(6, 7, 8)), Group("delta", tabs(9, 10, 11))]
        lay = tb.lay_out(groups, tabs(*range(12, 26)), 188, "@1", 28, 16)
        for r, (items, row) in enumerate(zip(lay.rows, tb.render(lay))):
            with self.subTest(row=r):
                want = [tb.FILL, tb.NORM, tb.left_part(28) if r == 0 else " " * 28]
                if items[0][0] != "head":
                    want.append(" " * lay.head)          # the gutter's header column, blank
                for k, item in enumerate(items):
                    if item[0] == "tab" and k and items[k - 1][0] == "tab":
                        want.append(tb.SEP)
                    if item[0] == "head":
                        want.append(tb.header(item[1], lay.head_w[item[1]] - 2, item[2],
                                              lay.head))
                    elif item[0] == "div":
                        want.append(tb.divider(item[1], lay.head_w[item[1]] - 2))
                    elif item[0] == "tab":
                        want.append(tb.entry(item[1], item[2], lay.slots[r]))
                want += [tb.right_part(16)] if r == 0 else []
                self.assertEqual(row, "".join(want))
                self.assertEqual(row.count(tb.SEP), tb.separators(items))
        # Outside every range: each entry closes its range before the separator.
        self.assertTrue(tb.entry("@1", 1, 20).endswith("#[norange]" + tb.NORM + ",}}"))
        self.assertEqual(tb.SEP, "#[fg=colour240]│#[fg=colour250]")
        self.assertIn("┃", tb.divider(0, 5))      # a packed group's divider reads differently
        self.assertNotIn("│", tb.divider(0, 5))

    def test_the_gutter_draws_g_cells_on_every_row(self):
        # Count what each gutter piece draws: status-left pads to L, a header's name pads to its
        # own width, the rest is literal text. Styles draw nothing.
        for width in (188, 45):
            lay = tb.lay_out([DOTCLAUDE], SHARED5, width, "@4", 8, 22)
            for r, row in enumerate(tb.render(lay)):
                with self.subTest(width=width, row=r):
                    gutter = row[:row.index("#{W:")]
                    gutter = gutter.replace(tb.left_part(lay.left), "L" * lay.left)
                    name = lay.head_w[0] - 2
                    gutter = gutter.replace(tb.name_part(0, name), "n" * name)
                    drawn = re.sub(r"#\[[^]]*\]", "", gutter)
                    self.assertNotIn("#", drawn)
                    self.assertEqual(tb.text_width(drawn), lay.gutter)

    def test_rows_hold_only_template_text(self):
        for width in (188, 45):
            lay = tb.lay_out([DOTCLAUDE], SHARED5, width, "@4", 28, 16)
            for row in tb.render(lay):
                with self.subTest(width=width):
                    self.assertTrue(row.startswith("#[fill=colour236]"))
                    for bad in ("%", "#(", "#{E:", "'", "\n"):
                        self.assertNotIn(bad, row)
                    self.assertLessEqual(set(row), ALPHABET)
                    self.assertNotRegex(row, r"#\[[^]]*,")       # one style per #[ ]

    def test_a_title_loses_its_hashes_then_claudes_prefix(self):
        e = tb.entry("@7", 7, 30)
        strip = "s/^([^ ][^ ]?[^ ]? )?[^ ]+ · (.*)$/\\2/"
        self.assertIn("#{s/[#]/♯/;" + strip + ":pane_title}", e)
        self.assertIn("#{s/[#]/♯/:pane_current_command}", e)
        self.assertEqual(e.count("pane_title}"), e.count("[#]/♯/;" + strip + ":pane_title}"))
        for bad in ("{", "}", ",", ":", ";"):   # each would end the modifier or the #{...}
            self.assertNotIn(bad, strip)
        # The same pattern in Python's dialect ([ escaped in a set): what it keeps.
        py = re.compile(r"^([^ ][^ ]?[^ ]? )?[^ ]+ · (.*)$")
        for title, label in (("✳ repo · label", "label"), ("⠂ repo · label", "label"),
                             ("⣿ repo · label", "label"), ("repo · label", "label"),
                             ("no prefix here", "no prefix here"),
                             ("✳ a · b · x", "b · x"), ("long word · x y", "long word · x y"),
                             ("[repo] label", "[repo] label")):
            with self.subTest(title=title):
                self.assertEqual(py.sub(r"\2", title), label)

    def test_row_0_keeps_status_left_and_right(self):
        rows = tb.render(tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 28, 16))
        self.assertTrue(rows[0].startswith(tb.FILL + tb.NORM + "#{p28:#{T;=/28:status-left}}"))
        self.assertTrue(rows[0].endswith("#[align=right]#{T;=/16:status-right}"))
        self.assertNotIn("status-left", rows[1])
        phone = tb.render(tb.lay_out([DOTCLAUDE], SHARED5, 45, "@4", 28, 16))
        self.assertIn("#{p6:#{T;=/6:status-left}}", phone[0])
        self.assertNotIn("status-right", "".join(phone))

    def test_each_slot_is_one_w_loop_with_literal_widths(self):
        e = tb.entry("@7", 7, 30)
        self.assertTrue(e.startswith("#{W:#{?#{==:#{window_id},@7},"))
        self.assertEqual(e.count("#{W:"), 1)
        # base = 30 - len(" 7 ") = 27: star and glyph 23, one of them 25, neither 27.
        self.assertEqual(sorted(set(re.findall(r"#\{p(\d+):", e))), ["23", "25", "27"])
        self.assertEqual(sorted(set(re.findall(r"#\{=/(\d+)/…:", e))), ["22", "24", "26"])
        self.assertIn("#[bg=colour24]#[fg=colour231]#[bold]", e)
        self.assertIn("#[range=window|#{window_index}]", e)
        for bad in (("@7x", 7), ("7", 7), ("@7", -1), ("@7", "7")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tb.entry(bad[0], bad[1], 30)

    def test_plus_n_is_a_user_range(self):
        groups = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 11))) for k in range(6)]
        rows = tb.render(tb.lay_out(groups, [], 188, "@1", 28, 16))
        self.assertIn("#[range=user|more]", rows[-1])

    def test_hostile_names_render_the_same_rows_as_benign_ones(self):
        root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        out = {}
        for label, name in (("benign", BENIGN), ("hostile", HOSTILE + "-tail")):
            base = os.path.join(root, label)
            os.makedirs(base)
            lead = make_repo(base, name, lanes=[name + "-lane"])
            plain = os.path.join(base, name + "-dir")
            os.makedirs(plain)
            cwds = {"@1": lead, "@2": os.path.join(base, name + "-lane"), "@3": plain}
            tab_of = {wid: tb.classify(cwd) for wid, cwd in cwds.items()}
            self.assertEqual(tab_of["@2"].kind, "lane")
            groups, shared, names = tb.group_windows([(1, "@1"), (2, "@2"), (3, "@3")], tab_of)
            for v in names.values():
                self.assertNotRegex(v[0], r"[#\x00-\x1f\x7f-\x9f]")
            rows = {}
            for width in (188, 45):
                lay = tb.lay_out(groups, shared, width, "@1", 28, 16)
                rows[width] = tb.render(lay)
                for opt, value in tb.session_ops(lay, rows[width]):
                    if opt.startswith("@tab_bar_g"):
                        self.assertNotRegex(value, r"[#\x00-\x1f\x7f-\x9f]")
            out[label] = rows
        self.assertEqual(out["hostile"], out["benign"])
        for row in out["hostile"][188] + out["hostile"][45]:
            self.assertNotIn("%", row)
            self.assertNotIn("#(", row)
            self.assertLessEqual(set(row), ALPHABET)

    def test_session_ops_write_every_row_and_the_phone_overrides(self):
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 45, "@4", 28, 16)
        rows = tb.render(lay)
        ops = dict(tb.session_ops(lay, rows))
        for i in range(len(rows)):
            self.assertEqual(ops[f"status-format[{i}]"], rows[i])
        self.assertEqual(ops["status-position"], "bottom")
        self.assertEqual(ops["status-left"], "#(~/.local/bin/tmux-claude-status)")
        self.assertEqual(ops["status-right"], "")
        self.assertEqual(ops["@tab_bar_g0"], "dot")
        desk = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 28, 16)
        ops = dict(tb.session_ops(desk, tb.render(desk)))
        self.assertEqual([ops[k] for k in ("status-position", "status-left", "status-right")],
                         [None, None, None])


# --- the source-file write ----------------------------------------------------------------------

# A model of tmux 3.7c's config lexer (cmd-parse.y yylex_token) for the words tmux-tab-bar writes,
# strict where tmux would expand: in double quotes it allows only a ', and unquoted only plain
# words and the ; between commands. The fake tmux below runs `source-file -` through it.
TMUX_WORDS = r'''
def tmux_words(line):
    """One config line as tmux's lexer reads it: [[word, ...] per ;-separated command]."""
    cmds, words, buf, state, inword = [], [], [], None, False
    for ch in line:
        if state == "'":
            if ch == "'":
                state = None
            else:
                buf.append(ch)
        elif state == '"':
            if ch == '"':
                state = None
            elif ch in "$\\~\n":
                raise ValueError("tmux would expand %r in double quotes" % ch)
            else:
                buf.append(ch)
        elif ch in " \t":
            if inword:
                words.append("".join(buf))
                buf, inword = [], False
        elif ch == ";" and not inword:
            cmds.append(words)
            words = []
        elif ch in "'\"":
            state, inword = ch, True
        elif ch in "$\\~#{};%\n":
            raise ValueError("unquoted %r" % ch)
        else:
            buf.append(ch)
            inword = True
    if state:
        raise ValueError("an open quote")
    if inword:
        words.append("".join(buf))
    if words:
        cmds.append(words)
    return cmds
'''
exec(TMUX_WORDS)

ROUND_TRIP = ["'", '"', "\\", "$HOME", ";", "{}", "#(touch x)", "~", "a\\'b", "\\\\", "end\\",
              "%if 1", " lead", "-t", "", "#{E:x}", "✳▸ ★", "'\"'\"'", "a b\tc", "q'\"\\$H;{}"]


class Quote(unittest.TestCase):
    def test_every_word_reads_back_byte_for_byte(self):
        for s in ROUND_TRIP:
            with self.subTest(s=s):
                line = tb.command("set-option", "-w", "-t", "@1", "@tab_name", s)
                self.assertEqual(tmux_words(line), [["set-option", "-w", "-t", "@1",
                                                      "@tab_name", s]])

    def test_a_newline_never_goes_in(self):
        for s in ("a\nb", "a\rb", "a\0b"):
            with self.subTest(s=s), self.assertRaises(ValueError):
                tb.quote(s)

    def test_a_session_line_writes_rows_then_status_then_the_rest_and_the_sig_last(self):
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 45, "@4", 28, 16)
        rows = tb.render(lay)
        line = tb.write_line("$3", tb.session_ops(lay, rows), "3", "SIG")
        cmds = tmux_words(line)
        names = [c[3] if c[1] == "-t" else c[4] for c in cmds]
        self.assertEqual(names, ["@tab_bar_g0"] + [f"status-format[{i}]" for i in range(len(rows))]
                         + ["status", "status-position", "status-left", "status-right",
                            "@tab_bar_sig"])
        self.assertEqual([c[4] for c in cmds[1:1 + len(rows)]], rows)
        self.assertEqual(cmds[-1], ["set-option", "-t", "$3", "@tab_bar_sig", "SIG"])
        no_status = tmux_words(tb.write_line("$3", tb.session_ops(lay, rows), None, "SIG"))
        self.assertNotIn("status", [c[3] for c in no_status if c[1] == "-t"])


# --- claude.conf --------------------------------------------------------------------------------

HOOK = ("'run-shell -b \"[ -x $HOME/.local/bin/tmux-tab-bar ] && "
        "$HOME/.local/bin/tmux-tab-bar layout >/dev/null 2>&1; true\"'")


class Conf(unittest.TestCase):
    CLAUDE_ITEM = re.compile(r'^\s*"(#\{\?@claude_state|Shelf…|Replies before pass)')

    def items(self, start):
        with open(CONF) as f:
            text = f.read()
        block = text[text.index(start):]
        block = block[:block.index("\n\n")]
        return [line.strip().rstrip("\\").rstrip() for line in block.splitlines()
                if self.CLAUDE_ITEM.match(line)]

    def test_the_tap_menu_has_the_right_click_menus_claude_items(self):
        right = self.items("bind -n MouseDown3Status")
        tap = self.items("bind -n MouseUp1Status")
        self.assertEqual(len(right), 4)
        self.assertEqual(tap, right)

    def test_the_tap_menu_has_no_kill_or_respawn_and_no_stay_open(self):
        with open(CONF) as f:
            text = f.read()
        block = text[text.index("bind -n MouseUp1Status"):]
        block = block[:block.index("\n\n")]
        self.assertNotIn("kill-window", block)
        self.assertNotIn("respawn-window", block)
        self.assertNotRegex(block, r"display-menu[^\n]* -O")
        self.assertIn("unbind -n MouseDown1Status", text)

    def test_every_hook_is_silent_exits_0_and_uses_the_full_path(self):
        # A run-shell -b that prints or fails puts the active pane into view mode.
        with open(CONF) as f:
            text = f.read()
        hooks = ("client-attached", "client-detached", "client-resized", "window-linked",
                 "window-unlinked", "after-new-window", "session-window-changed",
                 "client-session-changed")
        for hook in hooks:
            with self.subTest(hook=hook):
                self.assertIn(f"set-hook -g {hook}[43] {HOOK}\n", text)
        self.assertEqual(text.count("tmux-tab-bar layout"), len(hooks))

    def test_the_hook_command_exits_0_and_says_nothing_whatever_the_script_does(self):
        cmd = HOOK.split('"')[1].replace("$HOME", "$H")
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home)
        script = os.path.join(home, ".local", "bin", "tmux-tab-bar")
        os.makedirs(os.path.dirname(script))
        for body, mode in ((None, None), ("#!/bin/sh\necho out; echo err >&2; exit 3\n", 0o755),
                           ("#!/bin/sh\nexit 0\n", 0o644)):
            with self.subTest(body=body, mode=mode):
                if body is not None:
                    with open(script, "w") as f:
                        f.write(body)
                    os.chmod(script, mode)
                p = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True,
                                   timeout=10, env={"H": home, "PATH": "/usr/bin:/bin"})
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))


# --- layout against a fake tmux ------------------------------------------------------------------

FAKE_TMUX = TMUX_WORDS + r'''
import json, os, re, sys
if sys.argv[1:2] != ["-u"]:
    sys.exit(3)                         # without -u, tmux would print tabs and non-ASCII as _
args = sys.argv[2:]
log = os.environ["STUB_LOG"]
def record(argv):
    with open(log, "a") as f:
        f.write(json.dumps(argv) + "\n")
record(args)
path = os.environ["STUB_STATE"]
with open(path) as f:
    st = json.load(f)
if os.environ.get("STUB_FAIL") == args[0]:
    sys.exit(1)
lists = {"list-sessions": "sessions", "list-clients": "clients", "list-windows": "windows",
         "list-panes": "panes"}
if args[0] in lists:
    fmt = args[args.index("-F") + 1]
    for rec in st[lists[args[0]]]:
        print(re.sub(r"#\{([^}]*)\}", lambda m: str(rec.get(m.group(1), "")), fmt))
    sys.exit(0)

def set_option(argv):
    rest, unset, window, target = argv[1:], False, False, None
    while rest and rest[0].startswith("-") and len(rest) > 1 and rest[0] in ("-t", "-u", "-w"):
        flag = rest.pop(0)
        if flag == "-t":
            target = rest.pop(0)
        unset |= flag == "-u"
        window |= flag == "-w"
    key, recs = ("window_id", st["windows"]) if window else ("session_id", st["sessions"])
    recs = [r for r in recs if r[key] == target]
    if argv[0] != "set-option" or not recs or len(rest) != (1 if unset else 2):
        return False
    for r in recs:
        if unset:
            r.pop(rest[0], None)
        else:
            r[rest[0]] = rest[1]
    record(argv)
    return True

if args != ["source-file", "-"]:
    sys.exit(1)
ok = True
for line in sys.stdin.read().splitlines():
    try:
        cmds = tmux_words(line)
    except ValueError:
        sys.exit(2)                     # a parse error: tmux runs none of the file
    for argv in cmds:                   # an error drops the rest of its line, as in tmux
        if not set_option(argv):
            ok = False
            break
with open(path, "w") as f:
    json.dump(st, f)
sys.exit(0 if ok else 1)
'''


class FakeTmux(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(f"#!{sys.executable} -I\n" + FAKE_TMUX)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.state = os.path.join(self.tmp, "state.json")
        self.run_dir = os.path.join(self.tmp, "run")
        os.mkdir(self.run_dir)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("TMUX", "CLAUDE"))}
        self.env.update(PATH=stubs + os.pathsep + "/usr/bin:/bin", STUB_LOG=self.log,
                        STUB_STATE=self.state, TMUX="/fake/sock,1,0",
                        TMUX_CLAUDE_STATUS_DIR=self.run_dir)
        self.base = os.path.join(self.run_dir,
                                 f".tmux-tab-bar.{os.getuid()}.{tb.server_key('/fake/sock,1,0')}")
        repos = os.path.join(self.tmp, "code")
        os.makedirs(repos)
        lead = make_repo(repos, "dotclaude", lanes=["tab-bar", "lane-close"])
        hq = os.path.join(repos, "hq")
        os.makedirs(hq)
        cwds = {"@1": hq, "@2": lead, "@3": os.path.join(repos, "tab-bar"),
                "@4": os.path.join(repos, "lane-close")}
        self.write_state({
            "sessions": [{"session_id": "$0", "status": "on", "status-left-length": "28",
                          "status-right-length": "16"}],
            "clients": [{"session_id": "$0", "client_width": "188"}],
            "windows": [{"session_id": "$0", "window_id": w, "window_index": w[1:],
                         "window_active": "1" if w == "@2" else "0", "@claude_state": "idle"}
                        for w in cwds],
            "panes": [{"window_id": w, "pane_active": "1", "pane_current_path": p,
                       "pane_title": "✳ [x] title", "@claude_star": ""}
                      for w, p in cwds.items()],
        })

    def write_state(self, st):
        with open(self.state, "w") as f:
            json.dump(st, f)

    def read_state(self):
        with open(self.state) as f:
            return json.load(f)

    def run_layout(self, **env):
        if os.path.exists(self.log):
            os.remove(self.log)
        p = subprocess.run([sys.executable, "-I", SCRIPT, "layout"], capture_output=True,
                           text=True, timeout=30, env={**self.env, **env})
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        return p

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def writes(self):
        return [c for c in self.calls() if c[0] == "set-option"]

    def session(self):
        return self.read_state()["sessions"][0]

    def rows(self):
        s = self.session()
        return [s[k] for k in sorted(k for k in s if k.startswith("status-format"))]

    def test_a_first_run_writes_every_row_then_the_count_and_a_rerun_writes_nothing(self):
        self.run_layout()
        self.assertEqual(sum(c[0] == "source-file" for c in self.calls()), 1)   # one write
        s = self.session()
        self.assertEqual(s["status"], "2")
        self.assertTrue(s["status-format[0]"] and s["status-format[1]"])
        self.assertIn("@tab_bar_sig", s)
        self.assertEqual(s["@tab_bar_g0"], "dotclaude")
        names = {w["window_id"]: (w["@tab_name"], w.get("@tab_group", ""))
                 for w in self.read_state()["windows"]}
        self.assertEqual(names, {"@1": ("hq:", ""), "@2": ("lead", "0"),
                                 "@3": ("tab-bar", "0"), "@4": ("lane-close", "0")})
        writes = self.writes()
        order = [c[-1] if c[1] == "-u" else c[-2] for c in writes]
        self.assertEqual(order.index("@tab_name"), 0)          # window options come first
        self.assertLess(order.index("status-format[1]"), order.index("status"))
        self.assertLess(order.index("status"), order.index("status-position"))
        self.assertEqual(order[-1], "@tab_bar_sig")
        self.run_layout()
        self.assertEqual(self.writes(), [])
        self.assertNotIn("source-file", [c[0] for c in self.calls()])

    def test_title_and_state_churn_changes_no_row_and_writes_nothing(self):
        self.run_layout()
        for call in self.calls():
            if call[0].startswith("list-"):
                fmt = call[call.index("-F") + 1]
                for word in ("pane_title", "@claude_state", "@claude_star"):
                    self.assertNotIn(word, fmt)
        rows = self.rows()
        st = self.read_state()
        for p in st["panes"]:
            p["pane_title"] = "⠂ [x] a brand new and much longer title #[fg=red]"
            p["@claude_star"] = "1"
        for w in st["windows"]:
            w["@claude_state"] = "busy"
        self.write_state(st)
        self.run_layout()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.rows(), rows)

    def test_the_narrowest_client_picks_the_phone_layout_then_the_desktop_comes_back(self):
        st = self.read_state()
        st["clients"].append({"session_id": "$0", "client_width": "45"})
        self.write_state(st)
        self.run_layout()
        s = self.session()
        self.assertEqual((s["status-position"], s["status-right"]), ("bottom", ""))
        self.assertEqual(s["status-left"], "#(~/.local/bin/tmux-claude-status)")
        self.assertEqual(s["@tab_bar_g0"], "dot")
        st = self.read_state()
        st["clients"] = st["clients"][:1]
        self.write_state(st)
        self.run_layout()
        s = self.session()
        for opt in ("status-position", "status-left", "status-right"):
            self.assertNotIn(opt, s)
            self.assertIn(["set-option", "-u", "-t", "$0", opt], self.writes())

    def test_a_session_with_no_client_is_left_alone(self):
        st = self.read_state()
        st["clients"] = []
        self.write_state(st)
        self.run_layout()
        self.assertEqual(self.writes(), [])

    def test_a_bar_turned_off_stays_off_and_comes_back_laid_out_when_turned_on(self):
        st = self.read_state()
        st["sessions"][0]["status"] = "off"
        self.write_state(st)
        self.run_layout()
        self.assertEqual(self.session()["status"], "off")
        self.assertIn("status-format[1]", self.session())
        self.run_layout()
        self.assertEqual(self.writes(), [])        # off and unchanged: nothing to write
        st = self.read_state()
        st["sessions"][0]["status"] = "on"          # turned back on: one row of the default
        self.write_state(st)
        self.run_layout()
        self.assertEqual(self.session()["status"], "2")
        self.run_layout()
        self.assertEqual(self.writes(), [])

    def test_a_count_changed_behind_its_back_is_put_right(self):
        self.run_layout()
        st = self.read_state()
        st["sessions"][0]["status"] = "4"
        self.write_state(st)
        self.run_layout()
        self.assertEqual(self.session()["status"], "2")
        self.run_layout()
        self.assertEqual(self.writes(), [])

    def test_a_vanished_window_does_not_stop_the_session_line(self):
        st = self.read_state()
        st["panes"].append({"window_id": "@9", "pane_active": "1",
                            "pane_current_path": self.tmp})
        st["windows"].append({"session_id": "$0", "window_id": "@9", "window_index": "9",
                              "window_active": "0"})
        self.write_state(st)
        # @9 is listed but gone by the write: its option line fails, the session line runs.
        stub = os.path.join(self.tmp, "bin", "tmux")
        with open(stub) as f:
            text = f.read()
        with open(stub, "w") as f:
            f.write(text.replace('if args != ["source-file", "-"]:',
                                 'st["windows"] = [w for w in st["windows"] '
                                 'if w["window_id"] != "@9"]\n'
                                 'if args != ["source-file", "-"]:'))
        self.run_layout()
        self.assertIn("@tab_bar_sig", self.session())
        with open(self.base + ".err") as f:
            self.assertIn("source-file", f.read())

    def test_a_newline_in_a_path_cannot_forge_another_panes_line(self):
        # A directory named "x\n@1\t1\t<the lead>" would read, line by line, as a second pane
        # line giving @1 (hq) the lead's directory.
        st = self.read_state()
        lead = st["panes"][1]["pane_current_path"]
        forged = os.path.join(self.tmp, "x\n@1\t1\t" + lead)
        st["panes"].append({"window_id": "@5", "pane_active": "1", "pane_current_path": forged})
        st["windows"].append({"session_id": "$0", "window_id": "@5", "window_index": "5",
                              "window_active": "0"})
        self.write_state(st)
        self.run_layout()
        names = {w["window_id"]: w.get("@tab_name") for w in self.read_state()["windows"]}
        self.assertEqual(names["@1"], "hq:")
        self.assertNotEqual(names["@5"], "lead")

    def test_outside_tmux_nothing_runs(self):
        env = {k: v for k, v in self.env.items() if k != "TMUX"}
        p = subprocess.run([sys.executable, "-I", SCRIPT, "layout"], capture_output=True,
                           text=True, timeout=30, env=env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(self.calls(), [])

    def test_a_failing_tmux_is_fail_open_and_silent(self):
        self.run_layout(STUB_FAIL="list-windows")
        self.assertEqual(self.writes(), [])
        with open(self.base + ".err") as f:
            self.assertIn("list-windows", f.read())
        self.assertEqual(os.stat(self.base + ".err").st_mode & 0o777, 0o600)

    def test_an_unwritable_run_dir_still_lays_out_silently(self):
        self.run_layout(TMUX_CLAUDE_STATUS_DIR="/nonexistent/dir")
        self.assertIn("@tab_bar_sig", self.session())

    def test_a_held_lock_marks_the_state_dirty_and_leaves(self):
        fd = os.open(self.base + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.run_layout()
        self.assertEqual(self.calls(), [])
        self.assertTrue(os.path.exists(self.base + ".dirty"))

    def test_the_lock_is_per_tmux_server(self):
        fd = os.open(self.base + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.run_layout(TMUX="/other/sock,1,0")   # another server: not blocked by this lock
        self.assertIn("list-sessions", [c[0] for c in self.calls()])

    def test_bad_usage_exits_2_silently(self):
        p = subprocess.run([sys.executable, "-I", SCRIPT], capture_output=True, text=True,
                           timeout=30, env=self.env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", ""))


class Lock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.base = os.path.join(self.tmp, "b")

    def test_a_mark_while_running_runs_again(self):
        calls = []

        def run():
            calls.append(1)
            if len(calls) < 3:
                tb.touch(self.base + ".dirty")     # another hook fired meanwhile

        tb.run_locked(self.base, run)
        self.assertEqual(len(calls), 3)
        self.assertFalse(os.path.exists(self.base + ".dirty"))

    def test_the_passes_are_bounded(self):
        calls = []

        def run():
            calls.append(1)
            tb.touch(self.base + ".dirty")

        tb.run_locked(self.base, run)
        self.assertEqual(len(calls), 2 * tb.PASSES)   # the passes, then the one retry's

    def test_a_run_marks_dirty_before_it_tries_the_lock(self):
        # Otherwise a holder letting go between this run's failed flock and its mark would
        # check, find nothing and leave, and this run's change would wait for the next event.
        calls = []

        def flock(fd, op):
            self.assertTrue(os.path.exists(self.base + ".dirty"))
            raise BlockingIOError

        with unittest.mock.patch.object(tb.fcntl, "flock", flock):
            tb.run_locked(self.base, lambda: calls.append(1))
        self.assertEqual(calls, [])
        self.assertTrue(os.path.exists(self.base + ".dirty"))

    def test_one_pass_when_nothing_marks(self):
        calls = []
        tb.run_locked(self.base, lambda: calls.append(1))
        self.assertEqual(len(calls), 1)

    def test_the_error_log_never_follows_a_link_and_is_capped(self):
        target = os.path.join(self.tmp, "target")
        with open(target, "w") as f:
            f.write("keep")
        os.symlink(target, self.base + ".err")
        tb.log_error(self.base + ".err", "boom")
        with open(target) as f:
            self.assertEqual(f.read(), "keep")
        os.remove(self.base + ".err")
        tb.log_error(self.base + ".err", "x" * (tb.ERR_MAX * 2))
        self.assertEqual(os.path.getsize(self.base + ".err"), tb.ERR_MAX)


# --- against a real tmux -------------------------------------------------------------------------

class RealTmux(unittest.TestCase):
    """A private tmux server "in" (-S, -f /dev/null, mouse on, tmux/claude.conf sourced) holding
    session t: window 0 in a laned repo's lead, 1 in its lane, 2 in a plain dir. Its client runs
    inside a second private server "out" (188x46, no status bar of its own), so capture-pane on
    the out pane shows what the client draws, and send-keys -l on it sends the client SGR mouse
    events. HOME is a temp dir without tmux-tab-bar, so the conf's hooks find no script: each must
    still exit 0 silently (test_no_hook_puts_a_pane_in_view_mode). The tests lay out by running
    the script themselves."""

    def setUp(self):
        self.tmux_bin = shutil.which("tmux")
        if not self.tmux_bin:
            self.skipTest("tmux not installed")
        try:                    # a short path: a socket path has a 108-byte limit
            self.tmp = os.path.realpath(tempfile.mkdtemp(dir="/tmp"))
        except OSError:         # the sandbox's /tmp is read-only; tmux skips below anyway
            self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock, self.out_sock = os.path.join(self.tmp, "in"), os.path.join(self.tmp, "out")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("TMUX", "CLAUDE"))}
        self.env.update(HOME=self.home, TERM="xterm-256color", TMUX_CLAUDE_STATUS_DIR=self.tmp,
                        LANG="C.UTF-8")
        repos = os.path.join(self.tmp, "code")
        os.makedirs(repos)
        self.lead = make_repo(repos, "dotclaude", lanes=["tab-bar"])
        self.plain = os.path.join(repos, "hq")
        os.makedirs(self.plain)
        p = self.ti("-f", "/dev/null", "new-session", "-d", "-s", "t", "-x", "188", "-y", "46",
                    "-c", self.lead, "sleep 600", check=False)
        if "Operation not permitted" in p.stderr:
            self.skipTest("the Bash sandbox blocks tmux's socket; run outside it")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.addCleanup(self.ti, "kill-server", check=False)
        self.ti("set", "-g", "mouse", "on")
        self.ti("source-file", CONF)
        self.ti("new-window", "-d", "-t", "t:1", "-c", os.path.join(repos, "tab-bar"),
                "sleep 600")
        self.ti("new-window", "-d", "-t", "t:2", "-c", self.plain, "sleep 600")
        self.ti("rename-window", "-t", "t:2", "hqwin")
        for i, title in enumerate(("alpha-title", "beta-title", "gamma-title")):
            self.ti("select-pane", "-t", f"t:{i}", "-T", title)
        p = self.to("-f", "/dev/null", "new-session", "-d", "-s", "o", "-x", "188", "-y", "46",
                    f"env -u TMUX {self.tmux_bin} -u -S {self.sock} attach -t t", check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.addCleanup(self.to, "kill-server", check=False)
        self.to("set", "-g", "status", "off")
        self.wait(lambda: self.ti("list-clients", "-F", "#{client_width}x#{client_height}")
                  .stdout.strip() == "188x46", "the client never attached at 188x46")
        pid = self.ti("display", "-p", "#{pid}").stdout.strip()
        self.layout_env = {**self.env, "TMUX": f"{self.sock},{pid},0",
                           "PATH": os.path.dirname(self.tmux_bin) + os.pathsep
                           + os.environ.get("PATH", "/usr/bin:/bin")}

    # --- helpers ---

    def tmux(self, sock, args, check=True, stdin=None):
        # -u: a client without a UTF-8 locale prints non-ASCII and tabs as _ (utf8_sanitize).
        p = subprocess.run([self.tmux_bin, "-u", "-S", sock, *args], capture_output=True,
                           text=True, encoding="utf-8", timeout=10, env=self.env, input=stdin)
        if check:
            self.assertEqual(p.returncode, 0, (args, p.stderr))
        return p

    def ti(self, *args, check=True, stdin=None):
        return self.tmux(self.sock, args, check, stdin)

    def to(self, *args, check=True):
        return self.tmux(self.out_sock, args, check)

    def wait(self, pred, why, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred():
                return
            time.sleep(0.05)
        self.fail(why)

    def screen(self):
        """What the inner client draws: the out pane's text, one line per row."""
        return self.to("capture-pane", "-p", "-t", "o").stdout.split("\n")

    def find(self, text, timeout=5.0):
        """(x, y) of text on the client's screen, 1-based cells, once it is drawn."""
        found = []

        def look():
            for y, line in enumerate(self.screen()):
                if text in line:
                    found.append((line.index(text) + 1, y + 1))
                    return True
            return False

        self.wait(look, f"{text!r} never drawn: {self.screen()[:6]}", timeout)
        return found[0]

    def click(self, x, y, button=0, release=True):
        self.to("send-keys", "-t", "o", "-l", f"\x1b[<{button};{x};{y}M")
        if release:
            self.to("send-keys", "-t", "o", "-l", f"\x1b[<{button};{x};{y}m")

    def run_layout(self):
        p = subprocess.run([sys.executable, "-I", SCRIPT, "layout"], capture_output=True,
                           text=True, timeout=30, env=self.layout_env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        errs = [n for n in os.listdir(self.tmp) if n.endswith(".err")]
        self.assertEqual(errs, [], [open(os.path.join(self.tmp, n)).read() for n in errs])

    def show(self, *args):
        return self.ti("show-options", *args).stdout

    def current(self):
        return self.ti("display", "-p", "-t", "t", "#{window_index}").stdout.strip()

    # --- tests ---

    def test_every_row_is_written_and_a_rerun_changes_nothing(self):
        self.run_layout()
        self.assertEqual(self.show("-v", "-t", "t", "status").strip(), "2")
        for i in range(2):
            row = self.show("-v", "-t", "t", f"status-format[{i}]")
            self.assertTrue(row.startswith("#[fill=colour236]"), (i, row[:80]))
        names = self.ti("list-windows", "-t", "t", "-F", "#{window_index} #{@tab_name}").stdout
        self.assertEqual(sorted(names.split("\n")[:-1]), ["0 lead", "1 tab-bar", "2 hq:"])
        before = (self.show("-t", "t"), self.show("-w", "-t", "t:0"), self.show("-w", "-t", "t:2"))
        self.run_layout()
        after = (self.show("-t", "t"), self.show("-w", "-t", "t:0"), self.show("-w", "-t", "t:2"))
        self.assertEqual(after, before)
        self.find("dotclaude▸")
        self.find("hq: gamma-title")

    def test_every_rows_first_tab_starts_at_the_same_column(self):
        # Row 1: the token, then `dotclaude▸ `; row 2 (shared): the same gutter, blank.
        self.run_layout()
        x0, y0 = self.find("0 lead")
        x2, y2 = self.find("2 hq:")
        self.assertEqual((y0, y2), (1, 2))
        self.assertEqual(x0, x2)

    def test_hostile_words_go_through_source_file_byte_for_byte(self):
        words = ROUND_TRIP
        script = "\n".join(tb.command("set-option", "-w", "-t", "t:0", f"@x{i}", w)
                           for i, w in enumerate(words)) + "\n"
        self.ti("source-file", "-", stdin=script)
        for i, w in enumerate(words):
            with self.subTest(w=w):
                got = self.ti("show-options", "-wv", "-t", "t:0", f"@x{i}").stdout
                self.assertEqual(got, w + "\n")
        # And end to end: a directory named with them becomes a tab name.
        odd = os.path.join(self.tmp, "q'\"\\$H;{}")
        os.makedirs(odd)
        self.ti("new-window", "-d", "-t", "t:3", "-c", odd, "sleep 600")
        self.run_layout()
        got = self.ti("show-options", "-wv", "-t", "t:3", "@tab_name").stdout
        self.assertEqual(got, "q'\"\\$H;{}:\n")

    def test_a_name_holding_a_job_is_drawn_as_text_and_runs_nothing(self):
        self.run_layout()
        pwned = os.path.join(self.tmp, "pwned")
        self.ti("set-option", "-w", "-t", "t:2", "@tab_name", f"#(touch {pwned})")
        self.ti("refresh-client", "-S", "-t", self.ti("list-clients", "-F", "#{client_name}")
                .stdout.strip())
        self.find("#(touch /")
        time.sleep(2.5)                   # a status-interval: the row is drawn again
        self.assertFalse(os.path.exists(pwned))

    def test_claudes_title_prefix_is_stripped_idle_busy_or_bare(self):
        self.ti("new-window", "-d", "-t", "t:3", "-c", self.plain, "sleep 600")
        self.run_layout()
        titles = ("✳ dotclaude · alpha label", "⠂ tab-bar · beta label", "hq · gamma label",
                  "no prefix here")
        for i, title in enumerate(titles):
            self.ti("select-pane", "-t", f"t:{i}", "-T", title)
        for text in ("lead alpha label", "tab-bar beta label", "hq: gamma label",
                     "hq: no prefix here"):
            self.find(text)
        bar = "\n".join(self.screen()[:2])
        for gone in ("✳", "⠂", "dotclaude ·", "tab-bar ·", "hq ·"):
            self.assertNotIn(gone, bar)

    def test_a_hash_or_a_style_in_a_title_draws_as_text_and_keeps_the_width(self):
        self.run_layout()
        self.ti("select-pane", "-t", "t:0", "-T", "PR 93 x")
        self.find("lead PR 93 x")
        x0, y0 = self.find("tab-bar beta-title")
        self.ti("select-pane", "-t", "t:0", "-T", "PR #93x")          # as many characters
        self.find("lead PR ♯93x")
        self.assertEqual(self.find("tab-bar beta-title"), (x0, y0))    # the next tab stays put
        self.ti("select-pane", "-t", "t:2", "-T", "#[range=window|1]x")
        self.assertEqual(self.ti("display", "-p", "-t", "t:2", "#{pane_title}").stdout,
                         "#[range=window|1]x\n")
        self.find("hq: ♯[range=window|1]x")    # a # left in would make it a range: "hq: x"

    def test_a_click_on_row_2_switches(self):
        self.run_layout()
        self.assertEqual(self.current(), "0")
        x, y = self.find("gamma-title")
        self.assertEqual(y, 2)
        self.click(x, y)
        self.wait(lambda: self.current() == "2", "the click on row 2 did not switch")

    def test_a_click_on_a_separator_acts_on_the_tab_to_its_left(self):
        # tmux 3.7c ends a range at cx + 1 (format-draw.c:949), so the left tab's range
        # also claims the divider; the cell after the divider is the right tab's.
        self.run_layout()
        x, y = self.find("│")
        self.assertEqual(y, 1)                  # between the lead and the lane on row 1
        self.click(x, y)                        # the lead, the current tab: its menu
        self.find("Replies before pass")
        self.assertEqual(self.current(), "0")
        self.click(1, 40)                       # a tap in the pane closes the menu
        self.wait(lambda: not any("Replies before pass" in line for line in self.screen()),
                  "the menu did not close")
        self.click(x + 1, y)                    # the lane: a switch
        self.wait(lambda: self.current() != "0", "the click right of the divider did not switch")

    def test_a_tap_on_the_current_tab_opens_its_menu_and_a_tap_on_an_item_runs_it(self):
        self.run_layout()
        x, y = self.find("alpha-title")
        self.click(x, y)
        self.find("Replies before pass")
        self.assertEqual(self.current(), "0")
        wx, wy = self.find("Windows…")
        self.click(wx + 1, wy)
        self.wait(lambda: self.ti("display", "-p", "-t", "t:0", "#{pane_mode}").stdout.strip()
                  == "tree-mode", "the Windows… item did not open the window list")

    def test_a_right_click_opens_the_full_menu_for_the_clicked_tab(self):
        self.run_layout()
        x, y = self.find("gamma-title")
        self.click(x, y, button=2, release=False)   # a release outside would close it
        self.find("2:hqwin")
        self.find("Swap Left")

    def test_no_hook_puts_a_pane_in_view_mode(self):
        # HOME has no tmux-tab-bar: every hook's command must still exit 0 and print nothing.
        self.ti("new-window", "-t", "t", "-c", self.plain, "sleep 600")
        self.ti("select-window", "-t", "t:0")
        deadline = time.time() + 2
        while time.time() < deadline:
            modes = self.ti("list-panes", "-a", "-F", "#{pane_in_mode}").stdout.split()
            self.assertEqual(set(modes), {"0"})
            time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
