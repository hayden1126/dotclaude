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
import shutil
import subprocess
import stat
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
        # So is .git: the tripwire only reads it, and it is lane-writable by design (DA15/DA16).
        with open(os.path.join(REPO, "setup.sh")) as f:
            sources = set(re.findall(r'"?\$REPO_DIR"?/([\w.-]+)', f.read())) - {"templates", ".git"}
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


class VerifiedStoreRules(unittest.TestCase):
    """lane sync-main builds a store only when the live settings.json keep every lane out of it
    (DA15/DA16): its own settings_rules_problem must pass on what setup.sh installs."""

    @staticmethod
    def rules_problem():
        scripts = os.path.join(REPO, "skills", "lanes", "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)  # the CLI imports lanelib beside it
        return load(os.path.join(scripts, "lane")).settings_rules_problem

    def merged(self, d, *args):
        r = run(MERGE, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        path = os.path.join(d, "out.json")
        with open(path, "w") as f:
            f.write(r.stdout)
        return path

    def test_every_install_shape_carries_both_rules(self):
        check = self.rules_problem()
        base = os.path.join(REPO, "settings.json")
        with tempfile.TemporaryDirectory() as d:
            overlay, live = os.path.join(d, "overlay.json"), os.path.join(d, "live.json")
            with open(overlay, "w") as f:  # an overlay with lists of its own at both keys
                json.dump({"permissions": {"deny": ["Edit(~/x/**)"]},
                           "sandbox": {"filesystem": {"denyWrite": ["~/x"]}}}, f)
            with open(live, "w") as f:  # a live file from before the rules
                json.dump({"permissions": {"deny": []}, "model": "opus"}, f)
            lane = os.path.join(d, "lane")
            os.makedirs(lane)
            for args in ([base], [base, overlay], [base, overlay, live],
                         ["--checkout", lane, base, overlay, live]):
                with self.subTest(args=args[:-1]):
                    self.assertIsNone(check(self.merged(d, *args)))

    def test_the_check_fails_without_either_rule(self):
        # The control: the check reads the merged output, not something that always passes.
        check = self.rules_problem()
        with open(os.path.join(REPO, "settings.json")) as f:
            settings = json.load(f)
        with tempfile.TemporaryDirectory() as d:
            for keys, rule in ((("permissions", "deny"), "Edit("),
                               (("sandbox", "filesystem", "denyWrite"), "~/.local/state")):
                s = json.loads(json.dumps(settings))
                at = s
                for k in keys:
                    at = at[k]
                at[:] = [p for p in at if not p.startswith(rule) or "verified" not in p]
                path = os.path.join(d, "s.json")
                with open(path, "w") as f:
                    json.dump(s, f)
                with self.subTest(keys=keys):
                    self.assertIn(keys[-1], check(path))


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


class ModelPin(unittest.TestCase):
    """The baseline pins new sessions' model with env ANTHROPIC_MODEL, which startup reads ahead
    of the `model` key /model saves (probed 2026-10-23, 2.1.309): a /model moves only its own
    session. An overlay's env merges beside the pin, and the live `model` key stays (and stays
    unread)."""

    def test_the_merged_settings_pin_opus_beside_the_overlays_env(self):
        with tempfile.TemporaryDirectory() as d:
            overlay, live = os.path.join(d, "overlay.json"), os.path.join(d, "live.json")
            with open(overlay, "w") as f:
                json.dump({"env": {"FOO": "1"}}, f)
            with open(live, "w") as f:
                json.dump({"model": "sonnet"}, f)
            r = run(MERGE, os.path.join(REPO, "settings.json"), overlay, live)
        self.assertEqual(r.returncode, 0, r.stderr)
        merged = json.loads(r.stdout)
        self.assertEqual((merged["env"]["ANTHROPIC_MODEL"], merged["env"]["FOO"], merged["model"]),
                         ("opus", "1", "sonnet"))

    def test_the_docs_name_the_pin(self):
        for rel in ("README.md", "docs/lanes.md"):
            with self.subTest(doc=rel), open(os.path.join(REPO, rel)) as f:
                self.assertIn("ANTHROPIC_MODEL", f.read())


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

    def test_the_shipped_widget_runs_isolated_and_a_user_s_own_keeps_its_python(self):
        # ccstatusline runs widgets outside the sandbox, so ctx-breakdown.py gets -I (no user
        # site, no PYTHON* env), on a new install and on an earlier one that lacked it, and a
        # rerun leaves it as it is. A user's own widget may need their site-packages.
        exe = re.escape(f'"{sys.executable}"')
        isolated = exe + r' -I "/[^"]+/ccstatusline/ctx-breakdown\.py"'
        dst = self.fresh()
        self.install(dst)
        with open(dst) as f:
            ctx = [w["commandPath"] for line in json.load(f)["lines"] for w in line
                   if "ctx-breakdown" in (w.get("commandPath") or "")]
        self.assertEqual(len(ctx), 1, ctx)
        self.assertRegex(ctx[0], f"^{isolated}$")
        mine = {"id": "42", "type": "custom-command", "commandPath": "python my-widget.py --x"}
        old = dict(self.LINE_1[1], commandPath='"/usr/bin/python3" "/c/ctx-breakdown.py"')
        for _ in range(2):   # an install without -I, then a rerun over this one's output
            lines = self.installed([[self.LINE_1[0], old, self.LINE_1[2]], [mine]])
            self.assertRegex(lines[0][1]["commandPath"], f"^{isolated}$")
            self.assertRegex(lines[1][0]["commandPath"],
                             exe + r' "/[^"]+/ccstatusline/my-widget\.py" --x$')
            old, mine = lines[0][1], lines[1][0]

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


# Lines that name Python without starting it, per script (its path in the repo). Anything else
# that names a Python interpreter or a .py file outside a heredoc body must be a call in the
# strict form.
PYTHON_NON_CALLS = {
    "setup.sh": ('for f in "$REPO_DIR"/hooks/*.sh "$REPO_DIR"/hooks/*.py; do',
                 'for pyf in "$REPO_DIR"/statusline/*.py; do'),
    "setup-tmux.sh": ('command -v python3 >/dev/null || die "python3 not found."',),
    "setup-chrome-wsl.sh": ('command -v python3 >/dev/null || die "python3 not found."',),
    "hooks/practices-check.sh": (  # the message when practices_check.py can't run
        'printf \'{"systemMessage":"practices hooks are down: python3 exited %s running '
        'practices_check.py; edits are not checked"}\\n\' "$rc"',),
    "tmux/pass-last": (  # the reader's paths, run later by a strict call
        'render="${self:+${self%/*}/../hooks/md_render.py}"$\'\\n\'"$HOME/.claude/hooks/md_render.py"',),
}

PYTHON_WORD = r"\bpython[0-9.]*\b"
# What may come before `python3 -I` in its own command: env assignments (-I ignores PYTHON*
# vars), a timeout, exec, if or !.
CALL_PREFIX = r"(?:\w+=(?:\"[^\"]*\"|'[^']*'|\S*)\s+|timeout\s+\d+\s+|exec\s+|if\s+|!\s+)*"


def commands(line):
    """line's commands: each innermost $(...) and <(...) body is taken out as its own command
    line (a placeholder stands in its place), then every line is split at &&, ||, ;, |, & and
    backticks, and at any $( or <( still left (one the regex couldn't pair, like an arithmetic
    $(( or a paren inside quotes)."""
    lines, sub = [], re.compile(r"[$<]\(([^()]*)\)")
    while m := sub.search(line):
        lines.append(m.group(1))
        line = line[:m.start()] + "_SUB_" + line[m.end():]
    return [c for l in [line, *lines] for c in re.split(r"&&|\|\||[;|&`]|\$\(|<\(", l)]


def python_lines(text, non_calls):
    """A shell script's lines that name Python: (bad, ok, unclosed). ok holds the lines whose
    every command naming Python is a call in the strict form: `python3 -I` then a quoted arg or
    `-`, after at most CALL_PREFIX, and Python named once in that command. bad holds every
    other line naming a Python interpreter (python, python3, python3.12) or a .py file, so a
    bare python3, an interpreter in a variable (its assignment names it) and a direct run of a
    .py all land there. Full-line comments are dropped before continuations join (bash doesn't
    continue a comment), heredoc bodies (the Python a call reads, or printed text) are skipped,
    and unclosed is the delimiter of a heredoc still open at the end. Lines are
    whitespace-normalized.

    Known limits (no scanned script does any of these today): a `<<WORD` inside a string or
    an arithmetic `$((x << 2))` opens a heredoc that isn't there (the unclosed check catches one
    that never ends); a trailing `cmd # note \\` reads as a continuation; the lines of a
    multi-line `-c '...'` body are read as shell (a false alarm at worst); and an extensionless
    script run through its shebang, or an interpreter in a variable whose assignment names no
    Python (`"$PYTHON"` from the environment), isn't seen. The shebang test covers the first."""
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
        named = [c for c in commands(line) if re.search(PYTHON_WORD + r"|\.py\b", c)]
        if not named:
            continue
        if all(re.match(r"\s*" + CALL_PREFIX + r"python3 -I [\"'-]", c)
               and len(re.findall(PYTHON_WORD, c)) == 1 for c in named):
            ok.append(line)
        else:
            bad.append(line)
    return bad, ok, delim


def sandbox_off_shell_scripts():
    """Every shell script that runs outside the sandbox, by repo path: the top-level *.sh
    (setup, sync), the hooks, and what tmux, the statusline and excluded commands run (tmux/,
    statusline/, bin/), plus the skills' scripts. A file counts by a .sh name or a sh, bash or
    zsh shebang."""
    out = []
    for pat in ("*.sh", "hooks/*", "bin/*", "tmux/*", "statusline/*", "skills/*/scripts/*"):
        for path in glob.glob(os.path.join(REPO, pat)):
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as f:
                first = f.readline()
            if path.endswith(".sh") or re.match(rb"#!\S*(?:/|\s)(?:ba|z)?sh\b", first):
                out.append(os.path.relpath(path, REPO))
    return sorted(out)


# Every Python script starts through `#!/usr/bin/python3 -I` (env can't pass -I on Linux without
# -S, and a fixed path isn't looked up on a PATH). Many run outside the sandbox: excluded
# commands (lane, delegation-ledger, codex-delegate, pass-respawn), what hooks, tmux and the
# statusline run, and setup's helpers; a new script is covered by default. Each exception is a
# dir or file prefix and why.
ISOLATED_SHEBANG = "#!/usr/bin/python3 -I"
SHEBANG_EXCEPTIONS = {
    "skills/deck-production/scripts/":
        "runs only in sandboxed Bash; its scripts import their siblings through the script's "
        "own dir, which -I drops, and the build may need the user's site-packages",
}


def python_scripts():
    """{repo path: first line} for every file with a Python shebang in the dirs that hold run
    code: the top level, hooks/, bin/, tmux/, statusline/, git/, codex/ and skills/*/scripts/."""
    out = {}
    for pat in ("*", "hooks/*", "bin/*", "tmux/*", "statusline/*", "git/*", "codex/*",
                "skills/*/scripts/*"):
        for path in glob.glob(os.path.join(REPO, pat)):
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as f:
                first = f.readline().decode("utf-8", "replace").rstrip("\n")
            if first.startswith("#!") and re.search(PYTHON_WORD, first):
                out[os.path.relpath(path, REPO)] = first
    return out


# Python a script starts through sys.executable (or a literal "python3") runs isolated (-I),
# like the shell scripts' Python: the cwd or a writable dir never comes first on its import
# path. Each exception is a path and why.
EXECUTABLE_EXCEPTIONS = {
    "skills/deck-production/scripts/parity_check.py":
        "runs the deck build scripts in the sandbox, and they may need the user's "
        "site-packages, which -I drops",
}
EXECUTABLE_HEAD = r"(?:sys\.executable|[\"'](?:/usr/bin/)?python[0-9.]*[\"'])"


def unisolated_executable_calls(text):
    """The lines that start Python without -I as the first argument: a list or tuple that
    begins with sys.executable or a literal python3 (or python, /usr/bin/python3) and whose
    next item isn't "-I"."""
    return [m.group(0) for m in re.finditer(rf"(?:\[\s*{EXECUTABLE_HEAD}\s*[,\]]|"
                                            rf"\(\s*{EXECUTABLE_HEAD}\s*,)[^\n]*", text)
            if not re.match(rf"[\[(]\s*{EXECUTABLE_HEAD}\s*,\s*[\"']-I[\"']", m.group(0))]


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
        self.assertIn('python3 -I - "$CLAUDE_DIR/settings.json" 2>/dev/null <<\'PY\' || true',
                      calls["setup.sh"])  # section 2's check of the settings it replaces
        self.assertIn('python3 -I "$REPO_DIR/skills/lanes/scripts/lanelib.py" git-tamper '
                      '"$common" >&2 || tamper=$?', calls["setup.sh"])
        self.assertIn('python3 -I - "$lane_cli" "$CLAUDE_DIR/settings.json" "$HOME" '
                      '<<\'PY\' || verified_window=1', calls["setup.sh"])  # the window's check
        self.assertIn('python3 -I - "$lane_cli" "$HOME" <<\'PY\' || demoted=$?',
                      calls["setup.sh"])  # its demotion
        self.assertEqual(len(calls["setup.sh"]), 16)
        self.assertEqual(len(calls["sync.sh"]), 2)
        self.assertEqual(len(calls["setup-tmux.sh"]), 2)  # swap_in's os.replace and the .tmux.conf write
        self.assertEqual(len(calls["setup-chrome-wsl.sh"]), 2)  # the plugin version and the config merge

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
        # A call later in a pipe, inside a substitution or after a prefix is held to the same
        # form, and so is every other command on the line.
        for line in ('python3 "$policy" || {', "timeout 8 python3 x.py", 'printf x | python3 "$a"',
                     'A="$(f)" python3 x', 'out=$(printf x | python3 "$a")',
                     'out=$(python3 -I "$(python3 -c 1)")', 'exec {fd}< <(python3 "$a")',
                     'A="$(python3 y)" python3 -I "$a"', 'sudo python3 -I "$a"'):
            with self.subTest(line):
                self.assertEqual(python_lines(line + "\n", ())[0], [line])
        for line in ('printf \'%s\' "$i" | python3 -I "$a"', 'out=$(printf x | timeout 12 python3 -I "$a")',
                     'A="$(age "$t")" B=1 python3 -I -c "$x" 2>/dev/null',
                     'if out=$(python3 -I "$(dirname "$(readlink -f "$0")")/m.py" check) && [[ y ]]; then',
                     'exec {fd}< <(printf \'%s\' "$i" | timeout 12 python3 -I "$here/w.py" 2>/dev/null)'):
            with self.subTest(line):
                self.assertEqual(python_lines(line + "\n", ()), ([], [line], None))

    def test_every_sandbox_off_shell_script_runs_its_python_isolated(self):
        # Hooks, tmux scripts and the statusline run outside the sandbox, so does every Python
        # they start, and a bare python3 loads the user site and PYTHON* env (DA17).
        scripts = sandbox_off_shell_scripts()
        calls = {}
        for rel in scripts:
            with open(os.path.join(REPO, rel)) as f:
                bad, ok, unclosed = python_lines(f.read(), PYTHON_NON_CALLS.get(rel, ()))
            with self.subTest(rel):
                self.assertEqual(bad, [])
                self.assertIsNone(unclosed)
            calls[rel] = ok
        # The scan reached each kind of script and call, and every non-call names a file.
        for rel in ("hooks/subagent-policy.sh", "hooks/agent-spawn-guard.sh", "hooks/report-check.sh",
                    "hooks/watch-guard.sh", "hooks/delegation-due.sh", "hooks/delegation-ledger.sh",
                    "hooks/notify.sh", "hooks/session-pane.sh", "hooks/tmux-state.sh",
                    "hooks/stop-ring.sh", "tmux/tmux-claude-status", "tmux/claude-restore"):
            with self.subTest(rel):
                self.assertTrue(calls.get(rel), rel)
        self.assertIn("bin/npx", scripts)
        for rel in PYTHON_NON_CALLS:
            self.assertIn(rel, scripts)

    def test_every_python_script_starts_isolated(self):
        scripts = python_scripts()
        for rel, first in sorted(scripts.items()):
            with self.subTest(rel):
                if any(rel.startswith(p) for p in SHEBANG_EXCEPTIONS):
                    continue
                self.assertEqual(first, ISOLATED_SHEBANG)
        # The scan reached each kind of script, and every exception still holds one.
        for rel in ("skills/lanes/scripts/lane", "skills/delegation/scripts/delegation-ledger",
                    "skills/delegation/scripts/codex-delegate", "skills/handoff/scripts/handoff-check",
                    "skills/delegation/scripts/subagent-policy", "skills/pass/scripts/pass-respawn",
                    "statusline/ctx-breakdown.py", "tmux/tmux-tab-bar", "bin/claude-file-history",
                    "merge-settings.py", "git/install-ignore.py", "codex/merge-config.py"):
            self.assertIn(rel, scripts)
        for prefix in SHEBANG_EXCEPTIONS:
            self.assertTrue(any(r.startswith(prefix) and f != ISOLATED_SHEBANG
                                for r, f in scripts.items()), f"{prefix}: drop its exception")

    def test_the_settings_hook_commands_run_python_isolated(self):
        # Claude Code runs every hook command and the status line outside the sandbox.
        with open(os.path.join(REPO, "settings.json")) as f:
            settings = json.load(f)
        cmds = [h["command"] for groups in settings["hooks"].values() for g in groups
                for h in g["hooks"] if h.get("type") == "command"]
        cmds.append(settings["statusLine"]["command"])
        self.assertGreater(len(cmds), 20)
        for cmd in cmds:
            with self.subTest(cmd):
                self.assertEqual(python_lines(cmd + "\n", ())[0], [])

    def test_python_started_through_sys_executable_runs_isolated(self):
        roots = [os.path.join(REPO, d) for d in ("hooks", "bin", "tmux", "statusline", "git", "codex")]
        roots += glob.glob(os.path.join(REPO, "skills", "*", "scripts"))
        paths = [os.path.join(d, n) for root in roots for d, _, names in os.walk(root)
                 for n in names]
        paths += glob.glob(os.path.join(REPO, "*.py"))
        seen = set()
        for path in paths:
            rel = os.path.relpath(path, REPO)
            with open(path, "rb") as f:
                text = f.read().decode("utf-8", "replace")
            if not re.search(EXECUTABLE_HEAD, text):
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
                     "run([\n    sys.executable, '-u', x])", "run([sys.executable, \"-u\", \"-I\"])",
                     "run([\"python3\", x])", "Popen(('python3', '-c', s))",
                     "run([\"/usr/bin/python3\", x])", "argv = ['python']"):
            with self.subTest(text):
                self.assertEqual(len(unisolated_executable_calls(text)), 1)
        for text in ("run([sys.executable, \"-I\", x])", "run([ sys.executable , '-I', '-m', y])",
                     "return sys.executable", "print(sys.executable)", "run([\"python3\", \"-I\", x])",
                     "names = (\"python3\")", "which(\"python3\")"):
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


class VerifiedStoreDir(unittest.TestCase):
    """setup.sh makes ~/.local/state/dotclaude/verified (0700), the stores' dir settings.json
    denies to every lane, before anything else could (DA15/DA16): a link or a non-dir there
    stops the run. HOME points at a temp dir."""

    MARK = "# lane sync-main's stores' dir"
    END = "\n# The window (Hayden's pick"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.verified = os.path.join(self.home, ".local", "state", "dotclaude", "verified")

    def run_block(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            src = f.read()
        self.assertIn(self.MARK, src)
        block = self.MARK + src.split(self.MARK, 1)[1].split(self.END, 1)[0]
        # XDG_STATE_HOME elsewhere: the dir goes where the settings rules name it, below HOME.
        env = {"HOME": self.home, "PATH": "/usr/bin:/bin",
               "XDG_STATE_HOME": os.path.join(self.home, "xdg")}
        return subprocess.run(["bash", "-c", 'set -euo pipefail; say() { echo "$*"; }\n'
                               'warn() { echo "!! $*" >&2; }\n' + block],
                              env=env, capture_output=True, text=True, timeout=30)

    def test_it_makes_the_dir_0700(self):
        for _ in range(2):
            p = self.run_block()
            self.assertEqual(p.returncode, 0, p.stderr)
            st = os.lstat(self.verified)
            self.assertTrue(stat.S_ISDIR(st.st_mode))
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o700)

    def test_a_looser_dir_is_tightened(self):
        os.makedirs(self.verified, mode=0o755)
        os.chmod(self.verified, 0o755)
        self.assertEqual(self.run_block().returncode, 0)
        self.assertEqual(stat.S_IMODE(os.lstat(self.verified).st_mode), 0o700)

    def test_a_link_or_a_file_there_refuses(self):
        outside = os.path.join(self.home, "outside")
        os.makedirs(outside, mode=0o755)
        os.makedirs(os.path.dirname(self.verified))
        for plant in (lambda: os.symlink(outside, self.verified),
                      lambda: os.symlink(os.path.join(self.home, "nowhere"), self.verified),
                      lambda: open(self.verified, "w").close()):
            plant()
            with self.subTest(plant=os.readlink(self.verified)
                              if os.path.islink(self.verified) else "file"):
                p = self.run_block()
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertIn("verified", p.stderr)
                self.assertFalse(os.path.isdir(os.path.join(self.home, "nowhere")))
                self.assertEqual(stat.S_IMODE(os.stat(outside).st_mode), 0o755)
            os.unlink(self.verified)


class VerifiedWindow(unittest.TestCase):
    """The window (Hayden's pick, 2026-11-03): when the live settings.json this install replaces
    lacks either stores' rule, any lane could write the stores' dir, so once the new settings are
    in, every marker there goes pending (lane's demote_marks, tested in tests/lanes). Here: the
    detection before the settings copy, the demotion after it, and the flag between the two.
    HOME points at a temp dir; the copy is a stand-in that writes settings with the rules."""

    DETECT = "# The window (Hayden's pick"
    DETECT_END = '\nmkdir -p "$CLAUDE_DIR"'
    DEMOTE = "if [[ $verified_window -eq 1"
    DEMOTE_END = '\nlink "$REPO_DIR/CLAUDE.md"'
    RULES = {"permissions": {"deny": ["Edit(~/.local/state/dotclaude/verified/**)"]},
             "sandbox": {"filesystem": {"denyWrite": ["~/.local/state/dotclaude/verified"]}}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.realpath(tmp.name)
        self.claude = os.path.join(self.home, ".claude")
        os.makedirs(self.claude)
        self.verified = os.path.join(self.home, ".local", "state", "dotclaude", "verified")
        self.marks = os.path.join(self.verified, "new-lanes")
        os.makedirs(self.marks, mode=0o700)
        self.flag = os.path.join(self.verified, ".demote-pending")
        with open(os.path.join(REPO, "setup.sh")) as f:
            src = f.read()
        self.detect = self.DETECT + src.split(self.DETECT, 1)[1].split(self.DETECT_END, 1)[0]
        self.demote = self.DEMOTE + src.split(self.DEMOTE, 1)[1].split(self.DEMOTE_END, 1)[0]

    def live(self, data):
        with open(os.path.join(self.claude, "settings.json"), "w") as f:
            json.dump(data, f)

    def mark(self, name="k-chart-fix.json", verified=True):
        path = os.path.join(self.marks, name)
        with open(path, "w") as f:
            json.dump({"id": "chart-fix", "common": "/x", "verified": verified}, f)
        return path

    def run_setup(self, stop_after_detect=False):
        copy = f"cat > \"$CLAUDE_DIR/settings.json\" <<'J'\n{json.dumps(self.RULES)}\nJ\n"
        script = ('set -euo pipefail; say() { echo "$*"; }\nwarn() { echo "!! $*" >&2; }\n'
                  f'verified_dir="{self.verified}"\n' + self.detect + "\n"
                  + ("exit 0\n" if stop_after_detect else copy + self.demote))
        env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "REPO_DIR": REPO,
               "CLAUDE_DIR": self.claude}
        return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True,
                              timeout=60)

    def verified_field(self, path):
        with open(path) as f:
            return json.load(f)["verified"]

    def test_settings_without_a_rule_demote_every_marker(self):
        for live in ({}, {"permissions": self.RULES["permissions"]},
                     {"sandbox": self.RULES["sandbox"]}):
            with self.subTest(live=live):
                path = self.mark()
                self.live(live)
                p = self.run_setup()
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIs(self.verified_field(path), False)
                self.assertIn("k-chart-fix.json", p.stderr)
                self.assertIn("lane done <id> --abandon", p.stderr)
                self.assertFalse(os.path.lexists(self.flag))

    def test_settings_with_both_rules_touch_nothing(self):
        path = self.mark()
        self.live(self.RULES)
        p = self.run_setup()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIs(self.verified_field(path), True)
        self.assertEqual(p.stderr, "")

    def test_a_run_stopped_after_detection_demotes_on_the_next(self):
        path = self.mark()
        self.live({})
        self.assertEqual(self.run_setup(stop_after_detect=True).returncode, 0)
        self.assertTrue(os.path.isfile(self.flag))
        self.live(self.RULES)  # the stopped run's copy landed, say, but not its demotion
        p = self.run_setup()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIs(self.verified_field(path), False)
        self.assertFalse(os.path.lexists(self.flag))

    def test_a_link_at_the_flag_is_never_written_through(self):
        victim = os.path.join(self.home, "victim")
        with open(victim, "w") as f:
            f.write("mine\n")
        os.symlink(victim, self.flag)
        path = self.mark()
        self.live({})
        p = self.run_setup()
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(victim) as f:
            self.assertEqual(f.read(), "mine\n")
        self.assertIs(self.verified_field(path), False)
        self.assertFalse(os.path.lexists(self.flag))

    def test_a_dir_at_the_flag_never_stops_the_install(self):
        # Review round 14: `rm -f` on a dir a lane made there failed under set -e, every run.
        os.makedirs(os.path.join(self.flag, "sub"))
        path = self.mark()
        self.live({})
        p = self.run_setup()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIs(self.verified_field(path), False)
        self.assertFalse(os.path.lexists(self.flag))
        os.makedirs(self.flag)  # and one made after an earlier window, with the rules in
        self.live(self.RULES)
        p = self.run_setup()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.lexists(self.flag))

    def test_a_failed_demotion_warns_and_keeps_the_flag(self):
        locked = os.path.join(self.marks, "k-a.json", "locked")
        os.makedirs(os.path.join(locked, "x"))
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o700)
        path = self.mark("k-z.json")
        self.live({})
        p = self.run_setup()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("keep refusing while .demote-pending is there", p.stderr)
        self.assertIs(self.verified_field(path), False)
        self.assertTrue(os.path.isfile(self.flag))

    def test_detection_comes_before_the_settings_copy_and_demotion_after(self):
        # The blocks run here in the test's own order: this pins setup.sh's.
        with open(os.path.join(REPO, "setup.sh")) as f:
            src = f.read()
        copy = src.index('copy_managed "$MERGED_SETTINGS" "$CLAUDE_DIR/settings.json"')
        self.assertLess(src.index(self.DETECT), copy)
        self.assertLess(copy, src.index(self.DEMOTE))

    def test_a_window_with_no_markers_says_nothing(self):
        self.live({})
        p = self.run_setup()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")


