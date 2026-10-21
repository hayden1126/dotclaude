"""setup.sh's two merge helpers (the settings overlay, the git excludes block) and its wiring,
install-state.py's calls and source globs among it (stdlib only). test_install_state.py tests
install-state.py itself."""
import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import resource
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MERGE = os.path.join(REPO, "merge-settings.py")
IGNORE = os.path.join(REPO, "git", "install-ignore.py")
INSTALL_STATE = os.path.join(REPO, "install-state.py")


def load(path):
    loader = importlib.machinery.SourceFileLoader(os.path.basename(path).replace("-", "_")[:-3], path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


merge_settings = load(MERGE)
install_ignore = load(IGNORE)
install_state = load(INSTALL_STATE)


def run(*args, env=None):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, env=env)


class MergeRule(unittest.TestCase):
    CASES = [
        # (name, baseline, overlay, expected)
        ("objects merge key by key",
         {"a": 1, "s": {"x": 1}}, {"s": {"y": 2}}, {"a": 1, "s": {"x": 1, "y": 2}}),
        ("an overlay scalar wins", {"model": "a", "n": 1}, {"model": "b"}, {"model": "b", "n": 1}),
        ("lists append", {"l": ["a *"]}, {"l": ["b *"]}, {"l": ["a *", "b *"]}),
        ("a list item already present is not repeated",
         {"l": ["a *", "b *"]}, {"l": ["b *", "c *"]}, {"l": ["a *", "b *", "c *"]}),
        ("hooks groups append per event",
         {"hooks": {"Stop": [{"hooks": [{"command": "x"}]}]}},
         {"hooks": {"Stop": [{"hooks": [{"command": "y"}]}], "PostToolUse": [{"hooks": []}]}},
         {"hooks": {"Stop": [{"hooks": [{"command": "x"}]}, {"hooks": [{"command": "y"}]}],
                    "PostToolUse": [{"hooks": []}]}}),
        ("a new key is added", {"a": 1}, {"b": {"c": [1]}}, {"a": 1, "b": {"c": [1]}}),
    ]

    def test_cases(self):
        for name, base, over, want in self.CASES:
            with self.subTest(name):
                self.assertEqual(merge_settings.merge(base, over), want)

    def test_merge_does_not_mutate_the_baseline(self):
        base = {"l": [1], "d": {"k": [1]}}
        merge_settings.merge(base, {"l": [2], "d": {"k": [2]}})
        self.assertEqual(base, {"l": [1], "d": {"k": [1]}})


