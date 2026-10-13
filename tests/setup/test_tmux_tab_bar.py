"""tmux/tmux-tab-bar: the grouped multi-row tab bar (stdlib only).

The pure parts (classify, group_windows, lay_out, render) run in-process. `layout` runs as a
subprocess against a fake tmux (a stateful Python stub that answers the list commands from a
JSON file and applies set-option to it), and against a real tmux server on a private socket,
which the Bash sandbox blocks: that class skips there."""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import pty
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest

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
               " #{}[]=,:;|/@?^()\\*+-_.!…◐✳★▸│")

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
    def check_fits(self, lay, width, left=28, right=16):
        """Every row's headers, slots and +N fit its width; slots respect the cap."""
        for r, (row, slot) in enumerate(zip(lay.rows, lay.slots)):
            avail = width - ((lay.left + lay.right) if r == 0 else 0)
            fixed = sum(lay.head_w[i[1]] if i[0] in ("head", "div") else i[2]
                        for i in row if i[0] != "tab")
            n = len(tab_ids(row))
            self.assertLessEqual(fixed + n * slot, avail, (r, row))
            self.assertLessEqual(slot, tb.MAX_SLOT)
            self.assertLessEqual(n, tb.max_tabs_per_row())

    def test_one_laned_group_and_a_shared_row(self):
        lay = tb.lay_out([Group("dotclaude", tabs(2, 3))], tabs(1, 4), 188, "@1", 28, 16)
        self.assertEqual(lay.rows, [[("head", 0, False), ("tab", "@2", 2), ("tab", "@3", 3)],
                                    [("tab", "@1", 1), ("tab", "@4", 4)]])
        self.assertEqual(lay.slots, [48, 48])       # (144 - 11) // 2 and 188 // 2, capped
        self.assertEqual((lay.phone, lay.hidden, lay.heads), (False, 0, ["dotclaude"]))
        self.check_fits(lay, 188)

    def test_the_live_shape_on_the_desktop(self):
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 28, 16)
        self.assertEqual([tab_ids(r) for r in lay.rows],
                         [["@4", "@6", "@7", "@8"], ["@1", "@2", "@3", "@5", "@9"]])
        self.assertEqual(lay.slots, [33, 37])
        self.check_fits(lay, 188)

    def test_the_live_shape_on_the_phone(self):
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 45, "@4", 28, 16)
        self.assertTrue(lay.phone)
        self.assertEqual(lay.heads, ["dot"])
        self.assertEqual(lay.rows[1][0], ("head", 0, True))     # the overflow header, dimmed
        self.assertEqual([tab_ids(r) for r in lay.rows],
                         [["@4", "@6", "@7"], ["@8"], ["@1", "@2", "@3", "@5", "@9"]])
        self.assertEqual((lay.left, lay.right), (tb.PHONE_LEFT, 0))
        self.assertTrue(all(s >= tb.MIN_SLOT_PHONE for s in lay.slots))
        self.check_fits(lay, 45)

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
        groups = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 9))) for k in range(6)]
        for current in ("@1", "@58"):
            with self.subTest(current=current):
                lay = tb.lay_out(groups, [], 188, current, 28, 16)
                self.assertEqual(len(lay.rows), tb.MAX_ROWS)
                last = lay.rows[-1][-1]
                self.assertEqual(last[0], "more")
                self.assertEqual(last[1], lay.hidden)
                shown = [w for row in lay.rows for w in tab_ids(row)]
                self.assertEqual(len(shown) + lay.hidden, 48)
                self.assertIn(current, shown)
                self.assertEqual(len(set(shown)), len(shown))
                # Packing these saves no row, so none is packed: every row keeps its header.
                self.assertTrue(all(row[0][0] == "head" for row in lay.rows))
                self.check_fits(lay, 188)

    def test_title_churn_cannot_move_a_tab(self):
        # The layout's inputs are ids, indexes, names, widths and the current window: no title
        # or state. Changing the current window moves nothing while nothing is hidden.
        a = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@4", 28, 16)
        b = tb.lay_out([DOTCLAUDE], SHARED5, 188, "@9", 28, 16)
        self.assertEqual(a, b)
        self.assertEqual(tb.render(a), tb.render(b))

    def test_a_wide_screen_caps_a_row_by_bytes(self):
        lay = tb.lay_out([], tabs(*range(1, 21)), 400, "@1", 28, 16)
        self.check_fits(lay, 400)
        for row in tb.render(lay):
            self.assertLessEqual(len(row.encode()), tb.ROW_BYTES)

    def test_a_tiny_client_still_shows_one_tab_a_row(self):
        lay = tb.lay_out([DOTCLAUDE], SHARED5, 12, "@4", 28, 16)
        self.assertTrue(all(len(tab_ids(r)) >= 1 for r in lay.rows))
        tb.render(lay)                     # widths clamp: nothing raises


