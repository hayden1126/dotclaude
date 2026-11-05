"""bin/deny-coverage: what it finds from each kind of path, under a fake home and PATH."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "bin", "deny-coverage")


class DenyCoverage(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.bin = self.mk(".local/bin")
        self.deny = ["Edit(~/.local/**)"]

    def mk(self, rel):
        path = os.path.join(self.home, rel)
        os.makedirs(path, exist_ok=True)
        return path

    def write(self, rel, text="", mode=0o755):
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def link(self, target, name):
        os.symlink(os.path.join(self.home, target), os.path.join(self.bin, name))

    def run_it(self, path=None, deny=None, extra=()):
        settings = os.path.join(self.home, "s.json")
        with open(settings, "w") as f:
            json.dump({"permissions": {"deny": self.deny if deny is None else deny}}, f)
        env = {"HOME": self.home, "PATH": path or self.bin}
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--settings", settings, *extra],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_a_covered_home_reports_nothing(self):
        self.write(".local/bin/tool", "#!/bin/sh\n")
        self.assertEqual(self.run_it(), "")

    def test_a_link_target_outside_the_rules(self):
        self.write(".newtool/current/bin/tool", "#!/bin/sh\n")
        self.link(".newtool/current/bin/tool", "tool")
        self.assertIn('"Edit(~/.newtool/**)"', self.run_it())

    def test_a_link_target_a_rule_covers(self):
        self.write(".newtool/bin/tool", "#!/bin/sh\n")
        self.link(".newtool/bin/tool", "tool")
        self.assertEqual(self.run_it(deny=[*self.deny, "Edit(~/.newtool/**)"]), "")

    def test_the_interpreter_in_a_script_s_first_line(self):
        self.write(".interp/bin/py", "\0binary")
        self.write(".local/bin/tool", f"#!{self.home}/.interp/bin/py -x\n")
        self.assertIn('"Edit(~/.interp/**)"', self.run_it())

    def test_a_venv_home_and_its_pth_paths(self):
        self.write(".pyhome/bin/python3", "\0binary")
        self.write(".venvs/v/pyvenv.cfg", f"home = {self.home}/.pyhome/bin\n")
        self.write(".venvs/v/bin/python", "\0binary")
        self.write(".venvs/v/lib/python3.13/site-packages/x.pth", f"{self.home}/.editable/src\n")
        self.mk(".editable/src")
        self.write(".venvs/v/bin/tool", f"#!{self.home}/.venvs/v/bin/python\n")
        self.link(".venvs/v/bin/tool", "tool")
        out = self.run_it()
        for rule in ("Edit(~/.venvs/**)", "Edit(~/.pyhome/**)", "Edit(~/.editable/**)"):
            self.assertIn(rule, out)

    def test_what_a_script_sources_or_execs(self):
        self.write(".lib1/a.sh", "")
        self.write(".lib2/b.sh", "")
        self.write(".lib3/c", "")
        self.write(".local/bin/tool", "#!/bin/sh\n"
                                      f"source {self.home}/.lib1/a.sh\n"
                                      '. "$HOME/.lib2/b.sh"\n'
                                      "  exec ~/.lib3/c --flag\n"
                                      "exec bare-name\n"
                                      'source "$UNKNOWN/skip.sh"\n')
        out = self.run_it()
        for rule in ("Edit(~/.lib1/**)", "Edit(~/.lib2/**)", "Edit(~/.lib3/**)"):
            self.assertIn(rule, out)
        self.assertNotIn("skip", out)
        self.assertNotIn("bare-name", out)

    def test_a_library_found_relative_to_the_script(self):
        # The shape of a tool whose bin dir has a rule and whose lib dir doesn't.
        self.mk("tool/bin")
        self.write("tool/lib/x.sh", "")
        self.write("tool/bin/run", '#!/bin/sh\nsource "$(cd "$(dirname "$0")/.." && pwd)/lib/x.sh"\n')
        out = self.run_it(path=os.path.join(self.home, "tool/bin"), deny=["Edit(~/tool/bin/**)"])
        self.assertIn("Edit(~/tool/lib/**)", out)
        self.assertNotIn("Edit(~/tool/bin/**)", out)

    def test_what_a_followed_file_sources_too(self):
        self.write(".deep/two.sh", "")
        self.write(".local/one.sh", f"source {self.home}/.deep/two.sh\n")
        self.write(".local/bin/tool", f"#!/bin/sh\nsource {self.home}/.local/one.sh\n")
        self.assertIn("Edit(~/.deep/**)", self.run_it())

    def test_a_path_dir_with_no_rule(self):
        self.write(".foo/bin/tool", "")
        self.assertIn("Edit(~/.foo/**)", self.run_it(path=os.path.join(self.home, ".foo/bin")))

    def test_a_root_inside_a_project_gets_no_rule(self):
        self.mk("code/p/.git")
        self.write("code/p/tools/bin/tool", "#!/bin/sh\n")
        self.link("code/p/tools/bin/tool", "tool")
        out = self.run_it()
        self.assertIn("code/p/tools/bin/tool", out)
        self.assertIn("install the tool outside it", out)
        self.assertNotIn('"Edit(~/code', out)    # not in the block to paste
        self.assertIn("    Edit(~/code/p/**)", out)   # named apart, with what it costs
        self.assertNotIn("root(s) with no Edit deny rule", out)

    def test_the_paste_block_is_clean_json_items(self):
        self.write(".newtool/bin/tool", "#!/bin/sh\n")
        self.link(".newtool/bin/tool", "tool")
        self.mk(".ipython")
        lines = self.run_it().splitlines()
        block = [l for l in lines if l.startswith('  "')]
        self.assertEqual(len(block), 2)
        self.assertEqual(json.loads("[" + "".join(block).rstrip(",") + "]"),
                         ["Edit(~/.ipython/**)", "Edit(~/.newtool/**)"])
        self.assertTrue(any(l.startswith("  Edit(~/.newtool/**) is in the PATH dir") for l in lines))
        self.assertFalse(any(l.startswith("  Edit(~/.ipython/**) is") for l in lines))

    def test_the_checkout_and_dotclaude_are_skipped(self):
        self.write("dotclaude/bin/a", "#!/bin/sh\n")
        self.write("lanes/x/bin/b", "#!/bin/sh\n")
        self.link("dotclaude/bin/a", "a")
        self.link("lanes/x/bin/b", "b")
        out = self.run_it(extra=["--checkout", os.path.join(self.home, "lanes/x")])
        self.assertEqual(out, "")

    def test_home_dot_dirs_with_no_rule(self):
        self.mk(".ipython")
        self.mk("notdot")
        self.mk(".claude/x")
        out = self.run_it()
        self.assertIn('"Edit(~/.ipython/**)"', out)
        self.assertNotIn("notdot", out)
        self.assertNotIn(".claude", out)

    def test_cache_dirs_get_their_own_rule_and_never_the_sandbox_s(self):
        self.mk(".cache/puppeteer/x")
        self.mk(".cache/claude-sandbox/npm")
        out = self.run_it()
        self.assertIn('"Edit(~/.cache/puppeteer/**)"', out)
        self.assertNotIn("claude-sandbox", out)
        self.assertNotIn("Edit(~/.cache/**)", out)

    def test_a_dot_dir_linked_elsewhere_is_judged_at_both_ends(self):
        real = self.mk("data/real-aws")
        os.symlink(real, os.path.join(self.home, ".aws"))
        out = self.run_it()
        self.assertIn("Edit(~/.aws/**)", out)
        self.assertIn("Edit(~/data/real-aws/**)", out)

    def test_a_writable_file_outside_home(self):
        outside = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        with open(os.path.join(outside, "tectonic"), "w") as f:
            f.write("x")
        out = self.run_it(path=outside, deny=[*self.deny, f"Edit(/{outside}/**)"])
        self.assertEqual(out, "")
        out = self.run_it(path=outside)
        self.assertIn(f"Edit(/{outside}", out)

    def test_a_read_only_system_dir_is_ignored(self):
        if os.access("/usr/bin", os.W_OK):
            self.skipTest("this user can write /usr/bin")
        self.assertEqual(self.run_it(path="/usr/bin"), "")

    def test_a_fifo_doesn_t_block_it(self):
        os.mkfifo(os.path.join(self.bin, "pipe"))
        self.assertEqual(self.run_it(), "")

    def test_a_loop_of_sources_ends(self):
        a = f"{self.home}/.local/a.sh"
        b = f"{self.home}/.local/b.sh"
        self.write(".local/a.sh", f"source {b}\n")
        self.write(".local/b.sh", f"source {a}\n")
        self.write(".local/bin/tool", f"source {a}\n")
        self.assertEqual(self.run_it(), "")

    def test_a_name_that_can_t_be_a_rule_is_named_and_gets_none(self):
        self.write(".to[ol/bin/x", "")
        self.link(".to[ol/bin/x", "x")
        out = self.run_it()
        self.assertIn("the name can't be written as one", out)
        self.assertNotIn('"Edit(~/.to[ol', out)

    def test_a_control_character_in_a_name_can_t_reach_the_terminal(self):
        self.write(".evil\x1b[31m/bin/x", "")
        self.link(".evil\x1b[31m/bin/x", "x")
        self.assertNotIn("\x1b", self.run_it())

    def test_code_under_cache_or_claude_never_prints_a_rule_on_the_whole_dir(self):
        self.write(".cache/newtool/t", "#!/bin/sh\n")
        self.write(".claude/local/x", "#!/bin/sh\n")
        self.link(".cache/newtool/t", "t")
        self.link(".claude/local/x", "x")
        out = self.run_it()
        self.assertNotIn("Edit(~/.cache/**)", out)
        self.assertNotIn("Edit(~/.claude/**)", out)
        self.assertIn('"Edit(~/.cache/newtool/**)"', out)
        self.assertIn('"Edit(~/.claude/local/**)"', out)

    def test_code_in_what_must_stay_writable_is_named_with_no_rule(self):
        for rel in (".cache/claude-sandbox/x", ".claude/projects/x", ".claude/plans/x", ".claude/jobs/x"):
            with self.subTest(rel=rel):
                self.write(rel, "#!/bin/sh\n")
                name = rel.replace("/", "-")
                self.link(rel, name)
                out = self.run_it()
                self.assertIn("no rule can cover", out)
                self.assertNotIn(f'"Edit(~/{rel.rsplit("/", 1)[0]}', out)
                os.unlink(os.path.join(self.bin, name))

    def test_the_named_home_dirs_beyond_the_dot_dirs(self):
        for d in ("go/pkg/mod", "nltk_data", "sdk/x"):
            self.mk(d)
        out = self.run_it()
        for rule in ("Edit(~/go/**)", "Edit(~/nltk_data/**)", "Edit(~/sdk/**)"):
            self.assertIn(f'"{rule}"', out)

    def test_a_dot_dir_in_a_checkout_stays_out_of_the_paste_block(self):
        self.mk("dotfiles/.git")
        self.mk("dotfiles/vim")
        os.symlink(os.path.join(self.home, "dotfiles/vim"), os.path.join(self.home, ".vim"))
        out = self.run_it()
        self.assertNotIn('"Edit(~/dotfiles', out)
        self.assertIn("    Edit(~/dotfiles/**)", out)
        self.assertIn('"Edit(~/.vim/**)"', out)    # the link's own name

    def test_a_dot_dir_linked_to_home_gets_no_rule_on_home(self):
        os.symlink(self.home, os.path.join(self.home, ".self"))
        out = self.run_it()
        self.assertNotIn("Edit(~/./", out)
        self.assertIn("no rule can cover", out)

    def test_a_big_or_binary_script_still_gives_its_interpreter(self):
        self.write(".interp/bin/py", "\0binary")
        self.write(".local/bin/big", f"#!{self.home}/.interp/bin/py\n" + "x" * 300000)
        self.write(".interp2/bin/py", "\0binary")
        self.write(".local/bin/zipapp", f"#!{self.home}/.interp2/bin/py\n\0zip")
        out = self.run_it()
        self.assertIn("Edit(~/.interp/**)", out)
        self.assertIn("Edit(~/.interp2/**)", out)

    def test_commands_after_a_test_a_then_or_with_no_exec(self):
        for n in "1234":
            self.write(f".c{n}/f", "")
        self.write(".local/bin/tool", "#!/bin/sh\n"
                                      f'[ -f "$HOME/.c1/f" ] && . "$HOME/.c1/f"\n'
                                      f"if true; then source ~/.c2/f; fi\n"
                                      f"true; {self.home}/.c3/f arg\n"
                                      f"{self.home}/.c4/f\n"
                                      "# ~/.notreal/f\n"
                                      "echo ~/.alsonot/f\n")
        self.mk(".local")
        out = self.run_it()
        for n in "1234":
            self.assertIn(f"Edit(~/.c{n}/**)", out)
        self.assertNotIn("notreal", out)
        self.assertNotIn("alsonot", out)

    def test_a_writable_script_outside_home_leads_to_its_interpreter(self):
        outside = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        self.write(".interp/bin/py", "\0binary")
        with open(os.path.join(outside, "tool"), "w") as f:
            f.write(f"#!{self.home}/.interp/bin/py\n")
        self.assertIn("Edit(~/.interp/**)", self.run_it(path=outside))

    def test_unreadable_settings_warn_and_exit_0(self):
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--settings", "/nonexistent"],
                           env={"HOME": self.home, "PATH": self.bin}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("can't read", r.stderr)

    def test_the_rule_reader_agrees_with_the_baseline(self):
        # The baseline's own rules read as rules here: ~/.local covers a state file, a one-file
        # rule covers only that file, and a glob stays within one path part.
        with open(os.path.join(REPO, "settings.json")) as f:
            deny = json.load(f)["permissions"]["deny"]
        self.write(".zcompdump-HAYPC-5.9", "")
        self.mk(".ssh")
        self.mk(".cargo")
        self.assertEqual(self.run_it(deny=deny), "")

    def test_setup_runs_it_after_the_settings_install(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            text = f.read()
        self.assertIn('bin/deny-coverage" --settings "$CLAUDE_DIR/settings.json" --checkout "$REPO_DIR"',
                      text)
        self.assertLess(text.index('copy_managed "$MERGED_SETTINGS"'), text.index("bin/deny-coverage"))


if __name__ == "__main__":
    unittest.main()