class MergeCli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.dir.name, "settings.json")
        with open(self.base, "w") as f:
            f.write('{"a":   [1]}\n')  # odd spacing: proves the no-overlay path is verbatim

    def tearDown(self):
        self.dir.cleanup()

    def overlay(self, text):
        path = os.path.join(self.dir.name, "settings.machine.json")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_no_overlay_prints_the_baseline_byte_for_byte(self):
        r = run(MERGE, self.base, os.path.join(self.dir.name, "absent.json"))
        self.assertEqual((r.returncode, r.stdout), (0, '{"a":   [1]}\n'))

    def test_an_overlay_is_merged(self):
        r = run(MERGE, self.base, self.overlay('{"a": [2], "b": true}'))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout), {"a": [1, 2], "b": True})

    def test_a_bad_overlay_fails_and_prints_nothing(self):
        for text in ("{not json", "[1, 2]"):
            with self.subTest(text):
                r = run(MERGE, self.base, self.overlay(text))
                self.assertEqual((r.returncode, r.stdout), (1, ""))

    def test_an_overlay_too_deep_for_json_fails_as_a_bad_one(self):
        r = run(MERGE, self.base, self.overlay("[" * 100000))   # RecursionError in json
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("does not parse", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_the_real_baseline_passes_through(self):
        with open(os.path.join(REPO, "settings.json")) as f:
            want = f.read()
        self.assertEqual(run(MERGE, os.path.join(REPO, "settings.json")).stdout, want)

    def live(self, obj_or_text):
        path = os.path.join(self.dir.name, "live.json")
        with open(path, "w") as f:
            f.write(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text))
        return path

    def test_live_only_keys_are_kept(self):
        # The 2026-09-30 install: setup.sh dropped autoMode and model from the live file.
        live = self.live({"a": [9], "autoMode": {"soft_deny": ["x"]}, "model": "opus"})
        r = run(MERGE, self.base, os.path.join(self.dir.name, "absent.json"), live)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout),
                         {"a": [1], "autoMode": {"soft_deny": ["x"]}, "model": "opus"})
        self.assertIn("kept the live-only keys autoMode, model", r.stderr)

    def test_a_baseline_key_still_wins_and_the_reset_is_named(self):
        with open(self.base, "w") as f:
            f.write('{"effortLevel": "medium"}\n')
        r = run(MERGE, self.base, self.overlay("{}"), self.live({"effortLevel": "high"}))
        self.assertEqual(json.loads(r.stdout), {"effortLevel": "medium"})
        self.assertIn("effortLevel ('high' -> 'medium')", r.stderr)
        r = run(MERGE, self.base, self.overlay('{"effortLevel": "high"}'),
                self.live({"effortLevel": "high"}))
        self.assertEqual((json.loads(r.stdout), r.stderr), ({"effortLevel": "high"}, ""))

    def test_a_changed_object_and_a_dropped_hook_are_named(self):
        with open(self.base, "w") as f:
            json.dump({"permissions": {"allow": ["a"]},
                       "hooks": {"Stop": [{"hooks": [{"command": "base"}]}]}}, f)
        live = self.live({"permissions": {"allow": ["a", "b"]},
                          "hooks": {"Stop": [{"hooks": [{"command": "hand-added"}]},
                                             {"hooks": [{"command": "base"}]}]}})
        r = run(MERGE, self.base, self.overlay("{}"), live)
        self.assertIn("the baseline resets permissions", r.stderr)
        self.assertIn("dropped: hand-added", r.stderr)
        self.assertNotIn("base;", r.stderr)

    def test_a_reset_is_named_on_the_verbatim_path_too(self):
        # No overlay and no live-only keys: the baseline goes in byte for byte, and a live
        # permissions object it replaces must still be named.
        with open(self.base, "w") as f:
            f.write('{"permissions": {"allow": ["a"]}}\n')
        live = self.live({"permissions": {"allow": ["a", "mine"]}})
        r = run(MERGE, self.base, os.path.join(self.dir.name, "absent.json"), live)
        self.assertEqual(r.stdout, '{"permissions": {"allow": ["a"]}}\n')
        self.assertIn("the baseline resets permissions", r.stderr)

    def test_reordered_hooks_are_not_reported(self):
        with open(self.base, "w") as f:
            json.dump({"hooks": {"Stop": [{"hooks": [{"command": "x"}]}]}}, f)
        over = self.overlay('{"hooks": {"Stop": [{"hooks": [{"command": "y"}]}]}}')
        live = self.live({"hooks": {"Stop": [{"hooks": [{"command": "y"}]},
                                             {"hooks": [{"command": "x"}]}]}})
        self.assertEqual(run(MERGE, self.base, over, live).stderr, "")

    def test_an_overlay_key_is_not_duplicated_from_live(self):
        r = run(MERGE, self.base, self.overlay('{"b": 2}'), self.live({"b": 1}))
        self.assertEqual(json.loads(r.stdout), {"a": [1], "b": 2})

    def test_nothing_to_keep_is_still_verbatim(self):
        r = run(MERGE, self.base, os.path.join(self.dir.name, "absent.json"), self.live({"a": [9]}))
        self.assertEqual(r.stdout, '{"a":   [1]}\n')
        r = run(MERGE, self.base, os.path.join(self.dir.name, "absent.json"),
                os.path.join(self.dir.name, "no-live.json"))
        self.assertEqual(r.stdout, '{"a":   [1]}\n')

    def test_an_empty_live_file_counts_as_none(self):
        r = run(MERGE, self.base, os.path.join(self.dir.name, "absent.json"), self.live(""))
        self.assertEqual((r.returncode, r.stdout), (0, '{"a":   [1]}\n'))

    def protect(self, checkout, deny, live=None):
        """merge-settings --checkout under a fake HOME, with a baseline denyWrite of `deny`."""
        home = os.path.join(self.dir.name, "home")
        os.makedirs(checkout, exist_ok=True)
        with open(self.base, "w") as f:
            json.dump({"sandbox": {"filesystem": {"denyWrite": deny}}}, f)
        args = [MERGE, "--checkout", checkout, self.base, os.path.join(self.dir.name, "absent.json")]
        return run(*args, *([live] if live else []), env=dict(os.environ, HOME=home))

    def test_a_change_of_checkout_is_not_a_reset(self):
        # A lane install over a main one, and the lead's reinstall from main after it, change
        # only the checkout's copies: they are named on their own line, never as a reset whose
        # advice (keep it in the overlay) would keep the lane's paths.
        main, lane = os.path.join(self.dir.name, "home", "dotclaude"), os.path.join(self.dir.name, "x")
        deny = ["~/dotclaude/hooks", "~/dotclaude/bin"]
        installed = self.protect(lane, deny, self.live(self.protect(main, deny).stdout))
        self.assertIn("installing from", installed.stderr)
        self.assertNotIn("resets", installed.stderr)
        back = self.protect(main, deny, self.live(installed.stdout))
        self.assertEqual((back.returncode, back.stderr), (0, ""))
        self.assertNotIn(os.path.realpath(lane), back.stdout)

    def test_a_bad_flag_prints_usage(self):
        for args in (["--checkout"], ["--checkout=x", self.base], [self.base, "--checkout", "x"]):
            with self.subTest(args):
                r = run(MERGE, *args)
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertIn("Usage:", r.stderr)

    def test_another_checkout_protects_its_own_copies(self):
        # A lane's install links ~/.claude/hooks and the rest into the lane's worktree, which
        # that lane's sandboxed Bash can write; its copies join denyWrite.
        lane = os.path.realpath(os.path.join(self.dir.name, "dotclaude-lanes", "x"))
        r = self.protect(lane, ["~/dotclaude/hooks", "~/dotclaude/bin", "~/.claude/hooks"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["sandbox"]["filesystem"]["denyWrite"],
                         ["~/dotclaude/hooks", "~/dotclaude/bin", "~/.claude/hooks",
                          lane + "/hooks", lane + "/bin"])
        self.assertIn(f"installing from {lane}", r.stderr)

    def test_the_dotclaude_checkout_stays_verbatim(self):
        r = self.protect(os.path.join(self.dir.name, "home", "dotclaude"), ["~/dotclaude/hooks"])
        with open(self.base) as f:
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, f.read(), ""))

    def test_every_path_setup_installs_from_is_write_protected_in_each_checkout(self):
        # What setup.sh links, copies or runs from the checkout runs outside the sandbox later
        # (a hook, a skill script, the settings), so it must be in denyWrite, and so must a
        # lane's copy of it. templates/ is exempt: its seeds are copied into projects, never run.
        with open(os.path.join(REPO, "setup.sh")) as f:
            sources = set(re.findall(r'"?\$REPO_DIR"?/([\w.-]+)', f.read())) - {"templates"}
        self.assertIn("hooks", sources)
        with open(os.path.join(REPO, "settings.json")) as f:
            base = json.load(f)
        names = {p[len("~/dotclaude/"):] for p in base["sandbox"]["filesystem"]["denyWrite"]
                 if p.startswith("~/dotclaude/")}
        self.assertLessEqual(sources, names)
        lane = os.path.join(self.dir.name, "lane")
        deny = merge_settings.protect_checkout(base, lane, home=self.dir.name)
        deny = deny["sandbox"]["filesystem"]["denyWrite"]
        self.assertLessEqual({os.path.join(os.path.realpath(lane), n) for n in sources}, set(deny))

    def test_a_lane_install_with_an_overlay_and_a_live_file(self):
        # setup.sh's call shape: the overlay's ~/dotclaude paths get the lane's copies too, and
        # a live-only key is kept.
        lane = os.path.realpath(os.path.join(self.dir.name, "x"))
        overlay = self.overlay(json.dumps(
            {"sandbox": {"filesystem": {"denyWrite": ["~/dotclaude/local"]}}}))
        os.makedirs(lane)
        with open(self.base, "w") as f:
            json.dump({"sandbox": {"filesystem": {"denyWrite": ["~/dotclaude/hooks"]}}}, f)
        r = run(MERGE, "--checkout", lane, self.base, overlay, self.live({"model": "opus"}),
                env=dict(os.environ, HOME=os.path.join(self.dir.name, "home")))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["sandbox"]["filesystem"]["denyWrite"],
                         ["~/dotclaude/hooks", "~/dotclaude/local", lane + "/hooks",
                          lane + "/local"])
        self.assertEqual(out["model"], "opus")

    def test_a_symlinked_dotclaude_is_the_main_checkout(self):
        # ~/dotclaude may be a link to the real checkout: installing from either path is the
        # main install, verbatim, with no copies.
        home = os.path.join(self.dir.name, "home")
        real = os.path.join(self.dir.name, "src", "dotclaude")
        os.makedirs(real)
        os.makedirs(home)
        os.symlink(real, os.path.join(home, "dotclaude"))
        for checkout in (real, os.path.join(home, "dotclaude")):
            with self.subTest(checkout):
                r = self.protect(checkout, ["~/dotclaude/hooks"])
                self.assertEqual((r.returncode, r.stderr), (0, ""))
                self.assertNotIn(real, r.stdout)

    def test_a_bad_live_file_fails_and_prints_nothing(self):
        for text in ("{not json", "[1, 2]"):
            with self.subTest(text):
                r = run(MERGE, self.base, self.overlay("{}"), self.live(text))
                self.assertEqual((r.returncode, r.stdout), (1, ""))


