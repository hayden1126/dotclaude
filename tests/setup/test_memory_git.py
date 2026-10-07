"""hooks/memory-git.sh: every project's auto-memory committed to a local-only git repo on
SessionStart and Stop (stdlib only).

The repo's git dir is $XDG_STATE_HOME/dotclaude/memory.git and its work tree
$CLAUDE_CONFIG_DIR/projects; only */memory/** is tracked, so transcripts never are. A memory
file changed by any means, Bash included, is committed at the next fire. A live index.lock (another
session committing) makes a fire skip quietly; a stale one is cleared."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "memory-git.sh")
SID = "4c9dfc5e-45ab-47c6-8a18-8c674f3ff52b"


class MemoryGit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cfg = os.path.join(self.tmp, "claude")
        self.proj = os.path.join(self.cfg, "projects", "-home-hayden-code-karaoke")
        self.mem = os.path.join(self.proj, "memory")
        os.makedirs(self.mem)
        self.write(os.path.join(self.mem, "MEMORY.md"), "- [Karaoke](karaoke.md)\n")
        self.write(os.path.join(self.mem, "karaoke.md"), "vision\n")
        self.write(os.path.join(self.proj, SID + ".jsonl"), '{"type":"user"}\n')
        os.makedirs(os.path.join(self.proj, SID, "subagents"))
        self.write(os.path.join(self.proj, SID, "subagents", "agent-a.jsonl"), "{}\n")
        self.gd = os.path.join(self.tmp, "state", "dotclaude", "memory.git")
        self.env = dict(os.environ, CLAUDE_CONFIG_DIR=self.cfg,
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"))

    def write(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def fire(self, event="Stop", sid=SID):
        p = subprocess.run(["bash", HOOK], capture_output=True, text=True, env=self.env,
                           input=json.dumps({"hook_event_name": event, "session_id": sid}),
                           timeout=20)
        self.assertEqual((p.returncode, p.stdout), (0, ""), p.stderr)

    def git(self, *args):
        return subprocess.run(["git", "--git-dir", self.gd, *args], capture_output=True,
                              text=True, check=True).stdout

    def tracked(self):
        return sorted(self.git("ls-tree", "-r", "--name-only", "HEAD").split())

    def test_the_first_fire_commits_memory_and_only_memory(self):
        self.fire("SessionStart")
        self.assertEqual(self.tracked(), ["-home-hayden-code-karaoke/memory/MEMORY.md",
                                          "-home-hayden-code-karaoke/memory/karaoke.md"])
        self.assertEqual(self.git("log", "--format=%s").strip(), "SessionStart 4c9dfc5e")
        self.assertEqual(os.stat(self.gd).st_mode & 0o777, 0o700)

    def test_a_bash_made_edit_and_a_delete_are_committed_at_the_next_stop(self):
        self.fire("SessionStart")
        self.write(os.path.join(self.mem, "karaoke.md"), "PLACEHOLDER")
        os.remove(os.path.join(self.mem, "MEMORY.md"))
        self.fire("Stop")
        self.assertEqual(self.tracked(), ["-home-hayden-code-karaoke/memory/karaoke.md"])
        # The overwritten content is one commit back.
        self.assertEqual(self.git("show", "HEAD~1:-home-hayden-code-karaoke/memory/karaoke.md"),
                         "vision\n")

    def test_no_change_makes_no_commit(self):
        self.fire("SessionStart")
        self.fire("Stop")
        self.assertEqual(len(self.git("log", "--format=%H").split()), 1)

    def test_a_new_project_is_picked_up(self):
        self.fire("SessionStart")
        other = os.path.join(self.cfg, "projects", "-home-hayden-hq", "memory")
        os.makedirs(other)
        self.write(os.path.join(other, "hq.md"), "hq\n")
        self.write(os.path.join(self.cfg, "projects", "-home-hayden-hq", "x.jsonl"), "{}\n")
        self.fire("Stop")
        self.assertIn("-home-hayden-hq/memory/hq.md", self.tracked())
        self.assertNotIn("-home-hayden-hq/x.jsonl", self.tracked())

    def test_a_live_lock_skips_and_the_next_fire_commits(self):
        self.fire("SessionStart")
        lock = os.path.join(self.gd, "index.lock")
        self.write(lock, "")
        self.write(os.path.join(self.mem, "karaoke.md"), "v2\n")
        self.fire("Stop")
        self.assertEqual(len(self.git("log", "--format=%H").split()), 1)
        os.remove(lock)
        self.fire("Stop")
        self.assertEqual(self.git("show", "HEAD:-home-hayden-code-karaoke/memory/karaoke.md"),
                         "v2\n")

    def test_a_stale_lock_is_cleared(self):
        self.fire("SessionStart")
        lock = os.path.join(self.gd, "index.lock")
        self.write(lock, "")
        old = time.time() - 300
        os.utime(lock, (old, old))
        self.write(os.path.join(self.mem, "karaoke.md"), "v2\n")
        self.fire("Stop")
        self.assertEqual(len(self.git("log", "--format=%H").split()), 2)

    def test_concurrent_fires_never_fail_and_the_next_fire_catches_up(self):
        # A fire that meets another's lock skips by design; nothing is lost, because the next
        # trigger commits what it skipped.
        self.fire("SessionStart")
        self.write(os.path.join(self.mem, "karaoke.md"), "v2\n")
        self.write(os.path.join(self.mem, "MEMORY.md"), "v2\n")
        procs = [subprocess.Popen(["bash", HOOK], stdin=subprocess.PIPE, env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(4)]
        for p in procs:
            p.communicate(json.dumps({"hook_event_name": "Stop"}).encode(), timeout=20)
            self.assertEqual(p.returncode, 0)
        self.fire("Stop")  # whatever a skipped fire left is committed by the next one
        for name in ("karaoke.md", "MEMORY.md"):
            self.assertEqual(self.git("show", f"HEAD:-home-hayden-code-karaoke/memory/{name}"),
                             "v2\n")

    def test_no_projects_dir_or_an_unwritable_state_dir_exits_quietly(self):
        shutil.rmtree(os.path.join(self.cfg, "projects"))
        self.fire()
        self.assertFalse(os.path.exists(self.gd))
        os.makedirs(self.mem)
        blocked = os.path.join(self.tmp, "blocked")
        self.write(blocked, "")
        self.env["XDG_STATE_HOME"] = blocked
        self.fire()


if __name__ == "__main__":
    unittest.main()
