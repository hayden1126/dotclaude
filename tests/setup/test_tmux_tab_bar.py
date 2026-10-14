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
import threading
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


# --- a model of tmux's format expansion: what a row draws ----------------------------------------
# Enough of tmux 3.7c's format language for the rows tmux-tab-bar writes: #{?c,a,b}, #{==:a,b},
# #{W:a,b} (env["windows"], with env["current"] drawn by b), variables, #I, and the modifiers
# =N, =/N/marker and pN (s/// is taken as identity: the tests' titles have no prefix to strip).
# Styles (#[...]) draw nothing. It measures cells, so a test can check the columns a row draws
# instead of the ones the layout claims.

def _close(s, i):
    """The index of the } closing the #{ at s[i]."""
    depth, j = 0, i
    while j < len(s):
        if s.startswith("#{", j):
            depth, j = depth + 1, j + 2
            continue
        if s[j] == "#" and s[j + 1:j + 2] in (",", "#", "}", ":"):
            j += 2                      # an escape (format_skip): `#}` doesn't close
            continue
        if s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError(f"an unclosed #{{ at {i}")


def _split(s, n):
    """s split at its n - 1 top-level commas (outside any #{...})."""
    parts, depth, start, j = [], 0, 0, 0
    while j < len(s):
        if s.startswith("#{", j):
            depth, j = depth + 1, j + 2
            continue
        if s[j] == "#" and s[j + 1:j + 2] in (",", "#", "}", ":"):
            j += 2
            continue
        if s[j] == "}":
            depth -= 1
        elif s[j] == "," and depth == 0:
            parts.append(s[start:j])
            start = j + 1
        j += 1
    parts.append(s[start:])
    if len(parts) != n:
        raise ValueError(f"{len(parts)} parts, not {n}: {s[:60]!r}")
    return parts


def _cut(text, cells):
    out, used = [], 0
    for c in text:
        if used + tb.cell_width(c) > cells:
            break
        out.append(c)
        used += tb.cell_width(c)
    return "".join(out)


def _directive(body, env):
    if body.startswith("?"):
        cond, a, b = _split(body[1:], 3)
        value = draw(cond, env) if cond.startswith("#{") else str(env.get(cond, ""))
        return draw(a if value not in ("", "0") else b, env)
    if body.startswith("==:"):
        x, y = _split(body[3:], 2)
        return "1" if draw(x, env) == draw(y, env) else "0"
    if body.startswith("W:"):
        a, b = _split(body[2:], 2)
        return "".join(draw(b if w["window_id"] == env["current"] else a, {**env, **w})
                       for w in env["windows"])
    if ":" not in body.split("#{", 1)[0]:
        return str(env.get(body, ""))
    mods, value = body.split(":", 1)
    text = draw(value, env) if value.startswith("#{") else str(env.get(value, ""))
    for mod in mods.split(";"):         # in tmux's order: substitutions, the cut, the pad
        if mod.startswith("="):
            n, _, marker = mod[1:].lstrip("/").partition("/")
            if tb.text_width(text) > int(n):
                text = _cut(text, int(n)) + marker
        elif mod.startswith("p"):
            text += " " * max(0, int(mod[1:]) - tb.text_width(text))
    return text


def draw(fmt, env, starts=None):
    """The text tmux draws for fmt. With `starts`, each top-level W loop that draws anything
    appends the 0-based cell it starts at."""
    out, i = [], 0
    while i < len(fmt):
        if fmt.startswith("#[", i):
            i = fmt.index("]", i) + 1
        elif fmt.startswith("#{", i):
            j = _close(fmt, i)
            text = _directive(fmt[i + 2:j], env)
            if starts is not None and fmt.startswith("#{W:", i) and text:
                starts.append(tb.text_width("".join(out)))
            out.append(text)
            i = j + 1
        elif fmt.startswith("#I", i):
            out.append(str(env["window_index"]))
            i += 2
        else:
            out.append(fmt[i])
            i += 1
    return "".join(out)


def window(wid, index, star="1", state="busy", title="a title longer than any slot gets"):
    return {"window_id": wid, "window_index": index, "@tab_name": "tab-bar",
            "pane_title": title, "@claude_star": star, "@claude_state": state}


def bar_env(lay, current=None):
    """Every shown tab as a window with a star, a glyph and a long title (the widest case)."""
    wins = [window(i[1], i[2]) for row in lay.rows for i in row if i[0] == "tab"]
    env = {"windows": wins, "current": current or wins[0]["window_id"],
           "status-left": " " + "x" * 40, "status-right": " " + "y" * 40}
    env.update({f"@tab_bar_g{g}": h for g, h in enumerate(lay.heads)})
    return env


def cells(text, ch):
    """The 0-based cells where ch is drawn in text."""
    out, col = [], 0
    for c in text:
        if c == ch:
            out.append(col)
        col += tb.cell_width(c)
    return out


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
            fixed = sum(tb.marker_w(lay.head_w, i) if i[0] == "div" else i[2]
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

    def test_a_hidden_current_window_sits_under_its_own_header(self):
        # 6 groups of 10 at 188: each takes 2 rows, so rows 0-4 show g0, g1 and g2's first
        # row; g2's second row, g3-g5 and the shared tabs (61-65) are hidden.
        groups = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 11))) for k in range(6)]
        shared = tabs(*range(61, 66))
        cases = [("@28", 2, False),     # g2 has a shown row: it takes a g2 slot there
                 ("@40", 3, True),      # g3 has none: the last slot, behind g3's divider
                 ("@60", 5, True),
                 ("@63", None, True),   # shared: behind a lone divider, never under g2
                 ("@1", 0, False)]      # shown already: nothing moves
        for current, group, divided in cases:
            with self.subTest(current=current):
                lay = tb.lay_out(groups, shared, 188, current, 28, 16)
                self.assertEqual(len(lay.rows), tb.MAX_ROWS)
                (r, k), = [(r, k) for r, row in enumerate(lay.rows)
                           for k, item in enumerate(row) if item[:2] == ("tab", current)]
                row = lay.rows[r]
                self.assertEqual(tb.owner(row, k), group)
                self.assertEqual(row[k - 1] == ("div", group), divided, row)
                shown = [w for row in lay.rows for w in tab_ids(row)]
                self.assertEqual(len(shown) + lay.hidden, 65)
                self.assertEqual(len(set(shown)), len(shown))
                self.check_fits(lay, 188)
                rows = tb.render(lay)          # a lone divider renders inside the template
                for text in rows:
                    self.assertLessEqual(set(text), ALPHABET)
                self.assertLessEqual(tb.text_width(draw(rows[-1], bar_env(lay))), 188)

    def test_prune_drops_markers_with_no_tab(self):
        row = [("head", 0, False), ("div", 1), ("tab", "@1", 1), ("div", 2), ("more", 3, 4)]
        tb.prune(row)
        self.assertEqual(row, [("div", 1), ("tab", "@1", 1), ("more", 3, 4)])

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
        # Measured from what each row draws, not from the gutter the layout claims: every row's
        # first tab starts at the same cell (G, 0-based), with equal slots the separators line
        # up across rows, and no row draws past the client's width.
        for width, slots in ((188, [32, 32]), (45, None)):
            with self.subTest(width=width):
                lay = tb.lay_out([DOTCLAUDE], SHARED5, width, "@4", 8, 22)
                if slots:
                    self.assertEqual(lay.slots, slots)
                env = bar_env(lay)
                starts, seps = [], []
                for row in tb.render(lay):
                    cols = []
                    text = draw(row, env, cols)
                    self.assertLessEqual(tb.text_width(text), width)
                    starts.append(cols[0])
                    seps.append(cells(text, "│"))
                self.assertEqual(set(starts), {lay.gutter})
                if slots:
                    common = min(len(s) for s in seps)
                    self.assertEqual({tuple(s[:common]) for s in seps}, {tuple(seps[0][:common])})
                self.check_fits(lay, width)

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
                                              lay.head, lay.colours[item[1]]))
                    elif item[0] == "div":
                        want.append(tb.divider(item[1], lay.head_w[item[1]] - 2,
                                               lay.colours[item[1]]))
                    elif item[0] == "tab":
                        want.append(tb.entry(item[1], item[2], lay.slots[r]))
                want += [tb.right_part(16)] if r == 0 else []
                self.assertEqual(row, "".join(want))
                self.assertEqual(row.count(tb.SEP), tb.separators(items))
        # Outside every range: each entry closes its range before the separator.
        self.assertTrue(tb.entry("@1", 1, 20).endswith("#[norange]" + tb.NORM + ",}}"))
        self.assertEqual(tb.SEP, "#[fg=colour240]│#[fg=colour250]")
        self.assertIn("┃", tb.divider(0, 5, 75))  # a packed group's divider reads differently
        self.assertNotIn("│", tb.divider(0, 5, 75))

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
        strip = "s/^([^ [][^ []?[^ []? )?(\\[[^]]*\\]|[^ []+ ·) (.+)$/\\3/"
        # Each substitution runs on the text cut to LABEL_CAP characters first (s/// is
        # quadratic), and the cut is a substitution too: `=` skips #[...] and counts ## once.
        cut = "#{s/^(.{128#}).+$/\\1/:%s}"
        self.assertIn("#{s/[#]/♯/;" + strip + ":" + cut % "pane_title" + "}", e)
        self.assertIn("#{s/[#]/♯/:" + cut % "pane_current_command" + "}", e)
        self.assertEqual(e.count("pane_title}"),
                         e.count("[#]/♯/;" + strip + ":" + cut % "pane_title" + "}"))
        self.assertEqual(e.count("pane_current_command}"),
                         e.count("#{s/[#]/♯/:" + cut % "pane_current_command" + "}"))
        self.assertNotIn("#{=/" + str(tb.LABEL_CAP), e)
        self.assertEqual(tb.LABEL_CAP, 128)
        self.assertGreater(tb.LABEL_CAP, 3 * tb.DEFAULT_SLOT)  # bytes, under a C locale
        for bad in ("{", "}", ",", ":", ";"):   # each would end the modifier or the #{...}
            self.assertNotIn(bad, strip)
        # The same pattern in Python's dialect ([ escaped in a set): what it keeps.
        py = re.compile(r"^([^ \[][^ \[]?[^ \[]? )?(\[[^]]*\]|[^ \[]+ ·) (.+)$")
        for title, label in (
                # Today's form, and the bracketed one a session keeps until its next prompt.
                ("✳ repo · label", "label"), ("⠂ repo · label", "label"),
                ("⣿ repo · label", "label"), ("repo · label", "label"),
                ("✳ [repo] label", "label"), ("⠂ [repo] label", "label"),
                ("⣿ [repo] label", "label"), ("[repo] label", "label"),
                # Neither form, or only the first prefix of two, or nothing after it.
                ("no prefix here", "no prefix here"), ("✳ idle", "✳ idle"),
                ("✳ a · b · x", "b · x"), ("✳ [a] [b] x", "[b] x"),
                ("[a] b · x", "b · x"), ("a · [b] x", "[b] x"),
                ("long word · x y", "long word · x y"), ("long word [x] y", "long word [x] y"),
                ("repo · ", "repo · "), ("[repo] ", "[repo] "),
                ("✳ [repo] ", "✳ [repo] "), ("✳ repo · ", "✳ repo · ")):
            with self.subTest(title=title):
                self.assertEqual(py.sub(r"\3", title), label)

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

    def test_a_tab_draws_exactly_its_slot_at_any_index_width(self):
        # The worst case on the phone: a 3-digit index, a star and a glyph take 9 cells, the
        # whole minimum slot; the label then shrinks to '…' or nothing, never past the slot.
        # Below that (a client a few cells wide, a 4-digit index) the tab is its index, cut to
        # the slot, so the nav columns still match what the bar draws.
        self.assertGreaterEqual(tb.MIN_SLOT_PHONE, len(" 999 ") + len("★ ◐ "))
        for index in (7, 42, 999, 1234):
            for slot in (1, 2, 3, 5, 8, tb.MIN_SLOT_PHONE, tb.MIN_SLOT_PHONE + 1,
                         tb.MIN_SLOT_PHONE + 2, tb.MIN_SLOT, tb.DEFAULT_SLOT):
                for star in ("", "1"):
                    for state in ("idle", "busy", "wait"):
                        for current in ("@5", "@6"):
                            with self.subTest(index=index, slot=slot, star=star, state=state,
                                              current=current):
                                env = {"windows": [window("@5", index, star, state)],
                                       "current": current}
                                text = draw(tb.entry("@5", index, slot), env)
                                self.assertEqual(tb.text_width(text), slot, text)
                                self.assertTrue(text.startswith(f" {index} "[:slot]), text)

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


