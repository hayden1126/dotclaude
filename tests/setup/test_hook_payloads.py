"""session-title.sh, session-summary.sh and danger-guard.sh: the event arrives on stdin at any
size, and injected content (task notices, agent messages, skill bodies) is never taken for the
user (stdlib only)."""
import json
import os
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")
BIG = "x" * 200_000  # over MAX_ARG_STRLEN (128 KiB), which a payload passed as argv can't pass


def hook(name, payload, env=None):
    p = subprocess.run(["bash", os.path.join(HOOKS, name)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=20, env=env)
    assert p.returncode == 0, p.stderr
    return p.stdout


class Workspace(unittest.TestCase):
    """A repo named proj (its own .git, so a stray /tmp/.git can't name it), and a transcript
    under <cfg>/projects/<slug>/."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.tmp.name, "cfg", "projects", "slug"))
        os.makedirs(os.path.join(self.cwd, ".git"))
        self.transcript = os.path.join(self.tmp.name, "cfg", "projects", "slug", "sid.jsonl")
        open(self.transcript, "w").close()
        self.env = {**os.environ, "HOME": self.tmp.name}
        self.env.pop("DANGER_GUARD_AUTO", None)


class SessionTitle(Workspace):
    def title(self, **payload):
        out = hook("session-title.sh", {"cwd": self.cwd, "transcript_path": self.transcript,
                                        **payload}, env=self.env)
        return json.loads(out)["hookSpecificOutput"]["sessionTitle"] if out else None

    def test_a_prompt_seeds_the_title(self):
        self.assertEqual(self.title(prompt="fix the parser\nmore"), "[proj] fix the parser")

    def test_injected_content_never_seeds_the_title(self):
        for prompt in ("<task-notification><status>killed</status></task-notification>",
                       '<agent-message from="a1">[Subagent hand-back] done</agent-message>',
                       "[SYSTEM NOTIFICATION - NOT USER INPUT] a background task ended"):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.title(prompt=prompt), "[proj]")

    def test_a_subagent_or_teammate_prompt_never_retitles(self):
        self.assertIsNone(self.title(prompt="fix the parser", agent_id="a1"))

    def test_a_huge_prompt_still_titles(self):
        self.assertEqual(self.title(prompt="fix the parser " + BIG)[:22], "[proj] fix the parser ")


class DangerGuard(Workspace):
    def decision(self, command):
        out = hook("danger-guard.sh", {"tool_name": "Bash", "tool_input": {"command": command}},
                   env=self.env)
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else None

    def test_a_push_asks(self):
        self.assertEqual(self.decision("git push origin x"), "ask")

    def test_a_huge_command_is_still_checked(self):
        self.assertEqual(self.decision(f"git push origin x && echo '{BIG}'"), "ask")


class SessionSummary(Workspace):
    """Runs the hook's own script up to the dialogue it would send to Haiku, never the call."""

    MARK = "dialogue = recent_dialogue(transcript)"

    def dialogue(self, entries, **payload):
        with open(self.transcript, "w") as f:
            f.writelines(json.dumps(e) + "\n" for e in entries)
        src = open(os.path.join(HOOKS, "session-summary.sh")).read()
        src = src.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        self.assertIn(self.MARK, src)
        src = src.split(self.MARK, 1)[0] + "print(recent_dialogue(transcript))\n"
        p = subprocess.run(["python3", "-c", src], capture_output=True, text=True, timeout=20,
                           input=json.dumps({"session_id": "sid",
                                             "transcript_path": self.transcript, **payload}))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def test_only_the_users_own_words_count_as_the_user(self):
        def user(content, **extra):
            return {"type": "user", "message": {"role": "user", "content": content}, **extra}
        entries = [
            user("fix the parser", origin={"kind": "human"}),
            user("<task-notification><status>completed</status></task-notification>",
                 origin={"kind": "task-notification"}),
            user('<agent-message from="a1">report</agent-message>', origin={"kind": "peer"},
                 isMeta=True),
            user([{"type": "text", "text": "Base directory for this skill: x"}], isMeta=True),
            user("[SYSTEM NOTIFICATION - NOT USER INPUT] a task ended"),
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixed."}]}},
            user("an older prompt with no origin"),
        ]
        self.assertEqual(self.dialogue(entries).splitlines(),
                         ["User: fix the parser", "Assistant: Fixed.",
                          "User: an older prompt with no origin"])

    def test_a_huge_event_is_still_read(self):
        entries = [{"type": "user", "origin": {"kind": "human"},
                    "message": {"role": "user", "content": "fix the parser"}}]
        self.assertEqual(self.dialogue(entries, last_assistant_message=BIG),
                         "User: fix the parser")

    def test_the_hook_returns_at_once(self):
        # It detaches the summary job; with no credentials under HOME that job just exits.
        self.assertEqual(hook("session-summary.sh", {"session_id": "sid",
                                                     "transcript_path": self.transcript,
                                                     "last_assistant_message": BIG},
                              env=self.env), "")


if __name__ == "__main__":
    unittest.main()