# --- render -------------------------------------------------------------------------------------

class Render(unittest.TestCase):
    def test_rows_hold_only_template_text(self):
        for width in (188, 45):
            lay = tb.lay_out([DOTCLAUDE], SHARED5, width, "@4", 28, 16)
            for row in tb.render(lay):
                with self.subTest(width=width):
                    self.assertTrue(row.startswith("#[fill=colour236]"))
                    self.assertNotIn("%", row)
                    self.assertNotIn("#(", row)
                    self.assertNotIn("#{E:", row)
                    self.assertLessEqual(set(row), ALPHABET)
                    self.assertNotRegex(row, r"#\[[^]]*,")       # one style per #[ ]

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
        groups = [Group(f"g{k}", tabs(*range(10 * k + 1, 10 * k + 9))) for k in range(6)]
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


# --- claude.conf --------------------------------------------------------------------------------

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

    def test_every_hook_runs_the_layout_by_full_path(self):
        with open(CONF) as f:
            text = f.read()
        for hook in ("client-attached", "client-detached", "client-resized", "window-linked",
                     "window-unlinked", "after-new-window", "session-window-changed"):
            with self.subTest(hook=hook):
                self.assertRegex(text, rf"set-hook -g {hook}\[43\] 'run-shell -b "
                                       rf"\"\$HOME/\.local/bin/tmux-tab-bar layout\"'")


# --- layout against a fake tmux ------------------------------------------------------------------