# --- nav: Shift+arrows (pure) --------------------------------------------------------------------

def select(rows, current, direction):
    step = tb.nav_step(rows, current, direction)
    return step[1] if step and step[0] == "select" else step


class Nav(unittest.TestCase):
    def nav(self, lay):
        rows = tb.parse_nav(tb.nav_value(lay))
        self.assertIsNotNone(rows, tb.nav_value(lay))
        return rows

    def test_the_columns_are_where_each_row_draws_its_tabs(self):
        # Checked against the drawn rows, dividers (a lone one too) and +N included.
        big = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 11))) for k in range(6)]
        packed = [Group("alpha", tabs(1, 2)), Group("bravo", tabs(3, 4, 5)),
                  Group("charlie", tabs(6, 7, 8)), Group("delta", tabs(9, 10, 11))]
        cases = [([DOTCLAUDE], SHARED5, 188, "@4"), ([DOTCLAUDE], SHARED5, 45, "@4"),
                 (big, tabs(*range(61, 66)), 188, "@63"), (big, [], 45, "@60"),
                 (packed, tabs(*range(12, 26)), 188, "@1")]
        for groups, shared, width, current in cases:
            with self.subTest(width=width, current=current, groups=len(groups)):
                lay = tb.lay_out(groups, shared, width, current, 8, 22)
                rows = self.nav(lay)
                env = bar_env(lay, current)
                self.assertEqual(len(rows), len(lay.rows))
                for nav_row, fmt, items, slot in zip(rows, tb.render(lay), lay.rows, lay.slots):
                    starts = []
                    draw(fmt, env, starts)
                    self.assertEqual([t[1] for t in nav_row], starts)
                    self.assertEqual([t[0] for t in nav_row], tab_ids(items))
                    self.assertEqual({t[2] for t in nav_row}, {slot})

    def test_the_value_holds_only_ids_and_integers(self):
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 8, 22)
        self.assertEqual(tb.nav_value(lay), "0;@4:19:32,@6:52:32,@7:85:32,@8:118:32|"
                                            "1;@1:19:32,@2:52:32,@3:85:32,@5:118:32,@9:151:32")
        self.assertIn(("@tab_bar_nav", tb.nav_value(lay)), tb.session_ops(lay, tb.render(lay)))

    def test_the_live_shape_on_the_desktop(self):
        rows = self.nav(tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 8, 22))
        cases = [("@4", "right", "@6"), ("@8", "right", "@1"),     # past a row's end
                 ("@9", "right", "@4"), ("@4", "left", "@9"),      # wrapping
                 ("@1", "left", "@8"),
                 ("@7", "down", "@3"),                             # the tab under it
                 ("@9", "up", "@8"),                               # nothing above: the nearest
                 ("@4", "up", "@1"), ("@3", "down", "@7")]         # wrapping top and bottom
        for current, direction, want in cases:
            with self.subTest(current=current, direction=direction):
                self.assertEqual(select(rows, current, direction), want)

    def test_the_live_shape_on_the_phone(self):
        # Rows [@4 @6] [@7 @8] [@1 @2 @3] [@5 @9]; tabs start at 11 and 28, or 11, 22 and 33.
        rows = self.nav(tb.lay_out([DOTCLAUDE], SHARED5, 45, "@4", 8, 22))
        cases = [("@6", "down", "@8"), ("@8", "down", "@2"), ("@3", "down", "@9"),
                 ("@2", "up", "@7"), ("@4", "up", "@5"), ("@9", "down", "@6"),
                 ("@6", "right", "@7"), ("@9", "right", "@4"), ("@1", "left", "@8")]
        for current, direction, want in cases:
            with self.subTest(current=current, direction=direction):
                self.assertEqual(select(rows, current, direction), want)

    def test_plus_n_and_a_hidden_window(self):
        groups = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 11))) for k in range(6)]
        rows = self.nav(tb.lay_out(groups, tabs(*range(61, 66)), 188, "@63", 28, 16))
        self.assertEqual(select(rows, "@63", "right"), "@1")       # +N isn't a tab: wraps
        self.assertEqual(select(rows, "@63", "left"), "@24")
        self.assertEqual(select(rows, "@63", "up"), "@19")  # @63 at 152: @19 spans 125-154
        # A window the layout hid (the current one moved before the relayout): by number.
        self.assertEqual(tb.nav_step(rows, "@45", "right"), ("next-window",))
        self.assertEqual(tb.nav_step(rows, "@45", "left"), ("previous-window",))
        self.assertIsNone(tb.nav_step(rows, "@45", "up"))
        self.assertIsNone(tb.nav_step(rows, "@45", "down"))

    def test_a_missing_or_bad_option_falls_back(self):
        bad = ["", "0;@4:19", "0;@4:19:32,", "0;@4:19:32|", "0;$4:19:32", "0;@4:19:32\n",
               "1;@4:19:32|0;@6:52:32", "0;@4:1:1|0;@6:1:1", "#{E:x}", "0;@4:19:32 ; kill-server",
               "0;@4:" + "9" * 40 + ":32", "|".join(f"{i};@4:1:1" for i in range(20000))]
        for text in bad:
            with self.subTest(text=text[:40]):
                rows = tb.parse_nav(text)
                self.assertIsNone(rows)
                self.assertEqual(tb.nav_step(rows, "@4", "left"), ("previous-window",))
                self.assertEqual(tb.nav_step(rows, "@4", "right"), ("next-window",))
                self.assertIsNone(tb.nav_step(rows, "@4", "up"))
                self.assertIsNone(tb.nav_step(rows, "@4", "down"))

    def test_one_tab_or_one_row_stays(self):
        rows = [[("@1", 8, 32)]]
        for direction in tb.DIRECTIONS:
            self.assertIsNone(tb.nav_step(rows, "@1", direction))
        rows = [[("@1", 8, 32), ("@2", 41, 32)]]
        self.assertIsNone(tb.nav_step(rows, "@2", "up"))
        self.assertEqual(select(rows, "@2", "right"), "@1")


# --- arrange: placements, order and moves (pure) --------------------------------------------------

P = tb.Place
REPO_KEY, KAR_KEY = "p:/r/.git", "p:/k/.git"
TAB_OF = {"@1": tb.Tab("shared", "", "hq", "hq:"), "@2": tb.Tab("lead", "/r/.git", "repo", "lead"),
          "@3": tb.Tab("lane", "/r/.git", "repo", "a"), "@4": tb.Tab("lane", "/r/.git", "repo", "b"),
          "@5": tb.Tab("lead", "/k/.git", "kar", "lead"), "@6": tb.Tab("shared", "", "x", "x:")}
WINS = [(int(w[1:]), w) for w in TAB_OF]


def arranged(places, wins=WINS):
    groups, shared, names = tb.group_windows(wins, TAB_OF, places)
    return [(g.key, [w for w, _ in g.tabs]) for g in groups] + [("s", [w for w, _ in shared])], \
        groups, shared, names


class Placement(unittest.TestCase):
    def test_a_valid_placement_reads_back(self):
        for p in (P("s", 0), P(REPO_KEY, 999), P("c:1", 3, REPO_KEY, "work ♯1"),
                  P("c:9999", 0, "s", ""), P("c:2", 0, "c:1", "")):
            with self.subTest(p=p):
                self.assertEqual(tb.parse_place(tb.place_text(p)), p)

    def test_each_bad_field_or_shape_is_no_placement(self):
        good = {"row": "s", "pos": 0, "after": "", "name": ""}
        self.assertEqual(tb.parse_place(json.dumps(good)), P("s", 0))
        for change in ({"row": "x"}, {"row": "p:rel"}, {"row": "c:0"}, {"row": "c:10000"},
                       {"row": "c:01"}, {"row": 5}, {"row": "s\n"}, {"row": "p:/a\x07"},
                       {"pos": -1}, {"pos": 1000}, {"pos": True}, {"pos": 1.0}, {"pos": "1"},
                       {"after": "x"}, {"after": None}, {"name": "a#b"}, {"name": "x" * 17},
                       {"name": "a\x01"}, {"name": 3}, {"name": " a"}):
            with self.subTest(change=change):
                self.assertIsNone(tb.parse_place(json.dumps({**good, **change})))
        for text in ("", "null", "[]", "{", json.dumps({**good, "extra": 1}),
                     json.dumps({k: v for k, v in good.items() if k != "name"}),
                     json.dumps({**good, "row": "p:/" + "a" * tb.PLACE_MAX}),
                     json.dumps(good) + "\x07", "\t" + json.dumps(good),
                     "[" * 1000 + "]" * 1000):
            with self.subTest(text=text[:30]):
                self.assertIsNone(tb.parse_place(text))
        self.assertIsNone(tb.place_text(P("p:/" + "a" * tb.PLACE_MAX, 0)))   # can't read back
        self.assertIsNone(tb.place_text(P("p:/a\nb", 0)))

    def test_a_row_name_is_cleaned(self):
        hostile = "a\"b'c;d#[e%f$(g)$HOME~h\\i"
        self.assertEqual(tb.clean_row_name(hostile), "a\"b'c;d♯[e%f$(g…")
        self.assertEqual(tb.clean_row_name("\x1b[31m red\x00 "), "[31m red")
        self.assertEqual(tb.clean_row_name("   "), "")
        for raw in (hostile, "漢字" * 10, "#" * 40, "\x01 x", "x" * 16):
            with self.subTest(raw=raw):
                name = tb.clean_row_name(raw)
                self.assertLessEqual(tb.text_width(name), tb.ROW_NAME_CELLS)
                self.assertNotIn("#", name)
                self.assertEqual(tb.clean_row_name(name), name)   # a stored name stays valid

    def test_the_custom_colour_is_outside_the_palette(self):
        self.assertNotIn(tb.CUSTOM_COLOUR, tb.PALETTE)
        lay = tb.lay_out([Group("", tabs(1), tb.CUSTOM_COLOUR, "c:1")], tabs(2), 188, "@1", 8, 22)
        self.assertIn(f"#[fg=colour{tb.CUSTOM_COLOUR}]#[bold]▸", tb.render(lay)[0])


