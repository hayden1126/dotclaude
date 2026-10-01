"""setup.sh's two merge helpers: the settings overlay and the git excludes block (stdlib only)."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MERGE = os.path.join(REPO, "merge-settings.py")
IGNORE = os.path.join(REPO, "git", "install-ignore.py")


def load(path):
    loader = importlib.machinery.SourceFileLoader(os.path.basename(path).replace("-", "_")[:-3], path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


merge_settings = load(MERGE)
install_ignore = load(IGNORE)


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


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

    def test_a_bad_live_file_fails_and_prints_nothing(self):
        for text in ("{not json", "[1, 2]"):
            with self.subTest(text):
                r = run(MERGE, self.base, self.overlay("{}"), self.live(text))
                self.assertEqual((r.returncode, r.stdout), (1, ""))


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


class SetupWiring(unittest.TestCase):
    def test_setup_installs_the_merged_settings_and_the_block(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            text = f.read()
        self.assertIn('merge-settings.py" "$REPO_DIR/settings.json" "$CLAUDE_DIR/settings.machine.json"', text)
        self.assertIn('"$CLAUDE_DIR/settings.json" > "$MERGED_SETTINGS"', text)  # live keys kept
        self.assertIn('copy_managed "$MERGED_SETTINGS" "$CLAUDE_DIR/settings.json"', text)
        self.assertNotIn('copy_managed "$REPO_DIR/settings.json"', text)
        self.assertIn('git/install-ignore.py" "$REPO_DIR/git/sandbox-stubs.ignore"', text)


if __name__ == "__main__":
    unittest.main()