class BaselinePlugins(unittest.TestCase):
    def test_the_baseline_enables_exactly_what_setup_installs(self):
        # setup.sh installs plugins/enabled.json; a plugin missing from the baseline's
        # enabledPlugins is installed but off unless a machine's overlay turns it on.
        with open(os.path.join(REPO, "settings.json")) as f:
            baseline = json.load(f)["enabledPlugins"]
        with open(os.path.join(REPO, "plugins", "enabled.json")) as f:
            installed = json.load(f)
        self.assertEqual(baseline, installed)


class IgnoreBlock(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.block = os.path.join(self.dir.name, "block")
        with open(self.block, "w") as f:
            f.write("# why\n/.bashrc\n")
        self.dest = os.path.join(self.dir.name, "git", "ignore")

    def tearDown(self):
        self.dir.cleanup()

    def install(self):
        r = run(IGNORE, self.block, self.dest)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.dest) as f:
            return f.read()

    def test_a_missing_file_gets_just_the_block(self):
        self.assertEqual(self.install(), f"{install_ignore.BEGIN}\n# why\n/.bashrc\n{install_ignore.END}\n")

    def test_other_lines_survive_and_a_second_run_changes_nothing(self):
        os.makedirs(os.path.dirname(self.dest))
        with open(self.dest, "w") as f:
            f.write("**/.claude/settings.local.json")  # no trailing newline, like a hand edit
        first = self.install()
        self.assertTrue(first.startswith("**/.claude/settings.local.json\n\n"), first)
        self.assertEqual(self.install(), first)

    def test_the_block_is_replaced_in_place(self):
        self.install()
        with open(self.dest, "a") as f:
            f.write("after\n")
        with open(self.block, "w") as f:
            f.write("/.zshrc\n")
        text = self.install()
        self.assertNotIn("/.bashrc", text)
        self.assertTrue(text.endswith(f"/.zshrc\n{install_ignore.END}\nafter\n"), text)

    def test_an_unclosed_block_leaves_the_file_alone(self):
        os.makedirs(os.path.dirname(self.dest))
        with open(self.dest, "w") as f:
            f.write(f"{install_ignore.BEGIN}\n/.x\n")
        r = run(IGNORE, self.block, self.dest)
        self.assertEqual(r.returncode, 1)
        with open(self.dest) as f:
            self.assertEqual(f.read(), f"{install_ignore.BEGIN}\n/.x\n")