class Order(unittest.TestCase):
    def test_no_placement_is_todays_order(self):
        rows, _, _, names = arranged({})
        self.assertEqual(rows, [(REPO_KEY, ["@2", "@3", "@4"]), (KAR_KEY, ["@5"]),
                                ("s", ["@1", "@6"])])
        self.assertEqual(names["@3"], ("a", "0", ""))
        self.assertEqual(names["@5"], ("lead", "1", ""))
        self.assertEqual(names["@1"], ("hq:", "", ""))

    def test_a_manual_row_puts_its_placed_tabs_first_then_the_rest_in_auto_order(self):
        rows, *_ = arranged({"@4": P(REPO_KEY, 0), "@2": P(REPO_KEY, 1)})
        self.assertEqual(rows[0], (REPO_KEY, ["@4", "@2", "@3"]))

    def test_a_new_window_appends_and_a_closed_neighbour_leaves_no_gap(self):
        places = {"@4": P(REPO_KEY, 0), "@3": P(REPO_KEY, 1), "@2": P(REPO_KEY, 2)}
        tab_of = dict(TAB_OF, **{"@7": tb.Tab("lane", "/r/.git", "repo", "c")})
        groups, _, _ = tb.group_windows(WINS + [(7, "@7")], tab_of, places)
        self.assertEqual([w for w, _ in groups[0].tabs], ["@4", "@3", "@2", "@7"])
        rows, *_ = arranged(places, [w for w in WINS if w[1] != "@3"])
        self.assertEqual(rows[0], (REPO_KEY, ["@4", "@2"]))

    def test_a_tab_outside_its_projects_row_keeps_its_colour_and_shows_its_repo(self):
        rows, _, _, names = arranged({"@3": P("s", 0), "@1": P(KAR_KEY, 0)})
        self.assertEqual(rows, [(REPO_KEY, ["@2", "@4"]), (KAR_KEY, ["@1", "@5"]),
                                ("s", ["@3", "@6"])])
        self.assertEqual(names["@3"], ("repo·a", "0", ""))
        self.assertEqual(names["@1"], ("hq:", "", ""))    # a shared tab keeps its name

    def test_a_project_row_no_window_classifies_into_falls_back_to_auto(self):
        rows, _, _, names = arranged({"@1": P("p:/gone/.git", 0), "@3": P("p:/gone/.git", 1)})
        self.assertEqual(rows, arranged({})[0])
        self.assertEqual(names, arranged({})[3])

    def test_moving_every_tab_out_of_a_project_recolours_nothing(self):
        places = {w: P("s", k) for k, w in enumerate(("@2", "@3", "@4"))}
        rows, groups, _, names = arranged(places)
        self.assertEqual([g.key for g in groups], [KAR_KEY])
        self.assertEqual(groups[0].colour, tb.PALETTE[1])
        self.assertEqual(names["@5"][1], "1")
        self.assertEqual(names["@2"], ("repo·lead", "0", ""))

    def test_a_custom_row_follows_its_anchor_else_goes_last_among_the_groups(self):
        cases = [({"@3": P("c:1", 0, REPO_KEY)}, [REPO_KEY, "c:1", KAR_KEY]),
                 ({"@3": P("c:1", 0, KAR_KEY)}, [REPO_KEY, KAR_KEY, "c:1"]),
                 ({"@3": P("c:1", 0, "s")}, [REPO_KEY, KAR_KEY, "c:1"]),
                 ({"@3": P("c:1", 0, "p:/gone/.git")}, [REPO_KEY, KAR_KEY, "c:1"]),
                 ({"@3": P("c:3", 0, REPO_KEY), "@4": P("c:2", 0, REPO_KEY)},
                  [REPO_KEY, "c:2", "c:3", KAR_KEY]),
                 ({"@3": P("c:1", 0, REPO_KEY), "@4": P("c:2", 0, "c:1")},
                  [REPO_KEY, "c:1", "c:2", KAR_KEY]),
                 ({"@3": P("c:1", 0, "c:2"), "@4": P("c:2", 0, "c:1")},    # a cycle: by id
                  [REPO_KEY, KAR_KEY, "c:1", "c:2"]),
                 ({"@5": P("c:1", 0, "c:1")}, [REPO_KEY, "c:1"])]          # itself, kar gone
        for places, want in cases:
            with self.subTest(places=places):
                rows, groups, _, _ = arranged(places)
                self.assertEqual([g.key for g in groups], want)

    def test_a_custom_row_is_a_group_with_its_lowest_window_ids_name(self):
        places = {"@6": P("c:4", 0, KAR_KEY, "late"), "@3": P("c:4", 1, REPO_KEY, "work")}
        rows, groups, shared, names = arranged(places)
        custom = groups[1]
        self.assertEqual((custom.key, custom.name, custom.after, custom.colour),
                         ("c:4", "work", REPO_KEY, tb.CUSTOM_COLOUR))
        self.assertEqual([w for w, _ in custom.tabs], ["@6", "@3"])
        self.assertEqual(names["@3"], ("repo·a", "0", "1"))
        self.assertEqual(names["@6"], ("x:", "", "1"))

    def test_custom_rows_pack_and_end_in_plus_n_like_project_rows(self):
        groups = [Group("", tabs(1, 2), tb.CUSTOM_COLOUR, "c:1"), Group("bravo", tabs(3, 4, 5)),
                  Group("charlie", tabs(6, 7, 8)), Group("delta", tabs(9, 10, 11))]
        lay = tb.lay_out(groups, tabs(*range(12, 26)), 188, "@1", 28, 16)
        self.assertIn(("div", 0), [i for row in lay.rows for i in row])
        rows = tb.render(lay)
        self.assertIn(f"#[fg=colour{tb.CUSTOM_COLOUR}]#[bold]┃▸", "".join(rows))
        many = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 11)),
                      tb.CUSTOM_COLOUR if k == 2 else tb.PALETTE[0], f"c:{k}") for k in range(6)]
        lay = tb.lay_out(many, [], 188, "@25", 28, 16)
        self.assertEqual(len(lay.rows), tb.MAX_ROWS)
        self.assertEqual(lay.rows[-1][-1][0], "more")
        self.assertIn("@25", [w for row in lay.rows for w in tab_ids(row)])

    def test_the_gutter_widens_for_a_long_row_name(self):
        name = tb.clean_row_name("a very long row name indeed")
        lay = tb.lay_out([Group("ab", tabs(1)), Group(name, tabs(2), tb.CUSTOM_COLOUR, "c:1")],
                         tabs(3), 188, "@1", 8, 22)
        self.assertEqual(lay.head, tb.ROW_NAME_CELLS + 2)
        self.assertEqual(lay.heads[1], name)

    def test_a_hostile_row_name_never_reaches_a_row(self):
        name = tb.clean_row_name("#(touch x)%#{E:pwn}")
        rows, groups, shared, _ = arranged({"@3": P("c:1", 0, REPO_KEY, name)})
        for width in (188, 45):
            lay = tb.lay_out(groups, shared, width, "@2", 8, 22)
            for row in tb.render(lay):
                self.assertNotIn("#(", row)
                self.assertNotIn("touch", row)
                self.assertLessEqual(set(row), ALPHABET)
            self.assertIn(("@tab_bar_g1", tb.short(name, width < 100)), tb.session_ops(lay, []))


class Moves(unittest.TestCase):
    def test_put_rewrites_every_member_of_the_target_row(self):
        _, groups, shared, _ = arranged({})
        self.assertEqual(tb.put(groups, shared, "@1", "@3", False),
                         {"@2": P(REPO_KEY, 0), "@1": P(REPO_KEY, 1), "@3": P(REPO_KEY, 2),
                          "@4": P(REPO_KEY, 3)})
        self.assertEqual(tb.put(groups, shared, "@2", "@4", True),
                         {"@3": P(REPO_KEY, 0), "@4": P(REPO_KEY, 1), "@2": P(REPO_KEY, 2)})
        self.assertEqual(tb.put(groups, shared, "@3", "@3", True), {})
        _, groups, shared, _ = arranged({"@3": P("c:2", 0, KAR_KEY, "work")})
        self.assertEqual(tb.put(groups, shared, "@6", "@3", True),
                         {"@3": P("c:2", 0, KAR_KEY, "work"), "@6": P("c:2", 1, KAR_KEY, "work")})

    def test_left_and_right_stop_at_the_rows_ends(self):
        _, groups, shared, _ = arranged({})
        self.assertEqual(tb.side_step(groups, shared, "@2", "left"), {})
        self.assertEqual(tb.side_step(groups, shared, "@4", "right"), {})
        self.assertEqual(tb.side_step(groups, shared, "@5", "right"), {})
        self.assertEqual(tb.side_step(groups, shared, "@3", "left"),
                         {"@3": P(REPO_KEY, 0), "@2": P(REPO_KEY, 1), "@4": P(REPO_KEY, 2)})
        self.assertEqual(tb.side_step(groups, shared, "@1", "right"),
                         {"@6": P("s", 0), "@1": P("s", 1)})

    def test_up_and_down_cross_overflow_rows_and_stop_at_the_top_and_bottom(self):
        rows = [[("@1", 8, 20), ("@2", 29, 20), ("@3", 50, 20)], [("@4", 8, 30), ("@5", 39, 30)],
                [("@6", 8, 20)]]
        self.assertEqual(tb.climb(rows, "@3", "down"), "@5")
        self.assertEqual(tb.climb(rows, "@2", "down"), "@4")    # @4 spans 8-37: covers 29
        self.assertEqual(tb.climb(rows, "@5", "down"), "@6")
        self.assertEqual(tb.climb(rows, "@4", "up"), "@1")
        self.assertIsNone(tb.climb(rows, "@1", "up"))
        self.assertIsNone(tb.climb(rows, "@6", "down"))
        self.assertIsNone(tb.climb(rows, "@9", "down"))         # hidden in +N

    def test_a_new_row_takes_the_next_id_any_placement_names(self):
        _, groups, shared, _ = arranged({})
        self.assertEqual(tb.new_row(groups, shared, "@3", []), {"@3": P("c:1", 0, REPO_KEY)})
        places = [P("c:4", 0, "s"), P("c:2", 0, "c:7"), P("s", 3)]
        self.assertEqual(tb.new_row(groups, shared, "@1", places), {"@1": P("c:8", 0, "s")})
        self.assertEqual(tb.new_row(groups, shared, "@1", [P("c:9999", 0)]), {})
        _, groups, shared, _ = arranged({"@3": P("c:1", 0, REPO_KEY)})
        self.assertEqual(tb.new_row(groups, shared, "@3", []), {})   # alone already
        _, groups, shared, _ = arranged({"@3": P("c:1", 0, REPO_KEY), "@4": P("c:1", 1, REPO_KEY)})
        self.assertEqual(tb.new_row(groups, shared, "@4", [P("c:1", 0)]),
                         {"@4": P("c:2", 0, "c:1")})

    def test_a_new_row_from_a_lone_tab_does_nothing(self):
        _, groups, shared, _ = arranged({})
        self.assertEqual(tb.new_row(groups, shared, "@5", []), {})     # kar's only tab
        _, groups, shared, _ = arranged({}, [w for w in WINS if w[1] != "@6"])
        self.assertEqual(tb.new_row(groups, shared, "@1", []), {})     # the shared row's only

    def test_a_new_row_from_a_shared_tab_sits_just_above_the_shared_rows(self):
        _, groups, shared, _ = arranged({})
        places = tb.new_row(groups, shared, "@6", [])
        rows, *_ = arranged(places)
        self.assertEqual(rows, [(REPO_KEY, ["@2", "@3", "@4"]), (KAR_KEY, ["@5"]),
                                ("c:1", ["@6"]), ("s", ["@1"])])

    def test_rename_row_names_every_member_and_only_in_a_custom_row(self):
        _, groups, _, _ = arranged({"@3": P("c:1", 0, REPO_KEY), "@6": P("c:1", 1, REPO_KEY)})
        self.assertEqual(tb.rename_row(groups, "@6", "work"),
                         {"@3": P("c:1", 0, REPO_KEY, "work"), "@6": P("c:1", 1, REPO_KEY, "work")})
        self.assertEqual(tb.rename_row(groups, "@2", "work"), {})

    def test_a_drop_goes_before_or_after_by_the_half_of_the_slot(self):
        rows = [(0, [("@2", 19, 32), ("@3", 52, 32)]), (1, [("@1", 19, 32)])]
        for x, want in ((52, False), (67, False), (68, True), (83, True), (84, True)):
            with self.subTest(x=x):
                self.assertEqual(tb.drop_side(rows, "@3", x, 0), want)
        self.assertIsNone(tb.drop_side(rows, "@9", 20, 0))
        self.assertIsNone(tb.drop_side([], "@3", 20, 0))

    # One logical row a b c d drawn as [a b] / [c d] (lines 0 and 1), and kar's lead on line 2.
    ROW4 = {f"@{i}": tb.Tab("lane", "/r/.git", "repo", n) for i, n in zip(range(1, 5), "abcd")}
    ROW4["@5"] = tb.Tab("lead", "/k/.git", "kar", "lead")
    NAV4 = [(0, [("@1", 56, 18), ("@2", 75, 18)]), (1, [("@3", 56, 18), ("@4", 75, 18)]),
            (2, [("@5", 56, 18)])]

    def drawn(self, places=None):
        """(groups, shared, nav rows) for ROW4 at a width that splits its row 2 + 2."""
        groups, shared, _ = tb.group_windows([(i, f"@{i}") for i in range(1, 6)], self.ROW4,
                                             places or {})
        lay = tb.lay_out(groups, shared, 100, "@1", 50, 0)
        return groups, shared, tb.parse_nav_rows(tb.nav_value(lay))

    def line_of(self, nav, wid):
        return next(line for line, tabs in nav for w, _, _ in tabs if w == wid)

    def test_a_same_row_move_lands_on_the_drawn_line_aimed_at(self):
        groups, shared, nav = self.drawn()
        self.assertEqual([[w for w, _, _ in tabs] for _, tabs in nav],
                         [["@1", "@2"], ["@3", "@4"], ["@5"]])
        for src, dst, after, want in (
                ("@1", "@3", False, True),      # Down on a, or a left-half drop of a on c
                ("@4", "@2", True, False),      # a right-half drop of d on b
                ("@1", "@3", True, True),       # already lands on line 1
                ("@4", "@2", False, False),
                ("@2", "@1", False, False),     # one line: nothing shifts across lines
                ("@5", "@3", False, False),     # another row: put() leaves no gap here
                ("@1", "@5", True, True)):
            with self.subTest(src=src, dst=dst, after=after):
                self.assertEqual(tb.on_line(groups, shared, nav, src, dst, after), want)
                places = tb.put(groups, shared, src, dst, want)
                self.assertEqual(self.line_of(self.drawn(places)[2], src),
                                 self.line_of(nav, dst))

    def test_a_drop_on_a_lines_gutter_or_tail_lands_on_that_line(self):
        groups, shared, nav = self.drawn()
        for src, x, line, want in (("@1", 3, 1, ["@1", "@4"]), ("@4", 150, 0, ["@1", "@4"]),
                                   ("@5", 3, 1, ["@5", "@3"])):
            with self.subTest(src=src, line=line):
                dst, after = tb.row_end(nav, x, line)
                places = tb.put(groups, shared, src, dst,
                                tb.on_line(groups, shared, nav, src, dst, after))
                drawn = self.drawn(places)[2]
                self.assertEqual([w for w, _, _ in drawn[line][1]][:2], want)

    def test_move_down_through_put_and_lay_out_lands_on_the_line_below(self):
        groups, shared, nav = self.drawn()
        dst = tb.climb([tabs for _, tabs in nav], "@1", "down")
        self.assertEqual(dst, "@3")
        places = tb.put(groups, shared, "@1", dst, tb.on_line(groups, shared, nav, "@1", dst, False))
        self.assertEqual(self.line_of(self.drawn(places)[2], "@1"), 1)
        # Without the flip, the gap put() closes puts it back on line 0.
        self.assertEqual(self.line_of(self.drawn(tb.put(groups, shared, "@1", dst, False))[2],
                                      "@1"), 0)

    def test_a_hidden_member_leaves_the_side_alone(self):
        groups, shared, nav = self.drawn()
        hidden = [(line, [t for t in tabs if t[0] != "@4"]) for line, tabs in nav]
        self.assertFalse(tb.on_line(groups, shared, hidden, "@1", "@3", False))

    def test_a_drop_on_a_rows_gutter_or_tail_goes_first_or_last(self):
        rows = [(0, [("@2", 19, 32), ("@3", 52, 32)]), (2, [("@1", 19, 32)])]
        self.assertEqual(tb.row_end(rows, 3, 0), ("@2", False))
        self.assertEqual(tb.row_end(rows, 150, 0), ("@3", True))
        self.assertEqual(tb.row_end(rows, 150, 2), ("@1", True))
        self.assertIsNone(tb.row_end(rows, 3, 1))                 # no tabs on that line


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
                         + ["@tab_bar_nav", "status", "status-position", "status-left",
                            "status-right", "@tab_bar_sig"])
        self.assertEqual([c[4] for c in cmds[1:1 + len(rows)]], rows)
        self.assertEqual(cmds[-1], ["set-option", "-t", "$3", "@tab_bar_sig", "SIG"])
        no_status = tmux_words(tb.write_line("$3", tb.session_ops(lay, rows), None, "SIG"))
        self.assertNotIn("status", [c[3] for c in no_status if c[1] == "-t"])


