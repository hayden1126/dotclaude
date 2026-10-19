"""session-title.sh and session-summary.sh: the event arrives on stdin at any size, and injected
content (task notices, agent messages, skill bodies) is never taken for the user (stdlib only)."""
import ast
import json
import os
import re
import subprocess
import tempfile
import time
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
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        self.env["HOME"] = self.tmp.name


class SessionTitle(Workspace):
    def title(self, **payload):
        out = hook("session-title.sh", {"cwd": self.cwd, "transcript_path": self.transcript,
                                        **payload}, env=self.env)
        return json.loads(out)["hookSpecificOutput"]["sessionTitle"] if out else None

    def test_a_prompt_seeds_the_title(self):
        self.assertEqual(self.title(prompt="fix the parser\nmore"), "proj · fix the parser")

    def worktree(self, *parts):
        """A linked worktree at parts under the temp dir: a .git file, as git writes one."""
        path = os.path.join(self.tmp.name, *parts)
        os.makedirs(os.path.join(path, "sub"))
        with open(os.path.join(path, ".git"), "w") as f:
            f.write("gitdir: " + os.path.join(self.cwd, ".git", "worktrees", parts[-1]) + "\n")
        return path

    def test_the_launch_dir_names_the_repo_after_a_bash_cd(self):
        # A Bash cd moves the payload cwd (and $PWD) but not CLAUDE_PROJECT_DIR: the lead that
        # cd'd into an agent worktree keeps its own repo in the title.
        agent = self.worktree("proj", ".claude", "worktrees", "agent-a1")
        self.env["CLAUDE_PROJECT_DIR"] = self.cwd
        self.assertEqual(self.title(prompt="fix it", cwd=os.path.join(agent, "sub")),
                         "proj · fix it")

    def test_a_lane_shows_its_worktree_name(self):
        # Launched in its worktree, even with its cwd moved into the main checkout.
        lane = self.worktree("proj-lanes", "lane-x")
        self.env["CLAUDE_PROJECT_DIR"] = lane
        self.assertEqual(self.title(prompt="fix it", cwd=self.cwd),
                         "lane-x · fix it")

    def test_with_no_usable_launch_dir_the_cwd_names_the_repo(self):
        agent = self.worktree("proj", ".claude", "worktrees", "agent-a1")
        for project in (None, "", os.path.join(self.tmp.name, "gone")):
            with self.subTest(project=project):
                self.env.pop("CLAUDE_PROJECT_DIR", None)
                if project is not None:
                    self.env["CLAUDE_PROJECT_DIR"] = project
                self.assertEqual(self.title(prompt="fix it", cwd=agent), "agent-a1 · fix it")

    def test_a_long_summary_is_clipped_to_the_title_budget(self):
        title = self.title(prompt="word " * 40)
        self.assertEqual(len(title), 64)
        self.assertTrue(title.startswith("proj · word") and title.endswith("\u2026"), title)

    def test_injected_content_leaves_the_title_alone(self):
        # No output at all: falling through to a bare "proj" would overwrite the title the
        # user's own prompt set.
        for prompt in ("<task-notification><status>killed</status></task-notification>",
                       '<agent-message from="a1">[Subagent hand-back] done</agent-message>',
                       "[SYSTEM NOTIFICATION - NOT USER INPUT] a background task ended"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.title(prompt=prompt))

    def test_a_subagent_or_teammate_prompt_never_retitles(self):
        self.assertIsNone(self.title(prompt="fix the parser", agent_id="a1"))

    def test_a_huge_prompt_still_titles(self):
        self.assertEqual(self.title(prompt="fix the parser " + BIG)[:22], "proj · fix the parser ")


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
        # The hook passes its own directory, where it imports haiku.py from.
        p = subprocess.run(["python3", "-c", src, HOOKS], capture_output=True, text=True,
                           timeout=20,
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
            # A typed prompt is the user's even when it quotes a marker: origin.kind decides.
            user("why did <task-notification> say killed?", origin={"kind": "human"}),
            user("these args are not user input", origin={"kind": "human"}),
            # isMeta always drops: a skill body is never the user's words, whatever its origin.
            user("Base directory for this skill: y", origin={"kind": "human"}, isMeta=True),
        ]
        self.assertEqual(self.dialogue(entries).splitlines(),
                         ["User: fix the parser", "Assistant: Fixed.",
                          "User: an older prompt with no origin",
                          "User: why did <task-notification> say killed?",
                          "User: these args are not user input"])

    def test_a_huge_event_is_still_read(self):
        entries = [{"type": "user", "origin": {"kind": "human"},
                    "message": {"role": "user", "content": "fix the parser"}}]
        self.assertEqual(self.dialogue(entries, last_assistant_message=BIG),
                         "User: fix the parser")

    def test_the_detached_job_gets_the_whole_event_on_stdin(self):
        # A python3 shim records its first argument and how many bytes reached its stdin, so
        # this covers the shell wiring (the detached generate) that the tests above skip.
        shim_dir = os.path.join(self.tmp.name, "shim")
        os.makedirs(shim_dir)
        out = os.path.join(self.tmp.name, "shim.out")
        with open(os.path.join(shim_dir, "python3"), "w") as f:
            f.write('#!/bin/bash\n{ printf "%s\\n" "$1"; wc -c; } > "$SHIM_OUT.tmp"\n'
                    'mv "$SHIM_OUT.tmp" "$SHIM_OUT"\n')
        os.chmod(os.path.join(shim_dir, "python3"), 0o755)
        event = {"session_id": "sid", "transcript_path": self.transcript,
                 "last_assistant_message": BIG}
        env = {**self.env, "PATH": shim_dir + os.pathsep + os.environ["PATH"], "SHIM_OUT": out}
        self.assertEqual(hook("session-summary.sh", event, env=env), "")
        deadline = time.monotonic() + 10
        while not os.path.exists(out) and time.monotonic() < deadline:
            time.sleep(0.05)
        with open(out) as f:
            self.assertEqual(f.read().split(), ["-I", str(len(json.dumps(event).encode()))])

    def test_stdin_too_deep_for_json_draws_nothing(self):
        # The widget, statusline/session-summary.py: "[" * 100000 is RecursionError in json.
        widget = os.path.join(REPO, "statusline", "session-summary.py")
        p = subprocess.run(["python3", "-I", widget, "--row", "1"], input="[" * 100000,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))


