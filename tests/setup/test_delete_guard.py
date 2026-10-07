"""hooks/delete-guard.sh: deletes in sandbox-off Bash commands (stdlib only).

For a command run with dangerouslyDisableSandbox, a delete (rm, rmdir, shred, unlink, find
-delete) is denied when a path uses a variable the command didn't set (or one built from such), a
command substitution that would widen the path if it came back empty, a top-level or home tree,
or a relative path after a cd into one of those. A sandboxed command and every non-delete pass
untouched; delete_guard.py's docstring has the full rules. The first case
is the slip that prompted it: `rm -rf "$TMPDIR"/...` outside the sandbox, where $TMPDIR is /tmp."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "delete-guard.sh")


class DeleteGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = dict(os.environ, XDG_STATE_HOME=self.tmp, HOME="/home/u")

    def fire(self, command, off=True, raw=None):
        event = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": command, "dangerouslyDisableSandbox": off}}
        p = subprocess.run(["bash", HOOK], input=raw or json.dumps(event), capture_output=True,
                           text=True, env=self.env, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def log(self):
        try:
            with open(os.path.join(self.tmp, "dotclaude", "delete-guard.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def denied(self, command):
        out = self.fire(command)
        return out is not None and out["permissionDecision"] == "deny"

    def test_the_tmpdir_slip_is_denied_with_the_reason(self):
        out = self.fire('cd /x && rm -rf "$TMPDIR"/replay "$TMPDIR"/fp.py')
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("$TMPDIR is plain /tmp", out["permissionDecisionReason"])
        self.assertIn("deny untrusted rm $TMPDIR/replay", self.log())

    def test_a_sandboxed_command_is_never_judged(self):
        self.assertIsNone(self.fire('rm -rf "$TMPDIR"/x', off=False))
        self.assertIsNone(self.fire("rm -rf ~/*", off=False))

    def test_unset_variables_are_denied(self):
        for command in ("rm -rf $T", "rm -f ${OUT}/a.txt", "git branch -d x && rm -rf $T/y",
                        "for d in a; do rm -rf $NOPE; done", "if true; then rm -rf $Q; fi",
                        "find $X -name '*.pyc' -delete", "rmdir $D", "shred -u $F",
                        "sudo rm -rf $Z", "FOO=1 rm -rf $BAR",
                        "TMPDIR=/x rm -rf \"$TMPDIR\"/y",       # a prefix assignment comes too late
                        "rm -rf \"$1\"/*", "set -- $NOPE; rm -rf $1",
                        "cd ~ && rm -rf \"$PWD\"",             # PWD moves with cd
                        "rm -rf ${HOME%/*}", "rm -rf ${X:-/tmp}/y"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_a_variable_built_from_an_unset_one_is_denied(self):
        for command in ('D="$TMPDIR/replay"; rm -rf "$D"', 'for f in "$TMPDIR"/*; do rm -rf "$f"; done',
                        'fresh="${TMPDIR:-/tmp}/x"; rm -rf "$fresh"', "X=$(pwd)/a; rm -rf $X",
                        "dir=$(mktemp -d); Y=$dir/a; rm -rf $Y"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_a_substitution_is_denied_when_empty_would_widen_the_path(self):
        for command in ("rm -rf \"$(mktemp -d)\"/x", "rm -rf $(git rev-parse --show-toplevel)/x",
                        "rm -rf `pwd`/x", "dir=$(mktemp -d); rm -rf \"$dir\"/*",
                        "dir=$(mktemp -d); rm -rf \"$dir\"*", "dir=$(mktemp); rm -rf \"$dir\"/../x"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
        # Empty, these only empty the argument or stay in the working directory.
        for command in ("rm -rf \"$(mktemp -d)\"", "rm -rf $(mktemp -d)",
                        "dir=$(mktemp -d \"$TMPDIR/x-XXXX\"); rm -rf \"$dir\"",
                        "dir=$(mktemp -d); rm -rf \"$dir\".txt", "f=$(ls x); rm -f \"${f}_old\""):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_the_parse_survives_shell_layout(self):
        for command in ("rm -rf \\\n  \"$TMPDIR\"/replay",            # a line continuation
                        "rm -rf \\\n  ~/",
                        "# clean up (don't keep it)\nrm -rf \"$TMPDIR\"/replay",
                        "ls # list\nrm -rf $T",
                        "sudo -u x rm -rf $Q", "env -i rm -rf $Q", "timeout 60 rm -rf $Q",
                        "\\rm -rf $Q", "/bin/rm -rf $Q",
                        "find $Q -exec /bin/rm {} \\;", "find $Q -execdir rm {} +"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
        # Each layout must parse, not fail open: a safe delete passes, and an unsafe one on the
        # next line is still caught.
        for command in ("echo $((1<<3)); rm -rf /tmp/claude-1000/x",
                        "(( y = 1<<3 )); rm -rf /tmp/claude-1000/x",
                        "cat <<< \"$X\"; rm -f /tmp/claude-1000/y",
                        "echo \"# not a comment $X\"; rm -f /tmp/claude-1000/z",
                        "x=$(gh run list --jq '.[] | \"\\(.status)\"'); rm -f /tmp/claude-1000/w",
                        "python3 -c 'print(1<<n)'; rm -f /tmp/claude-1000/v",
                        "printf $'it\\'s\\n'; rm -f /tmp/claude-1000/u; echo don\\'t",
                        "x=$(ls # don't\n); rm -f /tmp/claude-1000/t",
                        "cat <<'EOF' > f\nrm -rf $NOPE\nEOF\nrm -f /tmp/claude-1000/s",
                        # A PR body: a heredoc with apostrophes inside "$(...)".
                        "gh pr create --body \"$(cat <<'EOF'\nthe payload's type\nEOF\n)\"; "
                        "rm -f /tmp/claude-1000/r"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))
                self.assertTrue(self.denied(command + "\nrm -rf \"$TMPDIR\"/x"))

    def test_values_are_followed_through_loops_braces_cd_and_reassignment(self):
        for command in ("for d in ~/*; do rm -rf \"$d\"; done", "set -- ~; rm -rf \"$1\"",
                        "rm -rf ~/{code,vault}", "rm -rf /{tmp,var}",
                        "set -- $(cmd); job=$1; rm -rf \"$job\"/*",
                        "rm -rf \"$HOME/$(cat name)\"", "d=$(mktemp -d); rm -rf \"$HOME/$d\"",
                        "R=~/code; d=$(cmd); rm -rf \"$R/$d\"", "HOME=$TMPDIR; rm -rf $HOME/x",
                        "cd \"$TMPDIR\" && rm -rf ./*", "cd && rm -rf *", "find -L $Q -delete",
                        "rm -rf \"\" \"$TMPDIR\"/x", "sudo nice rm -rf $Q"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
        for command in ("sudo git rm -r --cached $X",                 # git rm, not rm
                        "p=/tmp/claude-1000/run; rm -rf \"$p$(date +%s)\"",
                        "X=/a; rm -f \"$X$((1))\"", "set -- $(cmd); rm -rf \"$1\"",
                        "cd /tmp/claude-1000/x && rm -rf ./*"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_common_agent_shapes(self):
        # Final review (2026-10-06): loops after a cd, blank lines from read, prefix cleanups,
        # ${X:?}, arrays and filtered finds.
        for command in ("cd \"$TMPDIR\" && for f in *; do rm -rf \"$f\"; done",
                        "cd /tmp && for f in *; do rm -rf \"$f\"; done",
                        "while read -r d; do rm -rf \"$d\"/*; done < dirs.txt",
                        "cd \"$(mktemp -d)\" && rm -rf *", "timeout 30s rm -rf $X",
                        "rm -rf /mnt/c/Users/hayde", "find ~/code -exec rm -rf {} +",
                        "cd ~ && cd code && rm -rf *"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
        for command in ("rm -rf /tmp/pytest-*", "rm -f /tmp/*.log", "rm -rf ~/scratch/old-*",
                        "cd /tmp && rm -rf claude-test-*", "dir=/x/y; rm -rf \"${dir:?}\"/*",
                        "d=$(mktemp -d); rm -rf \"${d:?}\"/build",
                        "files=(a.txt b.txt); rm -f \"${files[@]}\"",
                        "find /tmp -maxdepth 1 -name 'pytest-*' -exec rm -rf {} +",
                        "find ~/code -name __pycache__ -exec rm -rf {} +",
                        "mkdir -p /x/y && cd $_ && rm -rf z",
                        "cd /tmp/claude-1000/w && for f in *; do rm -rf \"$f\"; done"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_variables_the_command_sets_are_fine(self):
        for command in ("S=/tmp/claude-1000/x; rm -rf $S/a", "export S=/a/b && rm -rf \"$S\"",
                        "for d in a b; do rm -rf $d; done",
                        "while read f; do rm -f \"$f\"; done < list",
                        "for pair in \"a b\"; do set -- $pair; job=$1; rm -f -- \"/c/$job.done\"; done",
                        "rm -rf $HOME/.cache/foo", "rm -f /tmp/x.$$"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_catastrophic_targets_are_denied(self):
        for command in ("rm -rf ~", "rm -rf ~/", "rm -rf ~/*", "rm -rf /tmp/*", "rm -rf /",
                        "rm -rf $HOME", "rm -rf ~/.claude", "rm -rf /home/u/code",
                        "S=/tmp; rm -rf $S/*", "rm -rf /mnt/c/Users", "S=/; rm -rf $S/*",
                        "rm -rf ~/.*", "rm -rf ~/**", "rm -rf /tmp/?*", "nice rm -rf ~/*"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_specific_paths_and_other_commands_pass(self):
        for command in ("rm -rf /tmp/claude-1000/foo", "rm -f work/79/out/*.png",
                        "rm -rf ~/.claude/plans/old.md", "find /home/u/code/x -name '*.pyc' -delete",
                        "echo \"rm -rf $NOPE\"", "git rm -r --cached $X", "ls $NOPE",
                        "python3 - <<'EOF'\nimport os; os.system('rm -rf $NOPE')\nEOF\necho done",
                        "cat <<EOF > f\nrm -rf $NOPE\nEOF"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_the_settings_prefilter_passes_both_payload_spacings_and_nothing_else(self):
        # Run the real settings.json command against a stand-in hook that only reports it ran, so
        # the test sees the prefilter's choice itself, not the guard's verdict.
        home = os.path.join(self.tmp, "home")
        hooks = os.path.join(home, ".claude", "hooks")
        os.makedirs(hooks)
        with open(os.path.join(hooks, "delete-guard.sh"), "w") as f:
            f.write("cat >/dev/null; echo RAN\n")
        with open(os.path.join(REPO, "settings.json")) as f:
            (cmd,) = [h["command"] for e in json.load(f)["hooks"]["PreToolUse"]
                      if e.get("matcher") == "Bash" for h in e["hooks"]]
        env = dict(self.env, HOME=home)
        event = {"tool_name": "Bash", "tool_input": {"command": 'rm -rf "$TMPDIR"/x',
                                                     "dangerouslyDisableSandbox": True}}
        sandboxed = {"tool_name": "Bash", "tool_input": {"command": 'rm -rf "$TMPDIR"/x'}}
        quoted = {"tool_name": "Bash", "tool_input": {
            "command": 'echo \'"dangerouslyDisableSandbox":true\'; rm -rf $T'}}
        for payload, ran in ((json.dumps(event, separators=(",", ":")), True),
                             (json.dumps(event), True),
                             (json.dumps(sandboxed), False),
                             (json.dumps(quoted), False),    # the text inside a command is escaped
                             (json.dumps(quoted, separators=(",", ":")), False)):
            with self.subTest(payload=payload[:60]):
                p = subprocess.run(["sh", "-c", cmd], input=payload, capture_output=True,
                                   text=True, env=env, timeout=10)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual("RAN" in p.stdout, ran, p.stdout)

    def test_fails_open(self):
        self.assertIsNone(self.fire("x", raw="not json"))
        self.assertIn("error", self.log())
        self.assertIsNone(self.fire("rm -rf 'unbalanced $T"))
        self.assertIn("unparsed", self.log())
        self.env["XDG_STATE_HOME"] = os.path.join(self.tmp, "file")
        open(self.env["XDG_STATE_HOME"], "w").close()
        self.assertTrue(self.denied("rm -rf $T"))  # an unwritable log doesn't stop the deny


if __name__ == "__main__":
    unittest.main()