class CcstatuslineSettings(unittest.TestCase):
    """setup.sh's inline python that installs ~/.config/ccstatusline/settings.json: an existing
    file that doesn't parse, has a malformed lines list or lacks the ctx widget is backed up
    before the baseline replaces it, a destination that isn't a regular file is left alone, and
    the retired session-summary rows leave an existing file."""

    MARK = "\"$CC_CFG_DIR/settings.json\" <<'PY'\n"

    def fresh(self):
        """A new temp dir's ccstatusline/settings.json path, not yet written."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "ccstatusline"))
        return os.path.join(tmp.name, "ccstatusline", "settings.json")

    def run_install(self, dst, preexec_fn=None):
        with open(os.path.join(REPO, "setup.sh")) as f:
            src = f.read()
        self.assertIn(self.MARK, src)
        src = src.split(self.MARK, 1)[1].split("\nPY\n", 1)[0]
        baseline = os.path.join(REPO, "statusline", "ccstatusline-settings.json")
        p = subprocess.run([sys.executable, "-I", "-", baseline, dst], input=src,
                           capture_output=True, text=True, timeout=30, preexec_fn=preexec_fn)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    @staticmethod
    def scripts(lines):
        """The basename of every *.py token in lines' commandPaths."""
        return {os.path.basename(t.strip('"')) for line in lines for w in line
                for t in (w.get("commandPath") or "").split() if t.strip('"').endswith(".py")}

    def install(self, dst):
        p = self.run_install(dst)
        with open(dst) as f:
            lines = json.load(f)["lines"]
        self.assertIn("ctx-breakdown.py", self.scripts(lines), lines)
        self.assertNotIn("session-summary.py", self.scripts(lines), lines)
        return p

    def backups(self, dst):
        return glob.glob(dst + ".pre-dotclaude-*")

    def installed(self, lines):
        """lines, as an earlier install left them, after this install: the lines it writes."""
        dst = self.fresh()
        with open(dst, "w") as f:
            json.dump({"version": 3, "lines": lines}, f)
        self.install(dst)
        with open(dst) as f:
            return json.load(f)["lines"]

    LINE_1 = [{"id": "1", "type": "model"},
              {"id": "3", "type": "custom-command", "commandPath": "python ctx-breakdown.py"},
              {"id": "30", "type": "custom-text", "customText": "mine"}]

    @staticmethod
    def summary_widget(row):
        return {"id": str(19 + row), "type": "custom-command",
                "commandPath": f'"/usr/bin/python3" "/c/session-summary.py" --row {row}'}

    def test_an_install_with_the_summary_rows_loses_them(self):
        lines = self.installed([self.LINE_1, [self.summary_widget(1)], [self.summary_widget(2)]])
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual([(w["id"], w["type"]) for w in lines[0]],
                         [(w["id"], w["type"]) for w in self.LINE_1])
        self.assertEqual(lines[0][2]["customText"], "mine")

    def test_a_line_shared_with_a_summary_widget_keeps_the_rest(self):
        own = {"id": "40", "type": "custom-text", "customText": "keep"}
        # Named like the retired script, but not that script: the user's own widgets.
        tool = {"id": "41", "type": "custom-command",
                "commandPath": "/home/u/session-summary-tools/x.sh"}
        mine = {"id": "42", "type": "custom-command", "commandPath": "python my-session-summary.py"}
        lines = self.installed([self.LINE_1, [self.summary_widget(1), own],
                                [self.summary_widget(2)], [], [tool, mine]])
        self.assertEqual(lines[1:3], [[own], []])
        self.assertEqual([w["id"] for w in lines[3]], ["41", "42"])
        self.assertTrue(lines[3][1]["commandPath"].endswith('/my-session-summary.py"'), lines[3])

    def test_a_file_that_does_not_parse_is_backed_up(self):
        # "[" * 100000: RecursionError in json, not ValueError.
        for junk in ("{", "[" * 100000):
            with self.subTest(junk=junk[:8]):
                dst = self.fresh()
                with open(dst, "w") as f:
                    f.write(junk)
                p = self.install(dst)
                kept = self.backups(dst)
                self.assertEqual(len(kept), 1, kept)
                with open(kept[0]) as f:
                    self.assertEqual(f.read(), junk)
                self.assertIn("isn't a readable JSON object; backed up to", p.stdout)

    def test_a_malformed_lines_list_is_backed_up(self):
        # Each crashed the helpers, which read lines as a list of lists of dicts; the last two
        # hold the ctx widget, so its check alone doesn't catch them.
        ctx = self.LINE_1[1]
        for lines in ({"a": 1}, "x", [{"not": "a list"}], [["a widget"]],
                      [[{"type": "custom-command", "commandPath": 5}]], [[ctx, "junk"]],
                      [[ctx, None]],
                      [[ctx], [{"type": "custom-command", "commandPath": ["x.py"]}]]):
            with self.subTest(lines=lines):
                dst = self.fresh()
                with open(dst, "w") as f:
                    json.dump({"lines": lines}, f)
                p = self.install(dst)
                self.assertEqual(len(self.backups(dst)), 1)
                self.assertIn("has a malformed lines list; backed up to", p.stdout)

    def test_a_file_too_deep_to_write_back_is_backed_up(self):
        # json reads 2000 levels but can't write them back: the write would crash after
        # truncating the file.
        dst = self.fresh()
        text = json.dumps({"lines": [self.LINE_1]})[:-1] + ', "x": ' + "[" * 2000 + "]" * 2000 + "}"
        with open(dst, "w") as f:
            f.write(text)
        p = self.install(dst)
        kept = self.backups(dst)
        self.assertEqual(len(kept), 1, kept)
        with open(kept[0]) as f:
            self.assertEqual(f.read(), text)
        self.assertIn("nests too deep to write back; backed up to", p.stdout)

    def test_a_destination_that_is_not_a_regular_file_is_left_alone(self):
        # A directory crashed the backup copy, a FIFO would hang the read, and a dangling or
        # looping link crashed the write (or sent it wherever the link points).
        def link(target):
            return lambda dst: os.symlink(target(dst), dst)
        makers = {"dir": os.makedirs, "fifo": os.mkfifo,
                  "link to a dir": link(os.path.dirname),
                  "dangling link": link(lambda dst: dst + ".gone/settings.json"),
                  "link loop": link(lambda dst: dst)}
        for name, make in makers.items():
            with self.subTest(make=name):
                dst = self.fresh()
                make(dst)
                before = os.lstat(dst)
                p = self.run_install(dst)
                after = os.lstat(dst)
                self.assertEqual((after.st_mode, after.st_ino), (before.st_mode, before.st_ino))
                self.assertFalse(os.path.lexists(dst + ".gone"))
                self.assertEqual(self.backups(dst), [])
                self.assertIn("isn't a regular file; ccstatusline settings not installed",
                              p.stdout)

    def test_a_link_to_a_file_stays_a_link(self):
        # A dotfiles manager's link: the file it points at gets the new layout. A leftover
        # read-only copy from a killed run doesn't stop the write.
        dst = self.fresh()
        target = os.path.join(os.path.dirname(dst), "managed.json")
        with open(target, "w") as f:
            json.dump({"lines": [self.LINE_1]}, f)
        os.symlink(target, dst)
        leftover = target + ".dotclaude-new"
        with open(leftover, "w") as f:
            f.write("{}")
        os.chmod(leftover, 0o444)
        p = self.install(dst)
        self.assertNotIn("!!", p.stdout)
        self.assertEqual(os.readlink(dst), target)
        with open(target) as f:
            ctx = json.load(f)["lines"][0][1]["commandPath"]
        self.assertTrue(ctx.startswith(f'"{sys.executable}" '), ctx)   # patched: written
        self.assertFalse(os.path.lexists(leftover))

    def test_a_failed_write_leaves_the_old_file_whole(self):
        # A write cut short (disk full, quota, EFBIG) after the open had truncated the file lost
        # the user's layout, with no backup. RLIMIT_FSIZE makes the write fail: Python ignores
        # SIGXFSZ, so it raises EFBIG.
        dst = self.fresh()
        text = json.dumps({"lines": [self.LINE_1]}, indent=2)
        with open(dst, "w") as f:
            f.write(text)
        limit = len(text) + 20   # the read fits; the patched paths make the write longer
        p = self.run_install(
            dst, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit)))
        with open(dst) as f:
            self.assertEqual(f.read(), text)
        self.assertEqual(os.listdir(os.path.dirname(dst)), ["settings.json"])
        self.assertIn("couldn't be written (File too large); ccstatusline settings not installed",
                      p.stdout)

    @unittest.skipIf(os.geteuid() == 0, "root reads and writes past file modes")
    def test_a_file_it_cannot_back_up_or_write_is_left_alone(self):
        for mode, why in ((0o000, "couldn't be backed up"), (0o444, "couldn't be written")):
            with self.subTest(mode=oct(mode)):
                dst = self.fresh()
                text = json.dumps({"lines": [self.LINE_1]})
                with open(dst, "w") as f:
                    f.write(text)
                os.chmod(dst, mode)
                self.addCleanup(os.chmod, dst, 0o644)
                p = self.run_install(dst)
                os.chmod(dst, 0o644)
                with open(dst) as f:
                    self.assertEqual(f.read(), text)
                self.assertEqual(self.backups(dst), [])
                self.assertIn(f"{why} (Permission denied); ccstatusline settings not installed",
                              p.stdout)

    def test_a_missing_file_gets_the_baseline_and_no_backup(self):
        dst = self.fresh()
        p = self.install(dst)
        self.assertEqual(self.backups(dst), [])
        self.assertNotIn("backed up to", p.stdout)


