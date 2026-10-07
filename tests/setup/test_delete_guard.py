"""hooks/delete-guard.sh: deletes in sandbox-off Bash commands (stdlib only).

For a command run with dangerouslyDisableSandbox, a delete (rm, rmdir, shred, unlink, find
-delete) is denied when a path uses a variable the command didn't set, a command substitution, or
a top-level or home tree. A sandboxed command and every non-delete pass untouched. The first case
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
        for command in ("echo $((1<<3)); rm -rf /tmp/claude-1000/x",
                        "cat <<< \"$X\"; rm -f /tmp/claude-1000/y",
                        "echo \"# not a comment $X\"; rm -f /tmp/claude-1000/z",
                        "x=$(gh run list --jq '.[] | \"\\(.status)\"'); rm -f /tmp/claude-1000/w"):
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
        # Run the real settings.json command with a HOME whose hooks dir links to this repo's.
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".claude"))
        os.symlink(os.path.join(REPO, "hooks"), os.path.join(home, ".claude", "hooks"))
        with open(os.path.join(REPO, "settings.json")) as f:
            (cmd,) = [h["command"] for e in json.load(f)["hooks"]["PreToolUse"]
                      if e.get("matcher") == "Bash" for h in e["hooks"]]
        env = dict(self.env, HOME=home)
        event = {"tool_name": "Bash", "tool_input": {"command": 'rm -rf "$TMPDIR"/x',
                                                     "dangerouslyDisableSandbox": True}}
        sandboxed = {"tool_name": "Bash", "tool_input": {"command": 'rm -rf "$TMPDIR"/x'}}
        for payload, want in ((json.dumps(event, separators=(",", ":")), True),
                              (json.dumps(event), True),
                              (json.dumps(sandboxed), False),
                              (json.dumps({"tool_name": "Bash", "tool_input": {
                                  "command": 'echo \'"dangerouslyDisableSandbox":true\'; rm -rf $T'}}),
                               False)):
            with self.subTest(payload=payload[:60]):
                p = subprocess.run(["sh", "-c", cmd], input=payload, capture_output=True,
                                   text=True, env=env, timeout=10)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual('"deny"' in p.stdout, want, p.stdout)

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