class RecurseSubmodulesOff(unittest.TestCase):
    """setup.sh's block at the end of section 4 sets fetch.recurseSubmodules false in the global
    git config (excluded-guard G-B) on every run, and warns when submodule.recurse is on there.
    HOME points at a temp dir."""

    MARK = "# git: no submodule recursion"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.gitconfig = os.path.join(self.home, ".gitconfig")

    def block(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            src = f.read()
        section4 = src.split("\n# 4. ", 1)[1].split("\n# 5. ", 1)[0]
        self.assertIn(self.MARK, section4)
        return self.MARK + section4.split(self.MARK, 1)[1].rsplit("\n# ---", 1)[0]

    def run_block(self):
        env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1"}
        p = subprocess.run(["bash", "-c", 'set -euo pipefail; say() { echo "$*"; }\n'
                            'warn() { echo "!! $*"; }\n' + self.block()],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def values(self):
        p = subprocess.run(["git", "config", "--file", self.gitconfig, "--get-all",
                            "fetch.recurseSubmodules"], capture_output=True, text=True)
        return p.stdout.split()

    def test_it_sets_it_on_every_run(self):
        for _ in range(2):
            out = self.run_block()
            self.assertIn("set fetch.recurseSubmodules false", out)
            self.assertNotIn("already", out)
            self.assertEqual(self.values(), ["false"])

    def test_another_value_is_replaced(self):
        for value in ("true", "on-demand"):
            with self.subTest(value=value):
                with open(self.gitconfig, "w") as f:
                    f.write(f"[fetch]\n\trecurseSubmodules = {value}\n"
                            "[fetch]\n\trecurseSubmodules = yes\n[user]\n\tname = me\n")
                self.assertIn("set fetch.recurseSubmodules false", self.run_block())
                self.assertEqual(self.values(), ["false"])
                with open(self.gitconfig) as f:
                    self.assertIn("name = me", f.read())

    def test_a_false_value_from_an_include_is_written_directly(self):
        # The guard doesn't count an includeIf file, whose condition it doesn't evaluate.
        inc = os.path.join(self.home, "off")
        with open(inc, "w") as f:
            f.write("[fetch]\n\trecurseSubmodules = false\n")
        with open(self.gitconfig, "w") as f:
            f.write(f'[includeIf "gitdir:/"]\n\tpath = {inc}\n')
        self.assertIn("set fetch.recurseSubmodules false", self.run_block())
        self.assertEqual(self.values(), ["false"])

    def test_it_warns_when_submodule_recurse_is_on(self):
        with open(self.gitconfig, "w") as f:
            f.write("[submodule]\n\trecurse = yes\n")
        out = self.run_block()
        self.assertIn("submodule.recurse is true", out)
        self.assertIn("git config --global submodule.recurse false", out)
        with open(self.gitconfig, "w") as f:
            f.write("[submodule]\n\trecurse = false\n")
        self.assertNotIn("submodule.recurse", self.run_block())


class ReplaceRefsOff(RecurseSubmodulesOff):
    """setup.sh sets core.useReplaceRefs false in the global git config on every run, beside
    G-B's key (DA15/DA16). The base class's tests run this block too, since G-B's block reaches
    the end of section 4."""

    MARK = "# git: no replace refs"

    def values(self):
        p = subprocess.run(["git", "config", "--file", self.gitconfig, "--get-all",
                            "core.useReplaceRefs"], capture_output=True, text=True)
        return p.stdout.split()

    def test_it_sets_it_on_every_run(self):
        for _ in range(2):
            self.assertIn("set core.useReplaceRefs false", self.run_block())
            self.assertEqual(self.values(), ["false"])

    def test_another_value_is_replaced(self):
        with open(self.gitconfig, "w") as f:
            f.write("[core]\n\tuseReplaceRefs = true\n[core]\n\tuseReplaceRefs = yes\n"
                    "[user]\n\tname = me\n")
        self.assertIn("set core.useReplaceRefs false", self.run_block())
        self.assertEqual(self.values(), ["false"])
        with open(self.gitconfig) as f:
            self.assertIn("name = me", f.read())

    def test_a_false_value_from_an_include_is_written_directly(self):
        inc = os.path.join(self.home, "off")
        with open(inc, "w") as f:
            f.write("[core]\n\tuseReplaceRefs = false\n")
        with open(self.gitconfig, "w") as f:
            f.write(f'[includeIf "gitdir:/"]\n\tpath = {inc}\n')
        self.assertIn("set core.useReplaceRefs false", self.run_block())
        self.assertEqual(self.values(), ["false"])

    def test_it_warns_when_submodule_recurse_is_on(self):
        pass  # G-B's own test; this block has no warning


class AutoMaintenanceOff(RecurseSubmodulesOff):
    """setup.sh sets gc.auto 0 and maintenance.auto false in the global git config on every run
    (LR3): a fetch, pull or commit outside the sandbox would otherwise run `gc --auto`, whose
    `git worktree prune` deletes through whatever a lane planted under <common>/worktrees/."""

    MARK = "# git: no automatic maintenance"
    KEYS = {"gc.auto": "0", "maintenance.auto": "false"}

    def values(self):
        return {k: subprocess.run(["git", "config", "--file", self.gitconfig, "--get-all", k],
                                  capture_output=True, text=True).stdout.split()
                for k in self.KEYS}

    def want(self):
        return {k: [v] for k, v in self.KEYS.items()}

    def test_it_sets_it_on_every_run(self):
        for _ in range(2):
            out = self.run_block()
            for k, v in self.KEYS.items():
                self.assertIn(f"set {k} {v} globally", out)
            self.assertEqual(self.values(), self.want())

    def test_another_value_is_replaced(self):
        with open(self.gitconfig, "w") as f:
            f.write("[gc]\n\tauto = 6700\n[gc]\n\tauto = 1\n[maintenance]\n\tauto = true\n"
                    "[user]\n\tname = me\n")
        self.run_block()
        self.assertEqual(self.values(), self.want())
        with open(self.gitconfig) as f:
            self.assertIn("name = me", f.read())

    def test_a_false_value_from_an_include_is_written_directly(self):
        inc = os.path.join(self.home, "off")
        with open(inc, "w") as f:
            f.write("[gc]\n\tauto = 0\n[maintenance]\n\tauto = false\n")
        with open(self.gitconfig, "w") as f:
            f.write(f'[includeIf "gitdir:/"]\n\tpath = {inc}\n')
        self.run_block()
        self.assertEqual(self.values(), self.want())

    def test_it_warns_when_submodule_recurse_is_on(self):
        pass  # G-B's own test; this block has no warning


class TamperRefusal(unittest.TestCase):
    """setup.sh's section 0 stops the run before changing anything when lanelib.git_tamper finds
    anything in the common dir of the checkout it installs from, or git can't name that dir
    (DA15/DA16). REPO_DIR is a throwaway repo holding a copy of lanelib.py."""

    MARK = "# The DA15/DA16 tripwire"
    END = "# A lane installs from its own worktree"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.tmp, "repo")
        self.env = {"HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1",
                    "PATH": os.path.dirname(sys.executable) + ":/usr/bin:/bin"}
        subprocess.run(["git", "init", "-q", self.repo], env=self.env, check=True)
        scripts = os.path.join(self.repo, "skills", "lanes", "scripts")
        os.makedirs(scripts)
        with open(os.path.join(REPO, "skills", "lanes", "scripts", "lanelib.py")) as src, \
                open(os.path.join(scripts, "lanelib.py"), "w") as dest:
            dest.write(src.read())

    def run_block(self, repo_dir=None):
        with open(os.path.join(REPO, "setup.sh")) as f:
            src = f.read()
        section0 = src.split("\n# 0. ", 1)[1].split("\n# 1. ", 1)[0]
        self.assertIn(self.MARK, section0)
        block = self.MARK + section0.split(self.MARK, 1)[1].split(self.END, 1)[0]
        return subprocess.run(["bash", "-c", 'set -euo pipefail; say() { echo "$*"; }\n'
                               'warn() { echo "!! $*" >&2; }\n' + block + "\necho went on\n"],
                              env=dict(self.env, REPO_DIR=repo_dir or self.repo),
                              capture_output=True, text=True, timeout=60)

    def test_a_clean_common_dir_goes_on(self):
        p = self.run_block()
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "went on\n", ""))

    def test_a_finding_stops_the_run(self):
        with open(os.path.join(self.repo, ".git", "shallow"), "w"):
            pass
        p = self.run_block()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("went on", p.stdout)
        self.assertIn("shallow exists", p.stderr)
        self.assertIn("stopped before changing anything", p.stderr)

    def test_a_planted_commondir_naming_a_clean_dir_stops_the_run(self):
        # git honours a commondir file in any git dir, the main checkout's .git too, so git's own
        # answer names the clean dir and a check of it passes. A checkout whose .git is a dir is
        # checked there, where the commondir file is a finding.
        clean = os.path.join(self.tmp, "clean.git")
        subprocess.run(["git", "init", "-q", "--bare", clean], env=self.env, check=True)
        with open(os.path.join(self.repo, ".git", "commondir"), "w") as f:
            f.write(clean + "\n")
        named = subprocess.run(["git", "-C", self.repo, "rev-parse", "--path-format=absolute",
                                "--git-common-dir"], env=self.env, capture_output=True, text=True)
        self.assertEqual(os.path.realpath(named.stdout.strip()), clean)  # git follows it
        p = self.run_block()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("went on", p.stdout)
        self.assertIn("commondir", p.stderr)
        self.assertIn("stopped before changing anything", p.stderr)

    def test_a_worktree_is_checked_where_git_names_its_common_dir(self):
        # A lane worktree's .git is a gitfile: the common dir git names is checked.
        env = dict(self.env, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["git", "-C", self.repo, "add", "skills"], env=env, check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "c"], env=env, check=True)
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", wt], env=env, check=True)
        p = self.run_block(repo_dir=wt)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "went on\n", ""))
        with open(os.path.join(self.repo, ".git", "shallow"), "w"):
            pass
        p = self.run_block(repo_dir=wt)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("shallow", p.stderr)

    def test_a_worktree_whose_commondir_names_another_dir_stops_the_run(self):
        # git's answer for a worktree comes from <common>/worktrees/<id>/commondir, which a lane
        # can rewrite: it must be the gitfile's admin dir's grandparent, the real common dir.
        env = dict(self.env, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["git", "-C", self.repo, "add", "skills"], env=env, check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "c"], env=env, check=True)
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", wt], env=env, check=True)
        with open(os.path.join(self.repo, ".git", "shallow"), "w"):
            pass  # a finding in the real common dir, which the redirect hides
        clean = os.path.join(self.tmp, "clean.git")
        subprocess.run(["git", "init", "-q", "--bare", clean], env=self.env, check=True)
        with open(os.path.join(self.repo, ".git", "worktrees", "wt", "commondir"), "w") as f:
            f.write(clean + "\n")
        named = subprocess.run(["git", "-C", wt, "rev-parse", "--path-format=absolute",
                                "--git-common-dir"], env=self.env, capture_output=True, text=True)
        self.assertEqual(os.path.realpath(named.stdout.strip()), clean)  # git follows it
        p = self.run_block(repo_dir=wt)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("went on", p.stdout)
        self.assertIn("stopped before changing anything", p.stderr)

    def test_a_linked_admin_dir_naming_a_decoy_stops_the_run(self):
        # A lane swaps <common>/worktrees/wt for a link to a decoy admin dir inside a clean
        # repo, whose commondir names that repo: git's answer and a resolved `$admin/../..`
        # agree on the decoy. The grandparent is taken from the gitfile's text instead, and a
        # link at worktrees/<id> is a git-tamper finding there.
        env = dict(self.env, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["git", "-C", self.repo, "add", "skills"], env=env, check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "c"], env=env, check=True)
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", wt], env=env, check=True)
        with open(os.path.join(self.repo, ".git", "shallow"), "w"):
            pass  # a finding in the real common dir, which the decoy hides
        clean = os.path.join(self.tmp, "clean.git")
        subprocess.run(["git", "init", "-q", "--bare", clean], env=self.env, check=True)
        admin = os.path.join(self.repo, ".git", "worktrees", "wt")
        decoy = os.path.join(clean, "worktrees", "wt")
        shutil.copytree(admin, decoy)
        with open(os.path.join(decoy, "commondir"), "w") as f:
            f.write("../..\n")
        shutil.rmtree(admin)
        os.symlink(decoy, admin)
        named = subprocess.run(["git", "-C", wt, "rev-parse", "--path-format=absolute",
                                "--git-common-dir"], env=self.env, capture_output=True, text=True)
        self.assertEqual(os.path.realpath(named.stdout.strip()), clean)  # git follows it
        p = self.run_block(repo_dir=wt)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("went on", p.stdout)
        self.assertIn("stopped before changing anything", p.stderr)
        # git's answer the real common dir, but the admin dir still a link: a finding.
        with open(os.path.join(decoy, "commondir"), "w") as f:
            f.write(os.path.join(self.repo, ".git") + "\n")
        os.unlink(os.path.join(self.repo, ".git", "shallow"))
        p = self.run_block(repo_dir=wt)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("worktrees/wt is a symlink", p.stderr)

    def test_a_dir_git_cant_place_stops_the_run(self):
        p = self.run_block(repo_dir=os.path.join(self.tmp, "not-a-repo"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("went on", p.stdout)
        self.assertIn("stopped before changing anything", p.stderr)


if __name__ == "__main__":
    unittest.main()