FAKE_TMUX = r'''
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
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
if args[0] != "set-option":
    sys.exit(1)
rest, unset, window, target = args[1:], False, False, None
while rest and rest[0].startswith("-"):
    flag = rest.pop(0)
    if flag == "-t":
        target = rest.pop(0)
    unset |= flag == "-u"
    window |= flag == "-w"
key, recs = ("window_id", st["windows"]) if window else ("session_id", st["sessions"])
recs = [r for r in recs if r[key] == target]
if not recs:
    sys.exit(1)
for r in recs:
    if unset:
        r.pop(rest[0], None)
    else:
        r[rest[0]] = rest[1]
with open(path, "w") as f:
    json.dump(st, f)
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
                         "window_active": "1" if w == "@2" else "0"} for w in cwds],
            "panes": [{"window_id": w, "pane_active": "1", "pane_current_path": p,
                       "pane_title": "✳ [x] title"} for w, p in cwds.items()],
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

    def test_a_first_run_writes_every_row_then_the_count_and_a_rerun_writes_nothing(self):
        self.run_layout()
        s = self.session()
        self.assertEqual(s["status"], "2")
        self.assertTrue(s["status-format[0]"] and s["status-format[1]"])
        self.assertIn("@tab_bar_sig", s)
        self.assertEqual(s["@tab_bar_g0"], "dotclaude")
        names = {w["window_id"]: (w["@tab_name"], w.get("@tab_group", ""))
                 for w in self.read_state()["windows"]}
        self.assertEqual(names, {"@1": ("hq:", ""), "@2": ("lead", "0"),
                                 "@3": ("tab-bar", "0"), "@4": ("lane-close", "0")})
        order = [c[-2] if c[1] != "-u" else c[-1] for c in self.writes()
                 if c[1] != "-w"]
        self.assertLess(order.index("status-format[1]"), order.index("status"))
        self.assertEqual(order[-1], "@tab_bar_sig")
        self.run_layout()
        self.assertEqual(self.writes(), [])

    def test_reads_carry_no_title_or_state_and_title_churn_writes_nothing(self):
        self.run_layout()
        for call in self.calls():
            if call[0].startswith("list-"):
                fmt = call[call.index("-F") + 1]
                for word in ("pane_title", "@claude_state", "@claude_star"):
                    self.assertNotIn(word, fmt)
        st = self.read_state()
        for p in st["panes"]:
            p["pane_title"] = "⠂ [x] a brand new and much longer title"
        self.write_state(st)
        self.run_layout()
        self.assertEqual(self.writes(), [])

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

    def test_a_bar_turned_off_stays_off(self):
        st = self.read_state()
        st["sessions"][0]["status"] = "off"
        self.write_state(st)
        self.run_layout()
        self.assertEqual(self.session()["status"], "off")
        self.assertIn("status-format[0]", self.session())

    def test_outside_tmux_nothing_runs(self):
        env = {k: v for k, v in self.env.items() if k != "TMUX"}
        p = subprocess.run([sys.executable, "-I", SCRIPT, "layout"], capture_output=True,
                           text=True, timeout=30, env=env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(self.calls(), [])

    def test_a_failing_tmux_is_fail_open_and_silent(self):
        self.run_layout(STUB_FAIL="list-windows")
        self.assertEqual(self.writes(), [])
        err = os.path.join(self.run_dir, f".tmux-tab-bar.{os.getuid()}.err")
        with open(err) as f:
            self.assertIn("list-windows", f.read())

    def test_a_held_lock_marks_the_state_dirty_and_leaves(self):
        lock = os.path.join(self.run_dir, f".tmux-tab-bar.{os.getuid()}.lock")
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.run_layout()
        self.assertEqual(self.calls(), [])
        self.assertTrue(os.path.exists(os.path.join(self.run_dir,
                                                    f".tmux-tab-bar.{os.getuid()}.dirty")))

    def test_bad_usage_exits_2(self):
        p = subprocess.run([sys.executable, "-I", SCRIPT], capture_output=True, text=True,
                           timeout=30, env=self.env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("layout", p.stderr)


# --- layout against a real tmux ------------------------------------------------------------------

class RealTmux(unittest.TestCase):
    """A private tmux server (-S, -f /dev/null) with one attached client on a pty at 188x46.
    HOME is a temp dir, so the conf's hooks find no tmux-tab-bar and stay inert: only the
    explicit runs lay out."""

    def setUp(self):
        self.tmux_bin = shutil.which("tmux")
        if not self.tmux_bin:
            self.skipTest("tmux not installed")
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock = os.path.join(self.tmp, "sock")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("TMUX", "CLAUDE"))}
        self.env.update(HOME=self.home, TERM="xterm-256color", TMUX_CLAUDE_STATUS_DIR=self.tmp)
        repos = os.path.join(self.tmp, "code")
        os.makedirs(repos)
        self.lead = make_repo(repos, "dotclaude", lanes=["tab-bar"])
        self.lane = os.path.join(repos, "tab-bar")
        self.plain = os.path.join(repos, "hq")
        os.makedirs(self.plain)
        p = self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "t", "-x", "188", "-y", "46",
                      "-c", self.lead, "sleep 600", check=False)
        if "Operation not permitted" in p.stderr:
            self.skipTest("the Bash sandbox blocks tmux's socket; run outside it")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.addCleanup(self.tmux, "kill-server", check=False)
        self.tmux("source-file", CONF)
        self.tmux("new-window", "-d", "-t", "t", "-c", self.lane, "sleep 600")
        self.tmux("new-window", "-d", "-t", "t", "-c", self.plain, "sleep 600")
        self.attach(188, 46)
        pid = self.tmux("display", "-p", "#{pid}").stdout.strip()
        self.layout_env = {**self.env, "TMUX": f"{self.sock},{pid},0",
                           "PATH": os.path.dirname(self.tmux_bin) + os.pathsep
                           + os.environ.get("PATH", "/usr/bin:/bin")}

    def tmux(self, *args, check=True):
        p = subprocess.run([self.tmux_bin, "-S", self.sock, *args], capture_output=True,
                           text=True, timeout=10, env=self.env)
        if check:
            self.assertEqual(p.returncode, 0, (args, p.stderr))
        return p

    def attach(self, cols, rows):
        pid, master = pty.fork()
        if pid == 0:                        # the child: size its tty, then become the client
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                os.execve(self.tmux_bin, [self.tmux_bin, "-S", self.sock, "attach", "-t", "t"],
                          self.env)
            finally:
                os._exit(127)

        def drain():
            while True:
                try:
                    if not os.read(master, 65536):
                        return
                except OSError:
                    return

        threading.Thread(target=drain, daemon=True).start()
        self.addCleanup(os.waitpid, pid, 0)
        self.addCleanup(os.close, master)
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.tmux("list-clients", "-F", "#{client_width}").stdout.strip() == str(cols):
                return
            time.sleep(0.05)
        self.fail("the client never attached")

    def run_layout(self):
        p = subprocess.run([sys.executable, "-I", SCRIPT, "layout"], capture_output=True,
                           text=True, timeout=30, env=self.layout_env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        err = os.path.join(self.tmp, f".tmux-tab-bar.{os.getuid()}.err")
        self.assertFalse(os.path.exists(err), open(err).read() if os.path.exists(err) else "")

    def show(self, *args):
        return self.tmux("show-options", *args).stdout

    def test_every_row_is_written_and_a_rerun_changes_nothing(self):
        self.run_layout()
        self.assertEqual(self.tmux("show-options", "-v", "-t", "t", "status").stdout.strip(), "2")
        for i in range(2):
            row = self.tmux("show-options", "-v", "-t", "t", f"status-format[{i}]").stdout
            self.assertTrue(row.startswith("#[fill=colour236]"), (i, row[:80]))
        names = self.tmux("list-windows", "-t", "t", "-F", "#{window_index} #{@tab_name}").stdout
        self.assertEqual(sorted(names.split("\n")[:-1]),
                         sorted(["0 lead", "1 tab-bar", "2 hq:"]))
        before = (self.show("-t", "t"), self.show("-w", "-t", "t:0"), self.show("-w", "-t", "t:2"))
        self.run_layout()
        after = (self.show("-t", "t"), self.show("-w", "-t", "t:0"), self.show("-w", "-t", "t:2"))
        self.assertEqual(after, before)

    def test_a_name_holding_a_job_runs_nothing(self):
        self.run_layout()
        pwned, control = os.path.join(self.tmp, "pwned"), os.path.join(self.tmp, "control")
        self.tmux("set-option", "-w", "-t", "t:2", "@tab_name", f"#(touch {pwned})")
        # The positive control: display -p does start a #() job written into its format.
        self.tmux("display", "-p", "-t", "t", f"#(touch {control})")
        deadline = time.time() + 5
        while not os.path.exists(control) and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(os.path.exists(control))
        for i in range(2):
            row = self.tmux("show-options", "-v", "-t", "t", f"status-format[{i}]").stdout
            row = row.rstrip("\n")
            self.tmux("display", "-p", "-t", "t", row)
        time.sleep(1)
        self.assertFalse(os.path.exists(pwned))


if __name__ == "__main__":
    unittest.main()