def setup_lines():
    """setup.sh's lines, backslash continuations joined."""
    with open(os.path.join(REPO, "setup.sh")) as f:
        return f.read().replace("\\\n", " ").splitlines()


def first(lines, pattern):
    return next(i for i, l in enumerate(lines) if re.match(pattern, l))


# Lines that name Python without starting it, per script. Anything else that names a Python
# interpreter or a .py file outside a heredoc body must be a call in the strict form.
PYTHON_NON_CALLS = {
    "setup.sh": ('for f in "$REPO_DIR"/hooks/*.sh "$REPO_DIR"/hooks/*.py; do',
                 'for pyf in "$REPO_DIR"/statusline/*.py; do'),
    "setup-tmux.sh": ('command -v python3 >/dev/null || die "python3 not found."',),
}


def python_lines(text, non_calls):
    """A shell script's lines that name Python: (bad, ok, unclosed). ok holds the calls in the
    strict form: the line's first command is `python3 -I` then a quoted arg or `-`, and nothing
    after it (past &&, ||, ;, |, & or a command substitution) names Python. bad holds every
    other line naming a Python interpreter (python, python3, python3.12) or a .py file, so a
    bare python3, an interpreter in a variable (its assignment names it) and a direct run of a
    .py all land there. Full-line comments are dropped before continuations join (bash doesn't
    continue a comment), heredoc bodies (the Python a call reads, or printed text) are skipped,
    and unclosed is the delimiter of a heredoc still open at the end. Lines are
    whitespace-normalized.

    Known limits (no top-level script does any of these today): a `<<WORD` inside a string or
    an arithmetic `$((x << 2))` opens a heredoc that isn't there (the unclosed check catches one
    that never ends); a trailing `cmd # note \\` reads as a continuation; and an extensionless
    script run through its shebang, or an interpreter in a variable whose assignment names no
    Python (`"$PYTHON"` from the environment), isn't seen."""
    bad, ok, delim, buf = [], [], None, ""
    for raw in text.splitlines():
        if delim is not None:
            if raw.strip() == delim:
                delim = None
            continue
        if not buf and raw.lstrip().startswith("#"):
            continue
        if raw.endswith("\\"):
            buf += raw[:-1] + " "
            continue
        line, buf = " ".join((buf + raw).split()), ""
        m = re.search(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1", line)  # a <<< here-string isn't one
        if m:
            delim = m.group(2)
        if line in non_calls:
            continue
        first, *rest = re.split(r"&&|\|\||[;|&`]|\$\(", line)
        if (re.match(r"python3 -I [\"'-]", first)
                and len(re.findall(r"\bpython[0-9.]*\b", first)) == 1
                and not any(re.search(r"\bpython[0-9.]*\b|\.py\b", s) for s in rest)):
            ok.append(line)
        elif re.search(r"\bpython[0-9.]*\b|\.py\b", line):
            bad.append(line)
    return bad, ok, delim


# Python a script starts through sys.executable runs isolated (-I), like the shell scripts'
# Python: the cwd or a writable dir never comes first on its import path. Each exception is a
# path and why.
EXECUTABLE_EXCEPTIONS = {
    "skills/deck-production/scripts/parity_check.py":
        "runs the deck build scripts in the sandbox, and they may need the user's "
        "site-packages, which -I drops",
}


def unisolated_executable_calls(text):
    """The lines that start sys.executable without -I as the first argument: a list or tuple
    that begins with sys.executable and whose next item isn't "-I"."""
    return [m.group(0) for m in re.finditer(r"(?:\[\s*sys\.executable\s*[,\]]|"
                                            r"\(\s*sys\.executable\s*,)[^\n]*", text)
            if not re.match(r"[\[(]\s*sys\.executable\s*,\s*[\"']-I[\"']", m.group(0))]


def setup_link_sources():
    """Every repo path setup.sh links, relative to the repo: the `for ... in` lists and the
    literal `link "$REPO_DIR/..."` sources, expanded by bash against this checkout."""
    words = []
    for line in setup_lines():
        m = re.match(r"\s*for \w+ in (.*); do$", line)
        if m:
            words += [w for w in m.group(1).split() if "$REPO_DIR" in w]
        m = re.match(r'\s*link ("\$REPO_DIR/[^"$]+")', line)
        if m:
            words.append(m.group(1))
    script = ('shopt -s nullglob; for f in ' + " ".join(words)
              + '; do printf "%s\\n" "${f#"$REPO_DIR"/}"; done')
    out = subprocess.run(["bash", "-c", script], env={**os.environ, "REPO_DIR": REPO},
                         capture_output=True, text=True, check=True).stdout
    return sorted({p.rstrip("/") for p in out.splitlines()
                   if os.path.lexists(os.path.join(REPO, p))})


class SetupWiring(unittest.TestCase):
    def test_setup_locks_and_holds_before_changing_anything(self):
        lines = setup_lines()
        hold = first(lines, r'python3 -I "\$REPO_DIR/install-state\.py" hold "\$REPO_DIR"')
        self.assertLess(first(lines, r"\s*flock -n 9"), hold)
        self.assertLess(first(lines, r"\s*flock -w 300 9"), hold)
        # Every flock on fd 9 is bounded: a sandboxed process can hold the lock, unnamed.
        calls = [m.group(1) for l in lines if not l.lstrip().startswith("#")
                 for m in re.finditer(r"\bflock((?: -\w+(?: \d+)?)*) 9\b", l)]
        self.assertEqual(sorted(calls), [" -n", " -w 300"])
        self.assertLess(hold, first(lines, r'mkdir -p "\$CLAUDE_DIR"'))
        self.assertLess(hold, first(lines, r"\s*(copy_managed|link) \""))
        self.assertLess(hold, first(lines, r'python3 -I "\$REPO_DIR/merge-settings\.py"'))
        # A plugin or tool installer that outlives the run must not inherit the lock.
        for name in ("plugins/marketplaces.json", "plugins/enabled.json", "tools.json"):
            line = lines[first(lines, rf'\s*python3 -I - "\$REPO_DIR/{re.escape(name)}"')]
            self.assertIn(" 9>&- ", line, name)

    def test_setup_prunes_after_the_last_link_then_checks_plugins(self):
        lines = setup_lines()
        prune = first(lines, r'python3 -I "\$REPO_DIR/install-state\.py" prune "\$REPO_DIR"')
        last_link = max(i for i, l in enumerate(lines) if re.match(r'\s*link "', l))
        plugins = first(lines, r'python3 -I "\$REPO_DIR/install-state\.py" plugins')
        self.assertLess(last_link, prune)
        self.assertLess(prune, plugins)
        self.assertLess(plugins, first(lines, r"# \d+\. Final checklist"))
        self.assertLess(first(lines, r"# \d+\. Register marketplaces"), prune)
        self.assertNotIn("prune_stale_hook_links", "\n".join(lines))

    def test_every_path_setup_links_matches_a_source_glob(self):
        sources = setup_link_sources()
        for known in ("CLAUDE.md", "notify-toast.ps1", "hooks/session-title.sh", "skills/lanes",
                      "agents/Explore.md", "skills/lanes/scripts/lane", "codex/AGENTS.md",
                      "statusline/ctx-breakdown.py"):
            self.assertIn(known, sources)  # the parse found each kind of source
        for rel in sources:
            with self.subTest(rel):
                self.assertTrue(install_state.managed(rel), rel)

    def test_no_tmux_path_matches_a_source_glob(self):
        # setup-tmux.sh's links are its own: setup.sh's prune and hold leave them alone.
        tmux = [os.path.relpath(p, REPO) for p in glob.glob(os.path.join(REPO, "tmux", "*"))]
        with open(os.path.join(REPO, "setup-tmux.sh")) as f:
            tmux += re.findall(r'^link "\$REPO_DIR/([^"]+)"', f.read(), re.M)
        self.assertIn("tmux/pass-last", tmux)
        for rel in tmux:
            with self.subTest(rel):
                self.assertFalse(install_state.managed(rel), rel)

    def test_setup_installs_the_merged_settings_and_the_block(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            text = f.read()
        self.assertIn('merge-settings.py" --checkout "$REPO_DIR" "$REPO_DIR/settings.json"', text)
        self.assertIn('"$CLAUDE_DIR/settings.machine.json" "$CLAUDE_DIR/settings.json" > '
                      '"$MERGED_SETTINGS"', text)  # live keys kept
        self.assertIn('copy_managed "$MERGED_SETTINGS" "$CLAUDE_DIR/settings.json"', text)
        self.assertNotIn('copy_managed "$REPO_DIR/settings.json"', text)
        self.assertIn('git/install-ignore.py" "$REPO_DIR/git/sandbox-stubs.ignore"', text)

    def test_the_top_level_scripts_run_their_python_isolated(self):
        # The top-level scripts run outside the sandbox (setup*.sh, sync.sh), and the repo root
        # isn't in denyWrite (only its files and subdirs are), so every Python they start runs
        # isolated: no import path from the cwd, the script's dir or the environment.
        scripts = sorted(os.path.basename(p) for p in glob.glob(os.path.join(REPO, "*.sh")))
        self.assertEqual(scripts, ["setup-chrome-wsl.sh", "setup-tmux.sh", "setup.sh", "sync.sh"])
        calls = {}
        for name in scripts:
            with open(os.path.join(REPO, name)) as f:
                bad, ok, unclosed = python_lines(f.read(), PYTHON_NON_CALLS.get(name, ()))
            with self.subTest(name):
                self.assertEqual(bad, [])
                self.assertIsNone(unclosed)  # every heredoc ended, so nothing after it was skipped
            calls[name] = ok
        # The scan reached each kind of call, past every heredoc.
        self.assertIn('python3 -I "$REPO_DIR/install-state.py" hold "$REPO_DIR" || hold=$?',
                      calls["setup.sh"])
        self.assertIn('python3 -I "$REPO_DIR/install-state.py" plugins '
                      '|| warn "the plugin change check failed (see above)"', calls["setup.sh"])
        self.assertEqual(len(calls["setup.sh"]), 12)
        self.assertEqual(len(calls["sync.sh"]), 2)
        self.assertEqual(len(calls["setup-tmux.sh"]), 2)  # swap_in's os.replace and the .tmux.conf write

    def test_the_isolation_scan_flags_every_other_way_to_start_python(self):
        planted = [
            "python3 <<'PY'", "python3 ./x.py", "python3 ~/x.py", "python3.12 -I x.py",
            "python x.py", 'PY="$(command -v python3)"', '"$PY" "$REPO_DIR/x.py"',
            '"$REPO_DIR/x.py" --flag', "./tool.py", "python3 -I x.py | python3 y.py",
            "if python3 x.py; then :; fi", "python3 -c 'import x'", "exec python3 x.py",
            "python3 -I \"$a\" && ./tool.py", "python3 -I - \"$a\" | sh -c 'python x'",
            "python3 -I \"$a\"; \"$REPO_DIR/x.py\"", "python3 -I \"$a\" \"$(python3 y)\"",
        ]
        for line in planted:
            with self.subTest(line):
                bad, _, _ = python_lines(line + "\nPY\n", ())
                self.assertEqual(bad, [line])
        # A comment doesn't continue, so the call after a `# note \` line is its own line.
        self.assertEqual(python_lines("# note \\\npython3 x.py\n", ()), (["python3 x.py"], [], None))
        text = ("python3 -I - \"$A\" <<'PY'\nimport os  # python x.py inside the heredoc\nPY\n"
                "cat <<EOF\n  needs python3 on PATH\nEOF\n"
                "command -v python3 >/dev/null\n"
                'python3 -I "$REPO_DIR/merge.py" \\\n  "$B" > "$C"\n')
        bad, ok, unclosed = python_lines(text, ("command -v python3 >/dev/null",))
        self.assertEqual(bad, [])
        self.assertEqual(ok, ["python3 -I - \"$A\" <<'PY'",
                              'python3 -I "$REPO_DIR/merge.py" "$B" > "$C"'])
        self.assertIsNone(unclosed)
        self.assertEqual(python_lines("python3 -I - <<'PY'\nimport os\n", ())[2], "PY")
        self.assertEqual(python_lines("sed -n '/<<< x <<</p' f\npython3 y.py\n", ()),
                         (["python3 y.py"], [], None))

    def test_python_started_through_sys_executable_runs_isolated(self):
        roots = [os.path.join(REPO, "hooks"), os.path.join(REPO, "bin")]
        roots += glob.glob(os.path.join(REPO, "skills", "*", "scripts"))
        seen = set()
        for root in roots:
            for dirpath, _, files in os.walk(root):
                for name in files:
                    path = os.path.join(dirpath, name)
                    rel = os.path.relpath(path, REPO)
                    with open(path, "rb") as f:
                        text = f.read().decode("utf-8", "replace")
                    if "sys.executable" not in text:
                        continue
                    seen.add(rel)
                    calls = unisolated_executable_calls(text)
                    with self.subTest(rel):
                        if rel in EXECUTABLE_EXCEPTIONS:
                            self.assertTrue(calls, f"{rel} is isolated now: drop its exception")
                        else:
                            self.assertEqual(calls, [])
        # The walk reached each kind of caller, and every exception still names a file.
        for rel in ("skills/delegation/scripts/delegation_checks.py",
                    "skills/delegation/scripts/watch-guard", "skills/lanes/scripts/lane",
                    "skills/pass/scripts/pass-respawn", *EXECUTABLE_EXCEPTIONS):
            self.assertIn(rel, seen)

    def test_the_executable_scan_flags_a_call_without_isolation(self):
        for text in ("subprocess.run([sys.executable, x])", "run([sys.executable, '-m', 'y'])",
                     "Popen((sys.executable, LEDGER))", "argv = [sys.executable]",
                     "run([\n    sys.executable, '-u', x])", "run([sys.executable, \"-u\", \"-I\"])"):
            with self.subTest(text):
                self.assertEqual(len(unisolated_executable_calls(text)), 1)
        for text in ("run([sys.executable, \"-I\", x])", "run([ sys.executable , '-I', '-m', y])",
                     "return sys.executable", "print(sys.executable)"):
            with self.subTest(text):
                self.assertEqual(unisolated_executable_calls(text), [])

    def test_codex_gets_the_portable_skills_and_each_exists(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            line = next(l for l in f if l.startswith("CODEX_SKILLS=("))
        skills = line.strip()[len("CODEX_SKILLS=("):-1].split()
        self.assertEqual(skills, ["coding-practices", "frontend-ui-discipline",
                                  "research-discipline", "ui-alignment", "vetting-sources"])
        for s in skills:
            self.assertTrue(os.path.isfile(os.path.join(REPO, "skills", s, "SKILL.md")), s)


if __name__ == "__main__":
    unittest.main()
