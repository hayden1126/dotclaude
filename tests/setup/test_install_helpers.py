"""setup.sh's two merge helpers: the settings overlay and the git excludes block (stdlib only)."""
import importlib.machinery
import importlib.util
import json
import os
import re
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


class SetupWiring(unittest.TestCase):
    def test_a_hook_removed_from_the_repo_has_its_link_pruned(self):
        # setup.sh's prune_stale_hook_links, run on its own: only a dangling link into this
        # checkout's hooks/ goes; a live link, another repo's dangling link and a file stay.
        with open(os.path.join(REPO, "setup.sh")) as f:
            text = f.read()
        start = text.index("prune_stale_hook_links() {")
        func = text[start:text.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory() as tmp:
            repo, claude = os.path.join(tmp, "repo"), os.path.join(tmp, "claude")
            os.makedirs(os.path.join(repo, "hooks"))
            os.makedirs(os.path.join(claude, "hooks"))
            with open(os.path.join(repo, "hooks", "live.sh"), "w"):
                pass
            hooks = os.path.join(claude, "hooks")
            os.symlink(os.path.join(repo, "hooks", "live.sh"), os.path.join(hooks, "live.sh"))
            os.symlink(os.path.join(repo, "hooks", "gone.sh"), os.path.join(hooks, "gone.sh"))
            os.symlink(os.path.join(tmp, "other", "hooks", "x.sh"), os.path.join(hooks, "x.sh"))
            with open(os.path.join(hooks, "plugin.sh"), "w"):
                pass
            r = subprocess.run(["bash", "-c", 'set -euo pipefail; say() { echo "$*"; }\n'
                                + func + "\nprune_stale_hook_links"],
                               env={**os.environ, "REPO_DIR": repo, "CLAUDE_DIR": claude},
                               capture_output=True, text=True, timeout=20)
            self.assertEqual((r.returncode, r.stdout), (0, "removed stale link hooks/gone.sh\n"))
            self.assertEqual(sorted(os.listdir(hooks)), ["live.sh", "plugin.sh", "x.sh"])

    def test_setup_installs_the_merged_settings_and_the_block(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            text = f.read()
        self.assertIn('merge-settings.py" --checkout "$REPO_DIR" "$REPO_DIR/settings.json"', text)
        self.assertIn('"$CLAUDE_DIR/settings.machine.json" "$CLAUDE_DIR/settings.json" > '
                      '"$MERGED_SETTINGS"', text)  # live keys kept
        self.assertIn('copy_managed "$MERGED_SETTINGS" "$CLAUDE_DIR/settings.json"', text)
        self.assertNotIn('copy_managed "$REPO_DIR/settings.json"', text)
        self.assertIn('git/install-ignore.py" "$REPO_DIR/git/sandbox-stubs.ignore"', text)

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
