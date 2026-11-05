"""bin/deny-coverage: what it finds from each kind of path, under a fake home and PATH."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "bin", "deny-coverage")


class CoverageBase(unittest.TestCase):
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


class DenyCoverage(CoverageBase):
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
        self.assertNotIn("dotclaude", out)
        self.assertNotIn("lanes/x", out)

    def test_home_dot_dirs_with_no_rule(self):
        self.mk(".ipython")
        self.mk("notdot")
        self.mk(".claude/x")
        out = self.run_it()
        self.assertIn('"Edit(~/.ipython/**)"', out)
        self.assertNotIn('"Edit(~/notdot', out)
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
        self.assertNotIn('"Edit(~/.vim/**)"', out)   # a rule on the link would act on the checkout

    def test_a_dot_dir_linked_to_home_gets_no_rule_on_home(self):
        os.symlink(self.home, os.path.join(self.home, ".self"))
        out = self.run_it()
        self.assertNotIn("Edit(~/.self", out)
        self.assertIn("no rule can cover", out)

    def settings_with(self, **extra):
        return {"permissions": {"deny": self.deny}, **extra}

    def run_with(self, settings):
        path = os.path.join(self.home, "s.json")
        with open(path, "w") as f:
            json.dump(settings, f)
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--settings", path],
                           env={"HOME": self.home, "PATH": self.bin}, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_a_root_above_a_repo_narrows_so_the_repo_stays_writable(self):
        self.write("work/acme/bin/tool", "#!/bin/sh\n")
        self.mk("work/acme/repo/.git")
        out = self.run_it(path=os.path.join(self.home, "work/acme/bin"))
        self.assertNotIn("Edit(~/work/acme/**)", out)
        self.assertIn('"Edit(~/work/acme/bin/**)"', out)

    def test_a_dot_dir_linked_to_a_dir_of_repos_gets_no_rule(self):
        self.mk("code/p/.git")
        os.symlink(os.path.join(self.home, "code"), os.path.join(self.home, ".x"))
        out = self.run_it()
        self.assertNotIn('"Edit(~/.x/**)"', out)
        self.assertNotIn('"Edit(~/code/**)"', out)
        self.assertIn("checkout", out)

    def test_a_dot_dir_holding_a_repo_gets_no_rule(self):
        self.mk(".things/deep/repo/.git")
        out = self.run_it()
        self.assertNotIn('"Edit(~/.things/**)"', out)
        self.assertIn(".things", out)

    def test_a_link_s_own_name_is_judged_by_its_target(self):
        self.mk(".claude/projects")
        os.symlink(os.path.join(self.home, ".claude"), os.path.join(self.home, ".alt"))
        os.symlink(self.home, os.path.join(self.home, ".self"))
        out = self.run_it()
        self.assertNotIn("Edit(~/.alt/**)", out)
        self.assertNotIn("Edit(~/.self/**)", out)
        self.assertIn("no rule can cover", out)
        self.assertIn(".alt", out)

    def test_a_dot_dir_linked_into_a_checkout_is_named_with_the_checkout(self):
        self.mk("proj/.git")
        self.mk("proj/vim")
        os.symlink(os.path.join(self.home, "proj/vim"), os.path.join(self.home, ".vim"))
        out = self.run_it()
        self.assertNotIn('"Edit(~/.vim/**)"', out)
        self.assertIn("inside a git checkout", out)

    def test_a_hook_status_line_and_mcp_command_are_followed(self):
        self.write("mytools/hook.sh", "#!/bin/sh\n")
        self.write("mytools2/status.sh", "#!/bin/sh\n")
        self.write("mytools3/server.js", "x\n")
        out = self.run_with(self.settings_with(
            hooks={"Stop": [{"hooks": [{"type": "command",
                                        "command": '[ -f "$HOME/mytools/hook.sh" ] && bash ~/mytools/hook.sh'}]}]},
            statusLine={"type": "command", "command": "~/mytools2/status.sh --x"},
            mcpServers={"s": {"command": "node", "args": ["~/mytools3/server.js"]}}))
        self.assertIn('"Edit(~/mytools/hook.sh)"', out)
        self.assertIn('"Edit(~/mytools2/status.sh)"', out)
        self.assertIn('"Edit(~/mytools3/server.js)"', out)

    def test_an_mcp_server_in_claude_json_is_followed(self):
        self.write("mcps/a.py", "x\n")
        self.write("mcps2/b.py", "x\n")
        self.write(".claude.json", json.dumps({
            "mcpServers": {"a": {"command": f"{self.home}/mcps/a.py"}},
            "projects": {"/p": {"mcpServers": {"b": {"command": "python3",
                                                     "args": [f"{self.home}/mcps2/b.py"]}}}}}), 0o600)
        out = self.run_it()
        self.assertIn('"Edit(~/mcps/a.py)"', out)
        self.assertIn('"Edit(~/mcps2/b.py)"', out)

    def test_what_a_shell_startup_file_sources_is_followed(self):
        self.write("mytools/env.sh", "x=1\n")
        self.write(".zshrc", "source ~/mytools/env.sh\n", 0o644)
        self.assertIn('"Edit(~/mytools/env.sh)"', self.run_it(
            deny=[*self.deny, "Edit(~/.zshrc)"]))

    def test_a_link_s_middle_hop_and_a_venv_behind_a_link_are_judged(self):
        self.write("envs/v/pyvenv.cfg", "home = /usr/bin\n", 0o644)
        self.write("envs/v/lib/python3.12/site-packages/e.pth", f"{self.home}/editable\n", 0o644)
        self.write("editable/x.py", "x\n", 0o644)
        self.mk("envs/v/bin")
        os.symlink(sys.executable, os.path.join(self.home, "envs/v/bin/python"))
        self.link("envs/v/bin/python", "py")
        out = self.run_it()
        self.assertIn('"Edit(~/envs/v/**)"', out)
        self.assertIn('"Edit(~/editable/**)"', out)

    def test_a_claude_local_md_above_projects_is_named(self):
        self.mk("code/p/.git")
        out = self.run_it()
        self.assertIn("Edit(~/code/CLAUDE.md)", out)
        self.assertIn("Edit(~/code/CLAUDE.local.md)", out)

    def test_bash_source_with_an_index_is_the_script_s_dir(self):
        self.write("lib2/lib/x.sh", "y=1\n")
        for spelling in ('$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)', '$(dirname "${BASH_SOURCE[0]}")',
                         '$(dirname "$BASH_SOURCE")', '$(dirname "${BASH_SOURCE}")'):
            with self.subTest(spelling):
                self.write("lib2/tool", f'#!/bin/sh\n. "{spelling}/lib/x.sh"\n')
                self.link("lib2/tool", "t")
                out = self.run_it(deny=[*self.deny, "Edit(~/lib2/tool)"])
                self.assertIn('"Edit(~/lib2/lib/**)"', out)
                os.unlink(os.path.join(self.bin, "t"))

    def test_a_link_to_a_checkout_with_an_odd_name_prints_no_broken_rule(self):
        self.mk("my code/.git")
        self.mk("my code/vim")
        os.symlink(os.path.join(self.home, "my code/vim"), os.path.join(self.home, ".vim"))
        out = self.run_it()
        self.assertNotIn("Edit(~/my code", out)
        self.assertIn("my code", out)

    def module(self):
        loader = importlib.machinery.SourceFileLoader("deny_coverage_mod", SCRIPT)
        spec = importlib.util.spec_from_loader("deny_coverage_mod", loader)
        m = importlib.util.module_from_spec(spec)
        loader.exec_module(m)
        return m

    def test_a_deep_repo_is_seen(self):
        self.mk(".things/a/b/c/d/e/f/.git")
        self.assertNotIn('"Edit(~/.things/**)"', self.run_it())

    def test_a_big_subtree_doesn_t_hide_a_shallow_repo(self):
        for n in range(150):
            self.mk(f".bulk/zz/d{n}")
        self.mk(".bulk/repo/.git")
        m = self.module()
        m.WALK_DIRS = 100
        self.assertTrue(m.Scan([], self.home, []).holds_checkout(os.path.join(self.home, ".bulk")))

    def test_a_plugin_clone_in_a_dot_dir_gets_its_rule_with_the_cost(self):
        self.mk(".tmux/plugins/tpm/.git")
        out = self.run_it()
        self.assertNotIn('"Edit(~/.tmux/**)"', out)   # not in the paste block
        self.assertIn("    Edit(~/.tmux/**)", out)
        self.assertIn("checkout", out)

    def test_a_narrowed_rule_says_what_stays_open(self):
        self.write("work/acme/bin/tool", "#!/bin/sh\n")
        self.mk("work/acme/repo/.git")
        out = self.run_it(path=os.path.join(self.home, "work/acme/bin"))
        self.assertIn('"Edit(~/work/acme/bin/**)"', out)
        self.assertIn("beside it stays open", out)

    def test_a_one_file_rule_says_what_stays_open(self):
        self.write("mcps/a.py", "x\n")
        self.write(".claude.json", json.dumps({"mcpServers": {"a": {"command": f"{self.home}/mcps/a.py"}}}), 0o600)
        self.assertIn("beside it stays open", self.run_it())

    def test_a_hop_through_a_linked_dir_resolves_from_the_real_dir(self):
        self.write("dotfiles/scripts/t", "#!/bin/sh\n")
        self.mk("dotfiles/bin")
        os.symlink("../scripts/t", os.path.join(self.home, "dotfiles/bin/t"))
        os.symlink("dotfiles/bin", os.path.join(self.home, ".bin"))
        out = self.run_it(path=os.path.join(self.home, ".bin"))
        self.assertNotIn("Edit(~/scripts/t)", out)

    def test_a_quote_split_and_a_spaced_path_in_a_hook(self):
        self.write("mytools/hook.sh", "#!/bin/sh\n")
        self.write("my tools/x.sh", "#!/bin/sh\n")
        out = self.run_with(self.settings_with(hooks={"Stop": [{"hooks": [
            {"command": 'bash "$HOME"/mytools/hook.sh'},
            {"command": 'bash "$HOME/my tools/x.sh"'}]}]}))
        self.assertIn('"Edit(~/mytools/hook.sh)"', out)
        self.assertIn("my tools/x.sh", out)      # named, with no rule
        self.assertNotIn('"Edit(~/my tools', out)

    def test_a_data_file_in_mcp_args_isn_t_code(self):
        self.write("work/client/config.json", "{}\n", 0o644)
        self.assertNotIn("work/client", self.run_with(self.settings_with(
            mcpServers={"s": {"command": "node", "args": ["--config", f"{self.home}/work/client/config.json"]}})))

    def test_a_link_into_the_skipped_checkout_prints_nothing_for_it(self):
        self.mk("dotclaude/.git")
        self.mk("dotclaude/x")
        os.symlink(os.path.join(self.home, "dotclaude/x"), os.path.join(self.home, ".t"))
        out = self.run_it()
        self.assertNotIn("Edit(~/dotclaude", out)

    def test_a_linked_home_reads_as_home(self):
        real, link = self.home, self.home + "-link"
        os.symlink(real, link)
        self.addCleanup(os.unlink, link)
        self.write(".local/bin/tool", "#!/bin/sh\n")
        settings = os.path.join(real, "s.json")
        with open(settings, "w") as f:
            json.dump({"permissions": {"deny": self.deny}}, f)
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--settings", settings],
                           env={"HOME": link, "PATH": os.path.join(link, ".local/bin")},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_a_deep_or_blocking_claude_json_is_no_crash(self):
        path = os.path.join(self.home, ".claude.json")
        os.mkfifo(path)
        self.run_it()
        os.unlink(path)
        deep = []
        for _ in range(100_000):
            deep = [deep]
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": self.home}), contextlib.redirect_stderr(err):
            self.module().Scan([], self.home, []).commands({"hooks": deep})
        self.assertIn("nests too deep", err.getvalue())

    def test_a_word_is_judged_as_data_not_a_whole_arg(self):
        self.write("t/run.sh", "#!/bin/sh\n")
        self.write("client/c.json", "{}\n", 0o644)
        out = self.run_with(self.settings_with(mcpServers={"s": {
            "command": f"node {self.home}/client/c.json",
            "args": ["-c", f"exec {self.home}/t/run.sh --config {self.home}/client/c.json"]}}))
        self.assertIn('"Edit(~/t/run.sh)"', out)
        self.assertNotIn("Edit(~/client/**)", out)
        self.assertNotIn("Edit(~/client/c.json)", out)

    def test_a_checkout_that_must_stay_open_prints_no_rule(self):
        self.mk(".claude/.git")
        self.write(".claude/local/x", "#!/bin/sh\n")
        self.link(".claude/local/x", "x")
        self.assertNotIn("Edit(~/.claude/**)", self.run_it())

    def test_a_link_s_target_says_why_it_prints(self):
        self.mk("notes")
        os.symlink(os.path.join(self.home, "notes"), os.path.join(self.home, ".x"))
        out = self.run_it()
        self.assertIn(f"Edit(~/notes/**) is what {self.home}/.x links to", out)

    def test_the_repo_walk_stays_out_of_mnt(self):
        m = self.module()
        with mock.patch.object(m.os, "scandir", side_effect=AssertionError("walked")):
            self.assertFalse(m.Scan([], self.home, []).holds_checkout("/mnt/c/Users/x"))

    def test_a_rule_on_a_link_to_what_must_stay_open_never_prints(self):
        self.write(".claude/tool/run", "#!/bin/sh\n")
        self.mk(".claude/projects")
        os.symlink(os.path.join(self.home, ".claude"), os.path.join(self.home, ".c"))
        os.symlink(self.home, os.path.join(self.home, ".h"))
        self.write("s2.sh", "")
        out = self.run_with(self.settings_with(hooks={"Stop": [{"hooks": [
            {"command": "~/.c/tool/run"}, {"command": "~/.h/s2.sh"}]}]}))
        self.assertNotIn("Edit(~/.c/**)", out)
        self.assertNotIn("Edit(~/.h/**)", out)
        self.assertIn('"Edit(~/.c/tool/**)"', out)     # narrowed to what the hook runs

    def test_a_middle_link_with_a_covered_target_keeps_its_rule(self):
        self.write(".tool/t", "#!/bin/sh\n")
        self.mk("tools/x")
        os.symlink(os.path.join(self.home, ".tool/t"), os.path.join(self.home, "tools/x/cur"))
        self.link("tools/x/cur", "t")
        self.assertIn('"Edit(~/tools/x/**)"',
                      self.run_it(deny=[*self.deny, "Edit(~/.tool/**)"]))

    def test_a_sourced_env_file_is_code(self):
        self.write("tools/x/dev.env", "A=1\n", 0o644)
        out = self.run_with(self.settings_with(hooks={"Stop": [{"hooks": [
            {"command": ". ~/tools/x/dev.env && x"}]}]}))
        self.assertIn("Edit(~/tools/x/**)", out)

    def test_a_path_link_into_a_skipped_checkout_is_named(self):
        self.write("dotclaude/bin/t", "#!/bin/sh\n")
        os.symlink(os.path.join(self.home, "dotclaude/bin"), os.path.join(self.home, ".mybin"))
        out = self.run_it(path=os.path.join(self.home, ".mybin"))
        self.assertNotIn("Edit(~/dotclaude", out)
        self.assertIn(".mybin", out)

    def test_a_missing_home_is_no_crash(self):
        settings = os.path.join(self.home, "s.json")
        with open(settings, "w") as f:
            f.write("{}")
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--settings", settings],
                           env={"HOME": os.path.join(self.home, "absent"), "PATH": self.bin},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

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

    def test_a_link_to_all_of_claude_or_cache_or_a_word_naming_tmp_gets_no_rule(self):
        self.mk(".claude/x")
        self.mk(".cache/y")
        os.symlink(os.path.join(self.home, ".claude"), os.path.join(self.home, ".alt"))
        os.symlink(os.path.join(self.home, ".cache"), os.path.join(self.home, ".alt2"))
        out = self.run_it()
        self.assertNotIn("Edit(~/.claude/**)", out)
        self.assertNotIn("Edit(~/.cache/**)", out)
        self.write(".local/bin/t", "#!/bin/sh\nexec /tmp\n")
        self.assertNotIn("Edit(//tmp/**)", self.run_it())

    def test_comments_and_words_naming_no_file_print_nothing(self):
        self.mk("scratch/audit")
        self.write(".local/bin/tool", "#!/bin/sh\ntrue  # then ~/scratch/audit/x\n"
                                      "true; ~/scratch/audit\n; ~/scratch/nofile\n")
        self.assertNotIn("Edit(~/scratch/audit", self.run_it())

    def test_a_quote_inside_a_word(self):
        self.write(".tools/env", "")
        self.write(".local/bin/tool", '#!/bin/sh\n. "$HOME"/.tools/env\n')
        self.assertIn('"Edit(~/.tools/**)"', self.run_it())

    def test_a_nul_in_a_first_line_doesn_t_crash_it(self):
        self.write(".local/bin/tool", "#!/x\0y")
        self.mk(".ipython")
        self.assertIn("Edit(~/.ipython/**)", self.run_it())

    def test_the_dirs_setup_fills_are_checked_with_a_minimal_path(self):
        self.write(".newtool/t", "#!/bin/sh\n")
        self.link(".newtool/t", "t")
        self.assertIn("Edit(~/.newtool/**)", self.run_it(path="/usr/bin"))

    def test_a_claude_md_above_projects_is_named_apart(self):
        self.mk("code/p/.git")
        self.mk("own/.git")
        out = self.run_it()
        self.assertIn("    Edit(~/code/CLAUDE.md)", out)
        self.assertNotIn('"Edit(~/code/CLAUDE.md)"', out)
        self.assertNotIn("Edit(~/own/CLAUDE.md)", out)

    def test_unreadable_settings_warn_and_exit_0(self):
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--settings", "/nonexistent"],
                           env={"HOME": self.home, "PATH": self.bin}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("can't read", r.stderr)

    def test_the_rule_reader_agrees_with_the_baseline(self):
        # The baseline's own rules read as rules here: ~/.local covers what's below it, and its
        # dir rules cover the dirs this looks at.
        with open(os.path.join(REPO, "settings.json")) as f:
            deny = json.load(f)["permissions"]["deny"]
        self.mk(".ssh")
        self.mk(".cargo")
        self.assertEqual(self.run_it(deny=deny), "")

    def test_setup_runs_it_after_the_settings_install(self):
        with open(os.path.join(REPO, "setup.sh")) as f:
            text = f.read()
        self.assertIn('bin/deny-coverage" --settings "$CLAUDE_DIR/settings.json" --checkout "$REPO_DIR"',
                      text)
        self.assertLess(text.index('copy_managed "$MERGED_SETTINGS"'), text.index("bin/deny-coverage"))



class Table(CoverageBase):
    """Each way a path is reached against what it resolves to. Two rules hold in every cell:
    no pasted rule takes a repo or a path sessions must write, even through a link, and each
    reached path prints something. Two gaps are on purpose, both in the docstring: the Windows mount
    (/mnt), which a test can't create, so test_the_repo_walk_stays_out_of_mnt covers it, and a
    skipped checkout, which stays silent since denyWrite covers it."""

    TARGETS = {
        "a plain dir": "tools/x/run.sh",
        "a repo": "proj/bin/run.sh",
        "a dir above a repo": "work/acme/bin/run.sh",
        "a dot-dir": ".thing/bin/run.sh",
        "a dot-dir holding a repo": ".held/bin/run.sh",
        "a path sessions must write": ".claude/projects/p/run.sh",
        "a sandbox cache": ".cache/claude-sandbox/t/run.sh",
        "a skipped checkout": "dotclaude/bin/run.sh",
        "a name no rule can spell": "my tools/run.sh",
    }
    REPOS = ("proj", "work/acme/repo", ".held/plugins/p", "dotclaude", "code/p")

    def build(self):
        for repo in self.REPOS:
            self.mk(f"{repo}/.git")
        self.mk(".claude/plans")
        self.mk(".claude/jobs")
        for rel in self.TARGETS.values():
            self.write(rel, "#!/bin/sh\n")

    def reach_path_link(self, rel):
        self.link(rel, "t")

    def reach_middle_link(self, rel):
        self.mk("mid")
        os.symlink(os.path.join(self.home, rel), os.path.join(self.home, "mid/cur"))
        self.link("mid/cur", "t")

    def reach_linked_path_dir(self, rel):
        os.symlink(os.path.dirname(os.path.join(self.home, rel)), os.path.join(self.home, ".pdir"))
        return os.path.join(self.home, ".pdir")

    def reach_script(self, rel):
        self.write(".local/bin/w", f'#!/bin/sh\nexec "$HOME/{rel}"\n')

    def reach_startup_file(self, rel):
        self.write(".zshrc", f'. "$HOME/{rel}"\n', 0o644)

    def reach_dot_dir_link(self, rel):
        os.symlink(os.path.dirname(os.path.join(self.home, rel)), os.path.join(self.home, ".lnk"))

    def reach_hook(self, rel):
        return {"hooks": {"Stop": [{"hooks": [{"command": f'bash "$HOME/{rel}"'}]}]}}

    def reach_status_line(self, rel):
        return {"statusLine": {"command": f'"$HOME/{rel}" --x'}}

    def reach_mcp(self, rel):
        return {"mcpServers": {"s": {"command": "node", "args": [f"{self.home}/{rel}"]}}}

    REACHES = ("path_link", "middle_link", "linked_path_dir", "script", "startup_file",
               "dot_dir_link", "hook", "status_line", "mcp")

    def protected(self):
        out = [self.home, *(os.path.join(self.home, r) for r in self.REPOS)]
        out += [os.path.join(self.home, d) for d in (
            ".claude/projects", ".claude/plans", ".claude/jobs", ".cache/claude-sandbox")]
        return [os.path.realpath(p) for p in out]

    def pasted_roots(self, out):
        for rule in re.findall(r'^  "Edit\((.+)\)",$', out, re.M):
            body = rule[:-3] if rule.endswith("/**") else rule
            yield rule, os.path.realpath(body.replace("~", self.home, 1) if body.startswith("~")
                                         else body[1:])

    def cell(self, reach, rel):
        self.build()
        how = getattr(self, f"reach_{reach}")(rel)
        settings = how if isinstance(how, dict) else {}
        path = how if isinstance(how, str) else self.bin
        settings_path = os.path.join(self.home, "s.json")
        with open(settings_path, "w") as f:
            json.dump({"permissions": {"deny": self.deny}, **settings}, f)
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--settings", settings_path],
                           env={"HOME": self.home, "PATH": path}, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_every_cell(self):
        for reach in self.REACHES:
            for what, rel in self.TARGETS.items():
                with self.subTest(reach=reach, target=what):
                    self.setUp()
                    out = self.cell(reach, rel)
                    for rule, root in self.pasted_roots(out):
                        for keep in self.protected():
                            self.assertFalse(
                                keep == root or keep.startswith(root + "/"),
                                f"{rule} takes {keep}:\n{out}")
                    if what != "a skipped checkout":
                        self.assertTrue(self.named(out, rel), f"nothing names {rel}:\n{out}")

    def named(self, out, rel):
        """Whether the output names the path, its dir, or a root above it."""
        parts = rel.split("/")
        spellings = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
        spellings += [".lnk", ".pdir", "mid"]
        return any(s in out for s in spellings)


if __name__ == "__main__":
    unittest.main()