class ProjectFilesStayOut(Workspace):
    """A hook runs in the project's directory: a json.py there must not replace the stdlib's."""

    def test_a_projects_json_py_never_runs(self):
        ran = os.path.join(self.tmp.name, "ran")
        with open(os.path.join(self.cwd, "json.py"), "w") as f:
            f.write(f"open({ran!r}, 'a').write(__name__)\n")
        # excluded-check prints only on a finding: a hooks dir the sandbox can write.
        with open(os.path.join(self.cwd, ".git", "config"), "w") as f:
            f.write("[core]\n\thooksPath = .githooks\n")
        self.env["XDG_STATE_HOME"] = os.path.join(self.tmp.name, "state")
        events = {"handoff-reminder.sh": {"prompt": "let's wrap up"},
                  "session-title.sh": {"cwd": self.cwd, "transcript_path": self.transcript,
                                       "prompt": "fix the parser"},
                  "excluded-check.sh": {"hook_event_name": "SessionStart", "cwd": self.cwd},
                  # ask-check prints only on a deny: four backticked names.
                  "ask-check.sh": {"tool_name": "AskUserQuestion", "cwd": self.cwd,
                                   "transcript_path": self.transcript, "tool_input": {
                                       "questions": [{"question": "`a1` `b2` `c3` `d4`?"}]}}}
        for name, event in events.items():
            with self.subTest(hook=name):
                p = subprocess.run(["bash", os.path.join(HOOKS, name)], input=json.dumps(event),
                                   capture_output=True, text=True, timeout=20, cwd=self.cwd,
                                   env=self.env)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertFalse(os.path.exists(ran), f"{name} imported the project's json.py")
                self.assertTrue(p.stdout, f"{name} printed nothing")


class InjectedMarkers(unittest.TestCase):
    """handoff-reminder, session-title and session-summary skip the same markers."""

    def test_the_three_lists_agree(self):
        lists = {}
        for name in ("handoff_reminder.py", "session-title.sh", "session-summary.sh"):
            body = re.search(r"^INJECTED = (\(.*?\))$",
                             open(os.path.join(HOOKS, name)).read(), re.S | re.M).group(1)
            lists[name] = set(ast.literal_eval(body))
        first = lists.pop("handoff_reminder.py")
        self.assertGreater(len(first), 10)
        for name, markers in lists.items():
            with self.subTest(hook=name):
                self.assertEqual(markers, first)

if __name__ == "__main__":
    unittest.main()
