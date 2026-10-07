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
        self.assertIn("deny unset-var $TMPDIR", self.log())

    def test_a_sandboxed_command_is_never_judged(self):
        self.assertIsNone(self.fire('rm -rf "$TMPDIR"/x', off=False))
        self.assertIsNone(self.fire("rm -rf ~/*", off=False))

    def test_unset_variables_and_substitutions_are_denied(self):
        for command in ("rm -rf $T", "rm -f ${OUT}/a.txt", "git branch -d x && rm -rf $T/y",
                        "for d in a; do rm -rf $NOPE; done", "if true; then rm -rf $Q; fi",
                        "find $X -name '*.pyc' -delete", "rm -rf \"$(mktemp -d)\"",
                        "rm -rf `pwd`/x", "rmdir $D", "shred -u $F", "sudo rm -rf $Z",
                        "FOO=1 rm -rf $BAR"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_variables_the_command_sets_are_fine(self):
        for command in ("S=/tmp/claude-1000/x; rm -rf $S/a", "export S=/a/b && rm -rf \"$S\"",
                        "for d in a b; do rm -rf $d; done",
                        "while read f; do rm -f \"$f\"; done < list",
                        "X=$(pwd)/a; rm -rf $X", "rm -rf $HOME/.cache/foo"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_catastrophic_targets_are_denied(self):
        for command in ("rm -rf ~", "rm -rf ~/", "rm -rf ~/*", "rm -rf /tmp/*", "rm -rf /",
                        "rm -rf $HOME", "rm -rf ~/.claude", "rm -rf /home/u/code",
                        "S=/tmp; rm -rf $S/*", "rm -rf /mnt/c/Users"):
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