# --- claude.conf --------------------------------------------------------------------------------

HOOK = ("'run-shell -b \"[ -x $HOME/.local/bin/tmux-tab-bar ] && "
        "$HOME/.local/bin/tmux-tab-bar layout >/dev/null 2>&1; true\"'")


# The script when it is installed, else window order for Left and Right (Up and Down do nothing).
NAV_CMD = "\"$HOME/.local/bin/tmux-tab-bar\" nav {dir} \"#{{client_name}}\" >/dev/null 2>&1; true"
NAV_BIND = ("bind -n S-{key} if-shell '[ -x \"$HOME/.local/bin/tmux-tab-bar\" ]' "
            "{{ run-shell '" + NAV_CMD + "' }}{fallback}\n")
NAV_FALLBACK = {"Left": " { previous-window }", "Right": " { next-window }", "Up": "", "Down": ""}


class Conf(unittest.TestCase):
    CLAUDE_ITEM = re.compile(r'^\s*"(#\{\?@claude_state|Shelf…|Replies before pass)')

    def items(self, start):
        with open(CONF) as f:
            text = f.read()
        block = text[text.index(start):]
        block = block[:block.index("\n\n")]
        return [line.strip().rstrip("\\").rstrip() for line in block.splitlines()
                if self.CLAUDE_ITEM.match(line)]

    # The commands the confs start a line with (names and aliases). A line starting with any
    # other word is prose that lost its #, and tmux refuses the whole file on it.
    COMMANDS = {"bind", "bind-key", "unbind", "unbind-key", "set", "set-option", "setw",
                "set-window-option", "set-hook", "if", "if-shell", "run", "run-shell",
                "display-menu", "menu", "display-popup", "popup", "display", "display-message",
                "choose-tree", "switch-client", "switchc", "select-pane", "selectp",
                "select-window", "selectw", "send-keys", "send", "copy-mode",
                "command-prompt", "confirm-before", "source-file", "source", "new-window",
                "neww", "split-window", "splitw", "resize-pane", "resizep", "}"}

    def test_every_line_of_each_conf_is_a_comment_or_a_command(self):
        # The real-tmux tests source claude.conf, but they can't run in the sandbox.
        for path in (CONF, os.path.join(REPO, "tmux", "base.conf")):
            cont = False
            with open(path) as f:
                for n, line in enumerate(f.read().splitlines(), 1):
                    s = line.strip()
                    if not cont and s and not s.startswith("#"):
                        with self.subTest(conf=os.path.basename(path), line=n):
                            self.assertIn(s.split()[0], self.COMMANDS, line)
                    cont = line.endswith("\\") and not s.startswith("#")

    def test_the_tap_menu_has_the_right_click_menus_claude_items(self):
        right = self.items("bind -n MouseDown3Status")
        tap = self.items("bind -n MouseUp1Status")
        self.assertEqual(len(right), 4)
        self.assertEqual(tap, right)

    def test_every_menu_and_popup_opens_at_row_0_under_a_top_bar(self):
        # tmux 3.7c masks a menu or popup out of a pane's redraw at the line's window y, not its
        # screen y, so under a top bar a busy pane painted over an overlay's first rows (the tap
        # menu lost its Star row). Row 0 escapes it; a bar at the bottom keeps tmux's spot. A
        # menu item's command is expanded when the menu opens, so a popup inside one has ##.
        tab = "#{?#{==:#{status-position},top},0,#{popup_window_status_line_y}}"
        centre = "#{?#{==:#{status-position},top},0,#{popup_centre_y}}"
        self.assertEqual(tb.OVERLAY_Y_CENTRE, centre)
        with open(CONF) as f:
            text = f.read()
        self.assertIn(f"set -g @overlay_y_tab '{tab}'\n", text)
        self.assertIn(f"set -g @overlay_y_centre '{centre}'\n", text)
        with open(os.path.join(REPO, "tmux", "base.conf")) as f:
            base = f.read()
        seen = 0
        for name, body, want in (("claude.conf", text, {"tab": "#{E:@overlay_y_tab}",
                                                         "top": "#{E:@overlay_y_centre}"}),
                                 ("base.conf", base, {"top": centre})):
            for line in body.splitlines():
                if line.lstrip().startswith("#"):
                    continue
                for m in re.finditer(r"display-(menu|popup)\b(.*)", line):
                    seen += 1
                    with self.subTest(conf=name, line=line.strip()[:60]):
                        y = re.search(r"-y '([^']*)'", m.group(2))
                        self.assertIsNotNone(y, "no -y")
                        kind = "tab" if "-x W" in m.group(2) else "top"
                        expect = want[kind]
                        if line.lstrip().startswith('"'):          # inside a menu item
                            expect = expect.replace("#", "##")
                        self.assertEqual(y.group(1), expect)
        self.assertEqual(seen, 11)

    def test_the_fallback_tab_formats_cut_the_title_before_stripping_it(self):
        # The single row drawn before the first layout (or with no script): s/// is quadratic,
        # so an uncut 212 KB title of "✳ " took 41 ms a tab; cut, 13 ms.
        with open(CONF) as f:
            text = f.read()
        for opt in ("window-status-format", "window-status-current-format"):
            with self.subTest(opt=opt):
                line = next(l for l in text.splitlines() if l.startswith(f"setw -g {opt} "))
                self.assertIn("#{s/✳ //:#{s/^(.{128#}).+$/\\\\1/:pane_title}}", line)
                self.assertEqual(line.count("pane_title}"), 1)

    def test_the_tap_menu_has_no_kill_or_respawn_and_no_stay_open(self):
        with open(CONF) as f:
            text = f.read()
        block = text[text.index("bind -n MouseUp1Status"):]
        block = block[:block.index("\n\n")]
        self.assertNotIn("kill-window", block)
        self.assertNotIn("respawn-window", block)
        self.assertNotRegex(block, r"display-menu[^\n]* -O")

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

    def test_shift_arrows_run_nav_for_the_client_that_pressed_them(self):
        with open(CONF) as f:
            text = f.read()
        for key in ("Left", "Right", "Up", "Down"):
            with self.subTest(key=key):
                self.assertIn(NAV_BIND.format(key=key, dir=key.lower(),
                                              fallback=NAV_FALLBACK[key]), text)
        self.assertEqual(text.count('tmux-tab-bar" nav '), 4)
        with open(os.path.join(REPO, "tmux", "base.conf")) as f:
            base = f.read()
        self.assertNotIn("S-Up", base)          # claude.conf, sourced after it, owns all four

    def test_the_nav_command_exits_0_and_says_nothing_whatever_the_script_does(self):
        cmd = NAV_CMD.format(dir="left").replace("#{client_name}", "/dev/pts/9")
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
                                   timeout=10, env={"HOME": home, "PATH": "/usr/bin:/bin"})
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def conf(self):
        with open(CONF) as f:
            return f.read()

    def bindings(self):
        """Every `bind` in claude.conf, whole: a { block to its closing } at column 0, else
        the line and its \\ continuations."""
        out, block = [], None
        for line in self.conf().splitlines():
            if block is None and line.startswith("bind "):
                block = [line]
                if not line.endswith(("{", "\\")):
                    out.append(line)
                    block = None
            elif block is not None:
                block.append(line)
                if (block[0].endswith("{") and line == "}") \
                        or (block[0].endswith("\\") and not line.endswith("\\")):
                    out.append("\n".join(block))
                    block = None
        return out

    def test_the_b_check_sees_a_b_anywhere_in_a_binding(self):
        for bad in ("run-shell -b 'x'", "run-shell -C -b 'x'", "run-shell -bC 'x'"):
            self.assertRegex(f"bind -n X {{\n  if -F '1' {{\n    {bad}\n  }}\n}}",
                             r"\brun-shell(?:\s+-\w+)*?\s+-\w*b")

    def tap_menu(self, binding):
        """The tap branch inside `binding`: from its window_active test to its switch-client."""
        text = self.conf()
        block = text[text.index(f"bind -n {binding} "):]
        start = block.index("if -F -t = '#{window_active}' {")
        end = block.index("switch-client -t =\n      }", start)
        return block[start:end]

    def test_a_drag_end_on_its_own_tab_is_exactly_the_tap(self):
        tap, drag = self.tap_menu("MouseUp1Status"), self.tap_menu("MouseDragEnd1Status")
        self.assertEqual(tap, drag)
        self.assertIn('"Move…" m { run-shell \'"$HOME/.local/bin/tmux-tab-bar" menu '
                      '"#{client_name}" "#{window_id}" >/dev/null 2>&1; true\' }', tap)
        # The verified prompt shape: a quoted template with %%%, never the { } form.
        self.assertIn('"#{?@tab_row_custom,,-}Name row…" N { command-prompt -p "row name:" '
                      '"set -w @tab_row_name_in \\"%%%\\" ; run-shell \'\\"$HOME/.local/bin/'
                      'tmux-tab-bar\\" name-row \\"#{client_name}\\" >/dev/null 2>&1; true\'" }',
                      tap)

    def test_the_drag_bindings_record_drop_and_clear(self):
        text = self.conf()
        self.assertIn("bind -n MouseUp1Status {\n  set -u @tab_bar_drag\n", text)
        # A press records a tab's id, or `more` for +N; every other press clears the flag.
        self.assertIn("bind -n MouseDown1Status set -F @tab_bar_drag '#{?#{==:#{mouse_status_range},"
                      "window},#{window_id},#{mouse_status_range}}'\n", text)
        for key in ("MouseDown1StatusDefault", "MouseDown1StatusLeft", "MouseDown1StatusRight",
                    "MouseDragEnd1Border"):
            with self.subTest(key=key):
                self.assertIn(f"bind -n {key} set -u @tab_bar_drag\n", text)
        for line in ("bind -n MouseDown1Pane { set -u @tab_bar_drag ; select-pane -t = ; "
                     "send-keys -M }\n",
                     "bind -n MouseDown1Border { set -u @tab_bar_drag ; select-pane -M }\n",
                     "bind -T copy-mode MouseDown1Pane { set -u @tab_bar_drag ; select-pane }\n",
                     "bind -T copy-mode-vi MouseDown1Pane { set -u @tab_bar_drag ; select-pane }\n"):
            with self.subTest(line=line):
                self.assertIn(line, text)
        # The end: the tap on its own tab, the window list from +N to +N, a drop from a tab,
        # else nothing; the flag cleared on every path.
        self.assertIn("bind -n MouseDragEnd1Status {\n  if -F '#{&&:#{==:#{mouse_status_range},"
                      "window},#{==:#{@tab_bar_drag},#{window_id}}}' {\n    set -u @tab_bar_drag\n",
                      text)
        self.assertIn("  } {\n    if -F '#{&&:#{==:#{mouse_status_range},more},"
                      "#{==:#{@tab_bar_drag},more}}' {\n      set -u @tab_bar_drag\n"
                      "      choose-tree -Zw\n    } {\n      if -F '#{m:@*,#{@tab_bar_drag}}' {\n"
                      "        run-shell '\"$HOME/.local/bin/tmux-tab-bar\" drop \"#{@tab_bar_drag}\" "
                      "\"#{window_id}\" \"#{mouse_x}\" \"#{mouse_status_line}\" "
                      "\"#{mouse_status_range}\" \"#{client_name}\" >/dev/null 2>&1; true'\n"
                      "      }\n      set -u @tab_bar_drag\n    }\n  }\n}\n", text)
        self.assertIn("bind -n MouseDragEnd1StatusDefault {\n  run-shell '\"$HOME/.local/bin/"
                      "tmux-tab-bar\" drop-row \"#{@tab_bar_drag}\" \"#{mouse_x}\" "
                      "\"#{mouse_status_line}\" \"#{client_name}\" >/dev/null 2>&1; true'\n"
                      "  set -u @tab_bar_drag\n}", text)
        self.assertNotIn("bind -n MouseDrag1Status", text)        # no live preview
        # No -b anywhere in a binding: two quick drops or moves must queue, not race.
        bindings = self.bindings()
        self.assertGreater(len(bindings), 25)
        for block in bindings:
            with self.subTest(binding=block[:60]):
                self.assertNotRegex(block, r"\brun-shell(?:\s+-\w+)*?\s+-\w*b")
        # The pane guard: tmux 3.7c's default inside it, and the release kept for apps.
        self.assertIn("bind -n MouseDrag1Pane if -F '#{==:#{@tab_bar_drag},}' { if -F "
                      "'#{||:#{pane_in_mode},#{mouse_any_flag}}' { send-keys -M } "
                      "{ copy-mode -M } }\n", text)
        self.assertIn("bind -n MouseDragEnd1Pane if -F '#{@tab_bar_drag}' "
                      "{ set -u @tab_bar_drag } { send-keys -M }\n", text)
        # A pane in copy mode looks its keys up in the mode's table first: guarded there too.
        for table in ("copy-mode", "copy-mode-vi"):
            with self.subTest(table=table):
                self.assertIn(f"bind -T {table} MouseDrag1Pane if -F '#{{==:#{{@tab_bar_drag}},}}'"
                              " { select-pane ; send-keys -X begin-selection }\n", text)
                self.assertIn(f"bind -T {table} MouseDragEnd1Pane if -F '#{{@tab_bar_drag}}' "
                              "{ set -u @tab_bar_drag } { send-keys -X copy-pipe-and-cancel }\n",
                              text)

    def test_ctrl_b_shift_arrows_carry_the_tab(self):
        text = self.conf()
        for key in ("Left", "Right", "Up", "Down"):
            with self.subTest(key=key):
                self.assertIn(f"bind -r S-{key} if-shell '[ -x \"$HOME/.local/bin/tmux-tab-bar\" ]'"
                              f" {{ run-shell '\"$HOME/.local/bin/tmux-tab-bar\" move "
                              f"{key.lower()} \"#{{client_name}}\" >/dev/null 2>&1; true' }}\n",
                              text)

    def test_the_right_click_menu_moves_instead_of_swapping(self):
        text = self.conf()
        block = text[text.index("bind -n MouseDown3Status"):]
        block = block[:block.index("\n\n")]
        for side, key, how in (("◀", "l", "left"), ("▶", "r", "right")):
            self.assertIn(f'"#{{?#{{>:#{{session_windows}},1}},,-}}Move {side}" {key} '
                          f'{{ run-shell \'"$HOME/.local/bin/tmux-tab-bar" move {how} '
                          f'"#{{client_name}}" "#{{window_id}}" >/dev/null 2>&1; true\' }}', block)
        self.assertNotIn("swap-window", block)
        self.assertNotIn("Swap", block)

    def test_the_restore_hook_is_silent_and_exits_0(self):
        self.assertIn("set-hook -g session-created[42] 'run-shell -b \"[ -x "
                      "$HOME/.local/bin/claude-restore ] && $HOME/.local/bin/claude-restore "
                      "--auto #{q:session_name} >/dev/null 2>&1; true\"'\n", self.conf())

    def test_the_enter_menu_moves_and_resets_behind_a_confirm(self):
        with open(os.path.join(REPO, "tmux", "base.conf")) as f:
            base = f.read()
        self.assertIn('"Move…"               m "run-shell \\"$HOME/.local/bin/tmux-tab-bar menu '
                      '#{client_name} >/dev/null 2>&1; true\\""', base)
        line = next(l for l in base.splitlines() if l.lstrip().startswith('"Reset bar"'))
        self.assertIn("confirm-before", line)
        self.assertIn("tmux-tab-bar reset #{client_name} >/dev/null 2>&1; true", line)

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

if args[0] == "set-option":            # a direct one (name-row unsets its input)
    ok = set_option(args)
    with open(path, "w") as f:
        json.dump(st, f)
    sys.exit(0 if ok else 1)
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
                       "pane_id": "%" + w[1:], "pane_title": "✳ [x] title", "@claude_star": ""}
                      for w, p in cwds.items()],
        })
        self.common = os.path.join(lead, ".git")

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

    def nav_state(self, current, nav=None, client="/dev/pts/7"):
        """Lay out, then give the fake one client on $0 at window `current`, whose
        #{@tab_bar_nav} (tmux resolves it from the client's session) is the session's, or `nav`."""
        self.run_layout()
        st = self.read_state()
        value = st["sessions"][0]["@tab_bar_nav"] if nav is None else nav
        st["clients"] = [{"session_id": "$0", "client_width": "188", "client_name": client,
                          "window_id": current, "@tab_bar_nav": value, "start_time": "1700",
                          "pid": "42", "socket_path": "/fake/sock"}]
        self.write_state(st)

    def run_nav(self, *args, **env):
        """nav's tmux calls after its read: [] when it selects nothing."""
        if os.path.exists(self.log):
            os.remove(self.log)
        p = subprocess.run([sys.executable, "-I", SCRIPT, "nav", *args], capture_output=True,
                           text=True, timeout=30, env={**self.env, **env})
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        return [c for c in self.calls() if c[0] != "list-clients"]

    def test_nav_selects_by_the_bars_layout(self):
        # Rows: dotclaude's lead @2 and lanes @3 @4, then the shared @1. G = 28 + 11.
        self.nav_state("@2")
        self.assertEqual(self.session()["@tab_bar_nav"],
                         "0;@2:39:32,@3:72:32,@4:105:32|1;@1:39:32")
        for direction, want in (("right", "@3"), ("down", "@1"), ("left", "@1"), ("up", "@1")):
            with self.subTest(direction=direction):
                self.assertEqual(self.run_nav(direction, "/dev/pts/7"),
                                 [["select-window", "-t", f"$0:{want}"]])
        self.nav_state("@4")
        self.assertEqual(self.run_nav("right", "/dev/pts/7"), [["select-window", "-t", "$0:@1"]])
        self.assertEqual(sum(c[0] == "list-clients" for c in self.calls()), 1)   # one read

    def test_nav_without_a_layout_steps_by_number(self):
        for nav in ("", "0;@2:39:32 ; kill-server", "#{E:x}"):
            with self.subTest(nav=nav):
                self.nav_state("@2", nav)
                self.assertEqual(self.run_nav("right", "/dev/pts/7"),
                                 [["next-window", "-t", "$0"]])
                self.assertEqual(self.run_nav("left", "/dev/pts/7"),
                                 [["previous-window", "-t", "$0"]])
                self.assertEqual(self.run_nav("up", "/dev/pts/7"), [])

    def test_nav_checks_its_words_and_says_nothing(self):
        self.nav_state("@2")
        for args in (("right", "/dev/pts/7;kill-server"), ("right", "-t"), ("right", ""),
                     ("sideways", "/dev/pts/7"), ("right",), ("right", "/dev/pts/7", "x"), ()):
            with self.subTest(args=args):
                self.assertEqual(self.run_nav(*args), [])
                self.assertEqual(self.calls(), [])          # not even the read
        self.assertEqual(self.run_nav("right", "/dev/pts/8"), [])   # no such client
        for wid in ("@2;x", "2", ""):                       # a window id that isn't one
            with self.subTest(wid=wid):
                self.nav_state(wid)
                self.assertEqual(self.run_nav("right", "/dev/pts/7"), [])
        env = {k: v for k, v in self.env.items() if k != "TMUX"}
        p = subprocess.run([sys.executable, "-I", SCRIPT, "nav", "right", "/dev/pts/7"],
                           capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_a_failing_tmux_leaves_nav_silent(self):
        self.nav_state("@2")
        self.assertEqual(self.run_nav("right", "/dev/pts/7", STUB_FAIL="list-clients"), [])
        with open(self.base + ".nav.err") as f:
            self.assertIn("list-clients", f.read())

    # --- arrange: rows @2 @3 @4 (dotclaude: lead, tab-bar, lane-close), then the shared @1 ---

    def run_cmd(self, *args, **env):
        """An arrange command; its tmux calls."""
        if os.path.exists(self.log):
            os.remove(self.log)
        p = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True,
                           text=True, timeout=30, env={**self.env, **env})
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertFalse(os.path.exists(self.base + ".move.err"),
                         open(self.base + ".move.err").read() if os.path.exists(
                             self.base + ".move.err") else "")
        return self.calls()

    def places(self):
        return {w["window_id"]: tb.parse_place(w["@tab_place"])
                for w in self.read_state()["windows"] if w.get("@tab_place")}

    def nav_rows(self):
        return [[t[0] for t in row] for row in tb.parse_nav(self.session()["@tab_bar_nav"])]

    def test_move_right_writes_the_row_then_lays_out(self):
        self.nav_state("@2")
        calls = self.run_cmd("move", "right", "/dev/pts/7")
        key = "p:" + self.common
        self.assertEqual(self.places(), {"@3": tb.Place(key, 0), "@2": tb.Place(key, 1),
                                         "@4": tb.Place(key, 2)})
        writes = [c for c in calls if c[0] == "set-option"]
        self.assertEqual([c[3] for c in writes[:3]], ["@3", "@2", "@4"])
        self.assertTrue(all(c[1:3] == ["-w", "-t"] and c[4] == "@tab_place" for c in writes[:3]))
        self.assertEqual(self.nav_rows(), [["@3", "@2", "@4"], ["@1"]])   # laid out at once
        self.nav_state("@2")
        self.assertEqual(self.run_cmd("move", "up", "/dev/pts/7"), [c for c in self.calls()
                                                                    if c[0].startswith("list-")])

    def test_move_down_auto_and_reset(self):
        self.nav_state("@3")
        self.run_cmd("move", "down", "/dev/pts/7")      # before @1, the tab under it
        self.assertEqual(self.nav_rows(), [["@2", "@4"], ["@3", "@1"]])
        names = {w["window_id"]: w.get("@tab_name") for w in self.read_state()["windows"]}
        self.assertEqual(names["@3"], "dotclaude·tab-bar")
        self.nav_state("@3")
        self.run_cmd("move", "auto", "/dev/pts/7", "@3")
        self.assertNotIn("@3", self.places())
        self.assertEqual(self.nav_rows(), [["@2", "@3", "@4"], ["@1"]])
        self.assertEqual(self.places(), {"@1": tb.Place("s", 1)})   # the shared row stays manual
        self.nav_state("@2")
        self.run_cmd("reset", "/dev/pts/7")
        self.assertEqual(self.places(), {})

    def test_newrow_makes_a_custom_row_below_and_name_row_names_it(self):
        self.nav_state("@3")
        self.run_cmd("move", "newrow", "/dev/pts/7")
        key = "p:" + self.common
        self.assertEqual(self.places(), {"@3": tb.Place("c:1", 0, key)})
        self.assertEqual(self.nav_rows(), [["@2", "@4"], ["@3"], ["@1"]])
        window = {w["window_id"]: w for w in self.read_state()["windows"]}
        self.assertEqual(window["@3"].get("@tab_row_custom"), "1")
        self.assertNotIn("@tab_row_custom", window["@2"])
        st = self.read_state()
        hostile = "a\"b'c;d#[e%f$(g)$HOME~h\\i"
        for w in st["windows"]:
            if w["window_id"] == "@3":
                w["@tab_row_name_in"] = hostile
        self.write_state(st)
        self.nav_state("@3")
        self.run_cmd("name-row", "/dev/pts/7")
        self.assertEqual(self.places()["@3"].name, tb.clean_row_name(hostile))
        self.assertNotIn("@tab_row_name_in", self.read_state()["windows"][2])
        self.assertEqual(self.session()["@tab_bar_g1"], tb.clean_row_name(hostile))
        self.nav_state("@2")                            # not in a custom row: no name
        self.run_cmd("name-row", "/dev/pts/7")
        self.assertNotIn("@2", self.places())

    def test_drop_by_the_half_of_the_slot_and_drop_row_by_the_end(self):
        self.nav_state("@2")                             # row 0: @2 at 39, @3 at 72, @4 at 105
        self.run_cmd("drop", "@4", "@2", "40", "0", "window", "/dev/pts/7")
        self.assertEqual(self.nav_rows(), [["@4", "@2", "@3"], ["@1"]])
        self.nav_state("@2")
        self.run_cmd("drop", "@4", "@3", "121", "0", "window", "/dev/pts/7")   # @3 at 105
        self.assertEqual(self.nav_rows(), [["@2", "@3", "@4"], ["@1"]])
        for args in (("@4", "@3", "100", "0", "more"), ("@3", "@3", "80", "0", "window"),
                     ("@9", "@3", "80", "0", "window"), ("@4", "@3", "x", "0", "window")):
            with self.subTest(args=args):
                self.nav_state("@2")
                calls = self.run_cmd("drop", *args, "/dev/pts/7")
                self.assertNotIn("source-file", [c[0] for c in calls])
        self.nav_state("@2")
        self.run_cmd("drop-row", "@1", "3", "0", "/dev/pts/7")      # the gutter: first
        self.assertEqual(self.nav_rows()[0], ["@1", "@2", "@3", "@4"])
        self.nav_state("@2")
        self.assertNotIn("source-file", [c[0] for c in self.run_cmd(
            "drop-row", "@1", "3", "4", "/dev/pts/7")])              # a line with no tabs

    def test_the_menu_shows_moves_for_a_checked_client_and_window(self):
        self.nav_state("@2")
        self.run_cmd("menu", "/dev/pts/7")
        deadline = time.time() + 10                     # display-menu runs detached
        while time.time() < deadline and "display-menu" not in [c[0] for c in self.calls()]:
            time.sleep(0.05)
        menu = next(c for c in self.calls() if c[0] == "display-menu")
        self.assertEqual(menu[:10], ["display-menu", "-c", "/dev/pts/7", "-t", "@2", "-x", "C",
                                     "-y", tb.OVERLAY_Y_CENTRE, "-T"])
        self.assertNotIn("-O", menu)
        items = menu[11:]
        self.assertIn("◀ Left", items)
        cmd = items[items.index("Auto place") + 2]
        self.assertEqual(tmux_words(cmd), [["run-shell", '"$HOME/.local/bin/tmux-tab-bar" move '
                                            'auto /dev/pts/7 @2 --menu >/dev/null 2>&1; true']])
        # Name row…: the tap menu's verified prompt (a quoted template with %%%), aimed at the
        # window, and not reopening the menu.
        k = items.index("#{?@tab_row_custom,,-}Name row…")
        self.assertEqual(items[k + 1:k + 3], [
            "N", 'command-prompt -p "row name:" "set -w -t @2 @tab_row_name_in \\"%%%\\" ; '
                 'run-shell \'\\"$HOME/.local/bin/tmux-tab-bar\\" name-row /dev/pts/7 @2 '
                 '>/dev/null 2>&1; true\'"'])
        for args in (("menu", "/dev/pts/7;x"), ("menu", "/dev/pts/7", "@9"),
                     ("move", "sideways", "/dev/pts/7"), ("reset",), ("name-row",),
                     ("drop-row", "@1", "3", "0")):
            with self.subTest(args=args):
                calls = self.run_cmd(*args)
                self.assertFalse([c for c in calls if c[0] in ("source-file", "display-menu")])

    def test_a_move_updates_only_this_servers_records_of_the_window(self):
        state_home = os.path.join(self.tmp, "state")
        reg = os.path.join(state_home, "dotclaude", "open-sessions")
        os.makedirs(reg)
        base = {"cwd": "/x", "socket": "/fake/sock", "server_start": 1700, "server_pid": 42}
        recs = {"mine": dict(base, session_id="a" * 8, pane="%2"),
                "other-server": dict(base, session_id="b" * 8, pane="%2", server_pid=43),
                "other-pane": dict(base, session_id="c" * 8, pane="%9", place="keep")}
        for name, rec in recs.items():
            with open(os.path.join(reg, name + ".json"), "w") as f:
                json.dump(rec, f)
        with open(os.path.join(reg, "bad.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(reg, "big.json"), "w") as f:
            json.dump(dict(base, pane="%2", pad="x" * tb.RECORD_MAX), f)
        before = {n: open(os.path.join(reg, n)).read() for n in os.listdir(reg)}
        self.nav_state("@2")
        self.run_cmd("move", "right", "/dev/pts/7", XDG_STATE_HOME=state_home)
        with open(os.path.join(reg, "mine.json")) as f:
            mine = json.load(f)
        self.assertEqual(tb.parse_place(mine["place"]), tb.Place("p:" + self.common, 1))
        self.assertEqual({k: v for k, v in mine.items() if k != "place"}, recs["mine"])
        after = {n: open(os.path.join(reg, n)).read() for n in os.listdir(reg)
                 if n != tb.RECORDS_LOCK}
        self.assertEqual(set(after), set(before))       # none created, no temp file left
        for n in before:
            if n != "mine.json":
                self.assertEqual(after[n], before[n], n)
        self.nav_state("@2")
        self.run_cmd("move", "auto", "/dev/pts/7", XDG_STATE_HOME=state_home)
        with open(os.path.join(reg, "mine.json")) as f:
            self.assertNotIn("place", json.load(f))

    def test_a_record_deleted_before_the_replace_is_never_brought_back(self):
        # The registry deletes a record (under the records lock) after the update read it: the
        # update's compare and replace wait for the lock, then see it gone.
        reg = os.path.join(self.tmp, "reg")
        os.makedirs(reg)
        path = os.path.join(reg, "a.json")
        with open(path, "w") as f:
            json.dump({"socket": "/fake/sock", "server_start": 1700, "server_pid": 42,
                       "pane": "%2"}, f)
        fd = os.open(os.path.join(reg, tb.RECORDS_LOCK), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(lambda: os.close(fd))
        fcntl.flock(fd, fcntl.LOCK_EX)
        update = threading.Thread(target=tb.update_record,
                                  args=(path, ("/fake/sock", 1700, 42), {"%2": '{"x":1}'}))
        update.start()
        deadline = time.time() + 5                      # its temp file: it is at the lock
        while time.time() < deadline and not any(n.startswith(".tmp-") for n in os.listdir(reg)):
            time.sleep(0.01)
        os.remove(path)
        fcntl.flock(fd, fcntl.LOCK_UN)
        update.join(10)
        self.assertEqual(os.listdir(reg), [tb.RECORDS_LOCK])   # not recreated, no temp left

    def test_a_record_update_goes_ahead_past_the_lock_bound(self):
        reg = os.path.join(self.tmp, "reg")
        os.makedirs(reg)
        path = os.path.join(reg, "a.json")
        with open(path, "w") as f:
            json.dump({"socket": "/s", "server_start": 1, "server_pid": 2, "pane": "%2"}, f)
        fd = os.open(os.path.join(reg, tb.RECORDS_LOCK), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(lambda: os.close(fd))
        fcntl.flock(fd, fcntl.LOCK_EX)
        with unittest.mock.patch.object(tb, "LOCK_WAIT", 0.2):
            tb.update_record(path, ("/s", 1, 2), {"%2": "p"})
        with open(path) as f:
            self.assertEqual(json.load(f)["place"], "p")

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

    def test_a_move_waits_for_a_layout_in_flight_and_lays_out_before_returning(self):
        # A hook's layout holds the lock briefly: the move waits for it, so the next queued move
        # reads the bar this one drew (it used to mark the state dirty and return).
        self.nav_state("@2")
        fd = os.open(self.base + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        timer = threading.Timer(0.5, os.close, (fd,))
        timer.start()
        self.addCleanup(timer.join)
        start = time.monotonic()
        self.run_cmd("move", "right", "/dev/pts/7")
        self.assertGreaterEqual(time.monotonic() - start, 0.4)
        self.assertEqual(self.nav_rows(), [["@3", "@2", "@4"], ["@1"]])
        self.assertFalse(os.path.exists(self.base + ".dirty"))

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

    def test_a_raising_pass_still_looks_for_a_mark_after_letting_go(self):
        # A run that left while the holder's pass was failing counts on the holder's look:
        # the error ends the hold, the look still finds the mark and lays out again, and the
        # first error then reaches main's catch-all.
        calls = []

        def run():
            calls.append(1)
            if len(calls) == 1:
                tb.touch(self.base + ".dirty")     # a hook fired, found the lock held, left
                raise RuntimeError("first")

        with self.assertRaisesRegex(RuntimeError, "first"):
            tb.run_locked(self.base, run)
        self.assertEqual(len(calls), 2)
        self.assertFalse(os.path.exists(self.base + ".dirty"))
        fd = os.open(self.base + ".lock", os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # let go: nothing still holds it

    def test_a_raising_pass_with_no_mark_runs_once_and_raises(self):
        calls = []

        def run():
            calls.append(1)
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            tb.run_locked(self.base, run)
        self.assertEqual(len(calls), 1)

    def test_a_wait_runs_once_the_lock_is_free_or_without_it_past_the_bound(self):
        fd = os.open(self.base + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(lambda: os.close(fd) if fd is not None else None)
        fcntl.flock(fd, fcntl.LOCK_EX)
        calls = []
        tb.run_locked(self.base, lambda: calls.append(1))           # a hook: marks and leaves
        self.assertEqual(calls, [])
        start = time.monotonic()
        tb.run_locked(self.base, lambda: calls.append(1), wait=0.3)  # still held: runs anyway
        self.assertEqual(calls, [1])
        self.assertGreaterEqual(time.monotonic() - start, 0.25)
        timer = threading.Timer(0.2, fcntl.flock, (fd, fcntl.LOCK_UN))
        timer.start()
        self.addCleanup(timer.join)
        tb.run_locked(self.base, lambda: calls.append(1), wait=5)     # freed: runs under it
        self.assertEqual(calls, [1, 1])
        self.assertFalse(os.path.exists(self.base + ".dirty"))

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
        self.settle()
        errs = [n for n in os.listdir(self.tmp) if n.endswith(".err")]
        self.assertEqual(errs, [], [open(os.path.join(self.tmp, n)).read() for n in errs])

    def settle(self, timeout=10.0):
        """Wait until no layout is in flight. A hook's run (a resize, a window selected) can hold
        the lock when the test's run starts; that run then only marks the state dirty and
        leaves, and the holder lays out again. Done = the lock is free and no mark is left. A
        mark found with the lock free (a hook that met this probe's own brief hold) gets a run
        of its own, since no holder will see it."""
        base = os.path.join(self.tmp, f".tmux-tab-bar.{os.getuid()}."
                                      f"{tb.server_key(self.layout_env['TMUX'])}")
        deadline = time.time() + timeout
        while time.time() < deadline:
            fd = os.open(base + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                free = True
            except OSError:
                free = False
            finally:
                os.close(fd)            # closing drops the lock
            if free and not os.path.exists(base + ".dirty"):
                return
            if free:
                subprocess.run([sys.executable, "-I", SCRIPT, "layout"], capture_output=True,
                               timeout=30, env=self.layout_env)
            else:
                time.sleep(0.02)
        self.fail("a layout was still in flight")

    def show(self, *args):
        return self.ti("show-options", *args).stdout

    def current(self):
        # "t:", never a bare "t": tmux tries a bare name as a window first, and under load
        # window 0 can be named "tmux" (automatic-rename sees the pane before its exec, then the
        # conf turns renaming off), so "t" read window 0 whatever was current.
        return self.ti("display", "-p", "-t", "t:", "#{window_index}").stdout.strip()

    # --- tests ---

    def test_every_row_is_written_and_a_rerun_changes_nothing(self):
        self.run_layout()
        self.assertEqual(self.show("-v", "-t", "t:", "status").strip(), "2")
        for i in range(2):
            row = self.show("-v", "-t", "t:", f"status-format[{i}]")
            self.assertTrue(row.startswith("#[fill=colour236]"), (i, row[:80]))
        names = self.ti("list-windows", "-t", "t:", "-F", "#{window_index} #{@tab_name}").stdout
        self.assertEqual(sorted(names.split("\n")[:-1]), ["0 lead", "1 tab-bar", "2 hq:"])
        before = (self.show("-t", "t:"), self.show("-w", "-t", "t:0"), self.show("-w", "-t", "t:2"))
        self.run_layout()
        after = (self.show("-t", "t:"), self.show("-w", "-t", "t:0"), self.show("-w", "-t", "t:2"))
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
        # Both forms in each place, swapped between rounds: `repo · ` now, and `[repo] `, which a
        # session that hasn't had a prompt since session-title.sh changed still carries.
        rounds = (("✳ [dotclaude] alpha one", "⠂ tab-bar · beta one", "[hq] gamma one"),
                  ("✳ dotclaude · alpha two", "⠂ [tab-bar] beta two", "hq · gamma two"))
        for n, titles in zip(("one", "two"), rounds):
            with self.subTest(round=n):
                for i, title in enumerate(titles + ("no prefix " + n,)):
                    self.ti("select-pane", "-t", f"t:{i}", "-T", title)
                for text in (f"lead alpha {n}", f"tab-bar beta {n}", f"hq: gamma {n}",
                             f"hq: no prefix {n}"):
                    self.find(text)
                bar = "\n".join(self.screen()[:2])
                for gone in ("✳", "⠂", "[dotclaude]", "[tab-bar]", "[hq]", "dotclaude ·",
                             "tab-bar ·", "hq ·"):
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

    def test_a_huge_osc_title_expands_fast(self):
        # A pane can set a title of any length with OSC 2 (select-pane -T that long hits
        # ARG_MAX). s/// is quadratic in its input: uncut, a 160k title took 98 ms to expand.
        # `=` skips a #[...] style and counts ## as one cell, so the cut can't be #{=/N:...}:
        # the second and third titles passed that whole (88 ms for the ## one).
        titles = ("x" * 160000, "#[" + "##" * 80000 + "]", "#[" + "x" * 160000 + "]")
        for i, title in enumerate(titles):
            with self.subTest(title=title[:6]):
                path = os.path.join(self.tmp, f"title{i}")
                with open(path, "w") as f:
                    f.write(title)
                win = f"t:{3 + i}"
                self.ti("new-window", "-d", "-t", win, "-c", self.plain,
                        f"printf '\\033]2;%s\\033\\\\' \"$(cat {path})\"; sleep 600")
                self.wait(lambda: len(self.ti("display", "-p", "-t", win,
                                              "#{pane_title}").stdout) > 150000,
                          "the OSC 2 title never arrived")
                times = []
                for _ in range(5):
                    start = time.perf_counter()
                    got = self.ti("display", "-p", "-t", win, tb.BODY).stdout.rstrip("\n")
                    times.append(time.perf_counter() - start)
                self.assertLessEqual(len(got), tb.LABEL_CAP + 16, got[:80])
                self.assertLess(min(times), 0.020, times)

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
        self.find("Move ◀")

    def test_a_busy_pane_behind_the_tap_menu_leaves_the_menu_whole(self):
        # The pane behind redraws whole every frame under synchronized output, as Claude Code
        # does. Before the menus opened at row 0, it painted over the menu's first row.
        self.run_layout()
        x, y = self.find("alpha-title")
        writer = os.path.join(self.tmp, "writer.py")
        with open(writer, "w") as f:
            f.write("import sys, time\n"
                    "for n in range(100000):\n"
                    "    sys.stdout.write('\\x1b[?2026h' + ''.join("
                    "'\\x1b[%d;1H\\x1b[2K\\x1b[41m row %d frame %d \\x1b[0m' % (r, r, n)"
                    " for r in range(1, 14)) + '\\x1b[?2026l')\n"
                    "    sys.stdout.flush()\n"
                    "    time.sleep(0.05)\n")
        replies = os.path.join(self.home, ".local", "bin", "pass-last")
        os.makedirs(os.path.dirname(replies), exist_ok=True)
        with open(replies, "w") as f:
            f.write("#!/bin/sh\necho replies-probe\nexec sleep 30\n")
        os.chmod(replies, 0o755)
        self.ti("respawn-pane", "-k", "-t", "t:0", f"{sys.executable} -I {writer}")
        self.wait(lambda: any("frame" in line for line in self.screen()), "the writer never drew")
        self.click(x, y)                                    # the current tab: its menu
        self.find("Replies before pass")
        time.sleep(1.5)                                     # about 30 frames behind it
        screen = self.screen()
        self.assertTrue(screen[0].count("┌"), screen[:3])  # its top edge on row 0
        for item in ("Star", "Shelve", "Shelf…", "Replies before pass", "Windows…"):
            self.assertTrue(any(item in line for line in screen), (item, screen[:14]))
        wx, wy = self.find("Replies before pass")
        self.click(wx + 1, wy)                              # a popup from inside a menu item
        self.find("replies-probe")
        time.sleep(1.5)
        screen = self.screen()
        self.assertIn("replies before the pass", screen[0])  # row 0, title kept
        self.assertTrue(any("replies-probe" in line for line in screen[1:3]), screen[:3])

    def drag(self, start, end, button=0):
        """An SGR press at start, motion (button 32) to end, release at end: (x, y) cells."""
        self.to("send-keys", "-t", "o", "-l", f"\x1b[<{button};{start[0]};{start[1]}M")
        self.to("send-keys", "-t", "o", "-l", f"\x1b[<{button + 32};{end[0]};{end[1]}M")
        self.to("send-keys", "-t", "o", "-l", f"\x1b[<{button};{end[0]};{end[1]}m")

    def test_a_drag_across_rows_reorders_and_a_drag_onto_the_pane_cancels(self):
        self.link_script()
        self.run_layout()
        self.assertEqual(self.nav_rows(), [["0", "1"], ["2"]])
        self.drag(self.find("gamma-title"), self.find("alpha-title"))    # hq before the lead
        self.wait(lambda: self.nav_rows() == [["2", "0", "1"]], f"rows {self.nav_rows()}")
        self.assertEqual(self.show("-qv", "-t", "t:", "@tab_bar_drag").strip(), "")
        rows = self.nav_rows()
        self.drag(self.find("beta-title"), (40, 30))                      # onto the pane
        time.sleep(1)
        self.assertEqual(self.nav_rows(), rows)
        modes = self.ti("list-panes", "-a", "-F", "#{pane_in_mode}").stdout.split()
        self.assertEqual(set(modes), {"0"})
        self.assertEqual(self.show("-qv", "-t", "t:", "@tab_bar_drag").strip(), "")

    # Each tmux default claude.conf wraps (table, key), and the keys it binds that have none.
    WRAPPED = (("copy-mode", "MouseDown1Pane"), ("copy-mode", "MouseDrag1Pane"),
               ("copy-mode", "MouseDragEnd1Pane"), ("copy-mode-vi", "MouseDown1Pane"),
               ("copy-mode-vi", "MouseDrag1Pane"), ("copy-mode-vi", "MouseDragEnd1Pane"),
               ("root", "MouseDown1Pane"), ("root", "MouseDown1Border"),
               ("root", "MouseDrag1Pane"), ("root", "MouseDrag1Border"))
    UNBOUND = (("root", "MouseDown1StatusDefault"), ("root", "MouseDown1StatusLeft"),
               ("root", "MouseDown1StatusRight"), ("root", "MouseDragEnd1Border"),
               ("root", "MouseDragEnd1Pane"))

    def keys(self, sock):
        """{(table, key): command} from a server's full list-keys (a single key's listing
        prints nothing in 3.7c), each command with its ; separators spelled alike: list-keys
        writes `\\;` between top-level commands and `;` inside braces."""
        out = {}
        for line in self.tmux(sock, ["list-keys"]).stdout.splitlines():
            m = re.match(r"bind-key\s+(?:-r\s+)?-T\s+(\S+)\s+(\S+)\s+(.*)$", line)
            if m:
                out[m.group(1), m.group(2)] = re.sub(r"\s*(?:\\?;)+\s*", " ; ", m.group(3))
        return out

    def test_every_wrapped_tmux_default_is_kept_whole_inside_its_guard(self):
        # A tmux upgrade that changes one of these defaults fails here, not silently in a pane.
        bare = os.path.join(self.tmp, "bare")
        self.tmux(bare, ["-f", "/dev/null", "new-session", "-d", "-s", "b", "sleep 600"])
        self.addCleanup(self.tmux, bare, ["kill-server"], False)
        defaults, ours = self.keys(bare), self.keys(self.sock)
        for key in self.WRAPPED:
            with self.subTest(key=key):
                self.assertIn(key, defaults)
                self.assertIn(defaults[key], ours[key])
        for key in self.UNBOUND:
            with self.subTest(key=key):
                self.assertNotIn(key, defaults)
                self.assertIn("@tab_bar_drag", ours[key])

    def test_a_tab_dragged_onto_a_pane_in_copy_mode_copies_nothing(self):
        self.link_script()
        self.ti("respawn-pane", "-k", "-t", "t:0", "printf 'one two three four\\n'; sleep 600")
        self.run_layout()
        self.find("one two three four")
        self.ti("copy-mode", "-t", "t:0")
        self.drag(self.find("beta-title"), (40, 30))                      # a tab onto the pane
        time.sleep(1)
        self.assertEqual(self.ti("list-buffers").stdout, "")
        self.assertEqual(self.show("-qv", "-t", "t:", "@tab_bar_drag").strip(), "")
        self.assertEqual(self.nav_rows(), [["0", "1"], ["2"]])
        x, y = self.find("one two three four")                            # a plain drag copies
        self.drag((x, y), (x + 6, y))
        self.wait(lambda: self.ti("list-buffers").stdout != "", "the copy-mode drag copied nothing")

    def plus_n(self):
        """Enough shared windows on a 100-cell client for the bar to end in +N: its (x, y)."""
        self.link_script()
        self.ti("source-file", "-", stdin="".join(
            f"new-window -d -t t:{i} -c {self.plain} 'sleep 600'\n" for i in range(3, 30)))
        self.to("resize-window", "-t", "o", "-x", "100")
        self.wait(lambda: self.ti("list-clients", "-F", "#{client_width}").stdout.strip() == "100",
                  "the client never shrank to 100")
        self.run_layout()
        found = []

        def look():
            for y, line in enumerate(self.screen()[:tb.MAX_ROWS]):
                m = re.search(r" \+\d+ ", line)
                if m:
                    found.append((m.start() + 2, y + 1))
                    return True
            return False

        self.wait(look, f"no +N drawn: {self.screen()[:6]}")
        return found[0]

    def test_a_jittery_tap_on_plus_n_opens_the_window_list(self):
        x, y = self.plus_n()
        self.drag((x, y), (x + 1, y))
        self.wait(lambda: self.ti("display", "-p", "-t", "t:", "#{pane_mode}").stdout.strip()
                  == "tree-mode", "a jittery tap on +N did not open the window list")
        self.assertEqual(self.show("-qv", "-t", "t:", "@tab_bar_drag").strip(), "")

    def test_a_drag_from_plus_n_onto_a_tab_moves_nothing(self):
        x, y = self.plus_n()
        rows = self.nav_rows()
        self.drag((x, y), self.find("alpha-title"))
        time.sleep(1)
        self.assertEqual(self.nav_rows(), rows)
        self.assertEqual(self.ti("show-options", "-wqv", "-t", "t:0", "@tab_place").stdout, "")
        self.assertEqual(self.show("-qv", "-t", "t:", "@tab_bar_drag").strip(), "")

    def test_a_stuck_flag_cleared_by_a_gutter_press_moves_nothing(self):
        # A release tmux never reported left the flag on a tab; a drag from the gutter onto a
        # tab must not drop that tab.
        self.link_script()
        self.run_layout()
        rows = self.nav_rows()
        wid = self.ti("display", "-p", "-t", "t:2", "#{window_id}").stdout.strip()
        self.ti("set-option", "-t", "t:", "@tab_bar_drag", wid)
        _, y = self.find("alpha-title")
        self.drag((2, y + 1), self.find("alpha-title"))                   # row 2's gutter
        time.sleep(1)
        self.assertEqual(self.nav_rows(), rows)
        self.assertEqual(self.show("-qv", "-t", "t:", "@tab_bar_drag").strip(), "")

    def test_ctrl_b_shift_right_carries_the_tab(self):
        self.link_script()
        self.run_layout()
        self.assertEqual(self.nav_rows(), [["0", "1"], ["2"]])
        self.to("send-keys", "-t", "o", "C-b")
        self.to("send-keys", "-t", "o", "S-Right")
        self.wait(lambda: self.nav_rows() == [["1", "0"], ["2"]], f"rows {self.nav_rows()}")
        self.assertEqual(self.current(), "0")

    def test_the_name_prompt_stores_a_hostile_name_literally_and_draws_it_cleaned(self):
        self.link_script()
        self.run_layout()
        self.ti("set-option", "-w", "-t", "t:1", "@tab_place",
                tb.place_text(tb.Place("c:1", 0, "s")))
        self.ti("select-window", "-t", "t:1")
        self.run_layout()
        x, y = self.find("beta-title")
        self.click(x, y)                                # the current tab: its menu
        nx, ny = self.find("Name row…")
        self.click(nx + 1, ny)
        self.find("row name:")
        hostile = "a\"b'c;d#[e%f$(g)$HOME~h\\i"
        self.to("send-keys", "-t", "o", "-l", hostile)
        self.to("send-keys", "-t", "o", "Enter")
        want = tb.clean_row_name(hostile)
        self.wait(lambda: (tb.parse_place(self.ti("show-options", "-wv", "-t", "t:1",
                                                    "@tab_place").stdout.rstrip("\n"))
                           or tb.Place("s", 0)).name == want, "the row was never named")
        self.find(want + "▸")
        self.assertEqual(self.ti("show-options", "-wqv", "-t", "t:1",
                                 "@tab_row_name_in").stdout, "")

    def test_the_move_menus_name_row_stores_a_hostile_name_literally(self):
        # The Move menu opened by the script itself, with no script in HOME yet: the prompt's
        # run-shell finds nothing, so the typed text stays in @tab_row_name_in to be read.
        self.run_layout()
        self.ti("set-option", "-w", "-t", "t:1", "@tab_place",
                tb.place_text(tb.Place("c:1", 0, "s")))
        self.run_layout()
        wid = self.ti("display", "-p", "-t", "t:1", "#{window_id}").stdout.strip()
        client = self.ti("list-clients", "-F", "#{client_name}").stdout.strip()
        p = subprocess.run([sys.executable, "-I", SCRIPT, "menu", client, wid],
                           capture_output=True, text=True, timeout=30, env=self.layout_env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.find("New row")
        nx, ny = self.find("Name row…")
        self.click(nx + 1, ny)
        self.find("row name:")
        hostile = "a\"b'c;d#[e%f$(g)$HOME~h\\i"
        self.to("send-keys", "-t", "o", "-l", hostile)
        self.to("send-keys", "-t", "o", "Enter")
        self.wait(lambda: self.ti("show-options", "-wqv", "-t", "t:1",
                                  "@tab_row_name_in").stdout == hostile + "\n",
                  "the typed name was not stored literally")
        self.link_script()
        p = subprocess.run([sys.executable, "-I", SCRIPT, "name-row", client, wid],
                           capture_output=True, text=True, timeout=30, env=self.layout_env)
        self.settle()
        self.find(tb.clean_row_name(hostile) + "▸")
        self.assertEqual(self.ti("show-options", "-wqv", "-t", "t:1",
                                 "@tab_row_name_in").stdout, "")

    def link_script(self):
        """Put tmux-tab-bar where the conf's hooks and keys look for it."""
        bin_dir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bin_dir, exist_ok=True)
        os.symlink(SCRIPT, os.path.join(bin_dir, "tmux-tab-bar"))

    def add_second_laned_repo(self):
        """Window 3 in another laned repo's lead: rows [0 1] [3] [2] (two groups, then hq)."""
        lead = make_repo(os.path.dirname(self.plain), "karaoke", lanes=["k1"])
        self.ti("new-window", "-d", "-t", "t:3", "-c", lead, "sleep 600")

    def press(self, key, want):
        self.to("send-keys", "-t", "o", key)        # the outer pane passes it to the client
        self.wait(lambda: self.current() == want,
                  f"{key} did not go to window {want} (at {self.current()})")

    def nav_rows(self):
        ids = dict(line.split() for line in self.ti(
            "list-windows", "-t", "t:", "-F", "#{window_id} #{window_index}").stdout.split("\n")
            if line)
        rows = tb.parse_nav(self.show("-v", "-t", "t:", "@tab_bar_nav").strip())
        return [[ids[t[0]] for t in row] for row in rows]

    def test_shift_arrows_follow_the_bars_layout(self):
        self.link_script()
        self.add_second_laned_repo()
        self.run_layout()
        self.assertEqual(self.nav_rows(), [["0", "1"], ["3"], ["2"]])
        ys = [self.find(text)[1] for text in ("0 lead", "3 lead", "2 hq:")]
        self.assertEqual(ys, [1, 2, 3])
        self.assertEqual(self.current(), "0")
        # Down from the lane (row 0's second tab) finds no tab under it: the nearest. Up from
        # row 0 wraps to the bottom row; up from the bottom row goes to row 1, not row 0.
        for key, want in (("S-Right", "1"), ("S-Down", "3"), ("S-Left", "1"), ("S-Up", "2"),
                          ("S-Up", "3"), ("S-Right", "2"), ("S-Right", "0")):
            self.press(key, want)
        self.run_layout()                       # and the keys left no error behind

    def test_rapid_shift_arrows_each_take_a_step(self):
        # Key repeat or quick presses: each nav must see the window the one before it chose.
        self.link_script()
        self.add_second_laned_repo()
        self.run_layout()
        self.to("send-keys", "-t", "o", "S-Right", "S-Right", "S-Right")
        self.wait(lambda: self.current() == "2", f"three S-Right ended at {self.current()}")
        time.sleep(0.5)
        self.assertEqual(self.current(), "2")

    def test_shift_up_goes_to_the_row_above_on_the_phone_too(self):
        # The phone's bar is at the bottom, but tmux still draws row 0 on top.
        self.link_script()
        self.add_second_laned_repo()
        self.to("resize-window", "-t", "o", "-x", "45")
        self.wait(lambda: self.ti("list-clients", "-F", "#{client_width}").stdout.strip() == "45",
                  "the client never shrank to 45")
        self.run_layout()
        self.assertEqual(self.show("-v", "-t", "t:", "status-position").strip(), "bottom")
        self.assertEqual(self.nav_rows(), [["0", "1"], ["3"], ["2"]])
        ys = [self.find(text)[1] for text in ("0 lead", "3 lead", "2 hq:")]
        self.assertEqual(ys, [44, 45, 46])
        self.ti("select-window", "-t", "t:2")
        for key, want in (("S-Up", "3"), ("S-Up", "0"), ("S-Down", "3"), ("S-Down", "2")):
            self.press(key, want)
        self.run_layout()

    def test_without_the_script_shift_left_right_step_by_number_and_up_down_do_nothing(self):
        self.add_second_laned_repo()
        for key, want in (("S-Right", "1"), ("S-Right", "2"), ("S-Left", "1")):
            self.press(key, want)
        for key in ("S-Up", "S-Down"):
            self.to("send-keys", "-t", "o", key)
        time.sleep(0.5)
        self.assertEqual(self.current(), "1")
        modes = self.ti("list-panes", "-a", "-F", "#{pane_in_mode}").stdout.split()
        self.assertEqual(set(modes), {"0"})

    def test_no_hook_puts_a_pane_in_view_mode(self):
        # HOME has no tmux-tab-bar: every hook's command must still exit 0 and print nothing.
        self.ti("new-window", "-t", "t:", "-c", self.plain, "sleep 600")
        self.ti("select-window", "-t", "t:0")
        deadline = time.time() + 2
        while time.time() < deadline:
            modes = self.ti("list-panes", "-a", "-F", "#{pane_in_mode}").stdout.split()
            self.assertEqual(set(modes), {"0"})
            time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
