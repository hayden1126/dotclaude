"""hooks/overwrite-guard.sh: the PreToolUse(Write) guard against blind overwrites (stdlib only).

A Write over an existing, non-empty file is denied unless this session's transcript shows a
successful Read, Write or Edit of it (read-proof), and denied when it would cut a file of 1 KB or
more to under a fifth (shrink). The transcripts here are synthetic, in the shapes real ones use:
a tool_use in an assistant message, its tool_result in the next user entry (is_error on a deny),
a subagent's transcript at <session>/subagents/agent-<id>.jsonl. Incident 1 of
docs/blind-overwrite-brief.md is the first case."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "overwrite-guard.sh")
SID = "4c9dfc5e-45ab-47c6-8a18-8c674f3ff52b"


def use(tid, name, **inp):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, error=False):
    block = {"tool_use_id": tid, "type": "tool_result", "content": "ok"}
    if error:
        block.update(is_error=True, content="PreToolUse:Write hook error: denied")
    return {"type": "user", "message": {"role": "user", "content": [block]}}


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.state = os.path.join(self.tmp, "state")
        self.proj = os.path.join(self.tmp, "projects", "-home-hayden-code-karaoke")
        os.makedirs(os.path.join(self.proj, "memory"))
        self.file = os.path.join(self.proj, "memory", "karaoke-personal-product.md")
        self.write(self.file, "x" * 6284)
        self.transcript = os.path.join(self.proj, SID + ".jsonl")
        self.entries([])

    def write(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def entries(self, rows, path=None):
        path = path or self.transcript
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # A memory index attachment names the file without its content: no proof.
        head = {"type": "attachment", "attachment": {"type": "instructions", "files": [
            {"path": os.path.join(self.proj, "memory", "MEMORY.md"),
             "content": "- [Karaoke](karaoke-personal-product.md)"}]}}
        # Raw UTF-8, as Claude Code writes them: a non-ASCII name is not \u-escaped.
        with open(path, "w", encoding="utf-8") as f:
            for r in [head] + rows:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")

    def fire(self, content="PLACEHOLDER", path=None, **extra):
        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.tmp,
                 "hook_event_name": "PreToolUse", "tool_name": "Write",
                 "tool_input": {"file_path": path or self.file, "content": content}, **extra}
        env = dict(os.environ, XDG_STATE_HOME=self.state, **getattr(self, "fire_env", {}))
        p = subprocess.run(["bash", HOOK], input=json.dumps(event), capture_output=True,
                           text=True, env=env, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def log(self):
        try:
            with open(os.path.join(self.state, "dotclaude", "overwrite-guard.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def assertDenied(self, out, rule):
        self.assertIsNotNone(out, "expected a deny")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn(f"deny {rule}", self.log())

    def test_the_incident_is_denied_by_read_proof(self):
        out = self.fire()
        self.assertDenied(out, "read-proof")
        self.assertIn("has not read it", out["permissionDecisionReason"])
        self.assertIn("6284 bytes", out["permissionDecisionReason"])

    def test_a_new_file_or_an_empty_one_is_allowed(self):
        self.assertIsNone(self.fire(path=os.path.join(self.proj, "memory", "new.md")))
        empty = os.path.join(self.proj, "empty.md")
        self.write(empty, "")
        self.assertIsNone(self.fire(path=empty))

    def test_a_read_then_a_full_write_is_allowed(self):
        self.entries([use("toolu_1", "Read", file_path=self.file), result("toolu_1")])
        self.assertIsNone(self.fire("y" * 6000))

    def test_a_read_then_a_stub_is_denied_by_shrink(self):
        self.entries([use("toolu_1", "Read", file_path=self.file), result("toolu_1")])
        out = self.fire()
        self.assertDenied(out, "shrink")
        self.assertIn("from 6284 to 11 bytes", out["permissionDecisionReason"])

    def test_shrink_spares_small_files_and_moderate_cuts(self):
        self.entries([use("toolu_1", "Read", file_path=self.file), result("toolu_1")])
        self.assertIsNone(self.fire("y" * 1300))   # just over a fifth of 6284
        small = os.path.join(self.proj, "small.md")
        self.write(small, "z" * 1000)
        self.entries([use("toolu_2", "Read", file_path=small), result("toolu_2")])
        self.assertIsNone(self.fire("hi", path=small))

    def test_an_earlier_write_or_edit_is_proof(self):
        for name in ("Write", "Edit", "MultiEdit"):
            with self.subTest(tool=name):
                self.entries([use("toolu_1", name, file_path=self.file), result("toolu_1")])
                self.assertIsNone(self.fire("y" * 6000))

    def bash(self, command, cwd=None, error=False):
        call = use("toolu_1", "Bash", command=command)
        call["cwd"] = cwd or self.proj  # each transcript entry carries the cwd it ran in
        self.entries([call, result("toolu_1", error)])
        return self.fire("y" * 6000)

    def test_a_bash_command_naming_the_files_path_is_proof(self):
        name = os.path.basename(self.file)
        for command in (f"cat memory/{name}", f"cat ./memory/{name}", f"head -50 '{self.file}'",
                        f"python3 - <<'EOF'\np='memory/{name}'\nEOF"):
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))
        self.assertIsNone(self.bash(f"cat {name}", cwd=os.path.join(self.proj, "memory")))

    def test_a_bash_command_naming_the_path_another_way_is_proof(self):
        name = os.path.basename(self.file)
        sub = os.path.join(self.proj, "spikes")
        self.assertIsNone(self.bash(f"cat ../memory/{name}", cwd=sub))
        self.fire_env = {"HOME": self.tmp}
        self.assertIsNone(self.bash(f"cat ~/projects/-home-hayden-code-karaoke/memory/{name}"))
        spaced = os.path.join(self.proj, "my notes.md")
        self.write(spaced, "z" * 2000)
        call = use("toolu_1", "Bash", command="cat my\\ notes.md")
        call["cwd"] = self.proj
        self.entries([call, result("toolu_1")])
        self.assertIsNone(self.fire("y" * 2000, path=spaced))

    def test_a_bash_command_naming_another_file_is_no_proof(self):
        name = os.path.basename(self.file)
        for command, cwd in (("cat memory/MEMORY.md", None),
                             (f"cat {name}", None),                        # not in this cwd
                             (f"cat other/memory/{name}", None),
                             (f"cat memory/{name}.bak", None),
                             (f"cat memory/{name}~", None),               # an editor backup
                             (f"cat memory/{name}\\ copy", None),         # a longer name
                             (f"cat old\\ {name}", os.path.join(self.proj, "memory")),
                             (f"cat memory/{name}", os.path.join(self.tmp, "elsewhere"))):
            with self.subTest(command=command, cwd=cwd):
                self.assertDenied(self.bash(command, cwd), "read-proof")
        self.assertDenied(self.bash(f"cat {self.file}", error=True), "read-proof")

    def test_dotdot_resolves_from_the_real_cwd(self):
        # cwd is a link into another tree: the shell's ../ is the real parent, not the link's.
        elsewhere = os.path.join(self.tmp, "data", "r", "d")
        os.makedirs(elsewhere)
        link = os.path.join(self.proj, "memory", "sub")
        os.symlink(elsewhere, link)
        name = os.path.basename(self.file)
        self.assertDenied(self.bash(f"cat ../{name}", cwd=link), "read-proof")

    def test_a_denied_or_failed_call_is_no_proof(self):
        self.entries([use("toolu_1", "Write", file_path=self.file, content="PLACEHOLDER"),
                      result("toolu_1", error=True)])
        self.assertDenied(self.fire("y" * 6000), "read-proof")

    def test_a_call_with_no_result_yet_is_no_proof(self):
        # A Read in the same parallel batch as the Write has no result when the Write is judged.
        self.entries([use("toolu_1", "Read", file_path=self.file)])
        self.assertDenied(self.fire("y" * 6000), "read-proof")

    def test_another_file_with_the_same_name_is_no_proof(self):
        other = os.path.join(self.tmp, "terrarium", "karaoke-personal-product.md")
        os.makedirs(os.path.dirname(other))
        self.write(other, "other")
        self.entries([use("toolu_1", "Read", file_path=other), result("toolu_1")])
        self.assertDenied(self.fire("y" * 6000), "read-proof")

    def test_a_relative_or_symlinked_path_matches(self):
        link = os.path.join(self.tmp, "mem")
        os.symlink(os.path.join(self.proj, "memory"), link)
        self.entries([use("toolu_1", "Read", file_path=os.path.relpath(self.file, self.tmp)),
                      result("toolu_1")])
        self.assertIsNone(self.fire("y" * 6000, path=os.path.join(link, os.path.basename(self.file))))

    def test_a_symlink_with_another_name_matches(self):
        # Read through the link, Write through the link: the line names the link, not the target.
        link = os.path.join(self.tmp, "notes.md")
        os.symlink(self.file, link)
        self.entries([use("toolu_1", "Read", file_path=link), result("toolu_1")])
        self.assertIsNone(self.fire("y" * 6000, path=link))
        call = use("toolu_1", "Bash", command="cat notes.md")
        call["cwd"] = self.tmp
        self.entries([call, result("toolu_1")])
        self.assertIsNone(self.fire("y" * 6000, path=link))

    def test_a_read_through_a_link_with_another_name_proves_the_target(self):
        link = os.path.join(self.tmp, "alias.md")
        os.symlink(self.file, link)
        self.entries([use("toolu_1", "Read", file_path=link), result("toolu_1")])
        self.assertIsNone(self.fire("y" * 6000))
        # The fallback still pairs results: a failed Read through the link is no proof.
        self.entries([use("toolu_1", "Read", file_path=link), result("toolu_1", error=True)])
        self.assertDenied(self.fire("y" * 6000), "read-proof")

    def test_notebook_edit_and_an_instructions_file_are_proof(self):
        self.entries([use("toolu_1", "NotebookEdit", notebook_path=self.file), result("toolu_1")])
        self.assertIsNone(self.fire("y" * 6000))
        self.entries([{"type": "attachment", "attachment": {"type": "instructions", "files": [
            {"path": self.file, "content": "x"}]}}])
        self.assertIsNone(self.fire("y" * 6000))

    def test_a_malformed_entry_skips_only_itself(self):
        name = os.path.basename(self.file)
        bad = [{"type": "attachment", "attachment": {"type": "instructions", "files": 7,
                                                     "note": name}},
               {"type": "user", "message": f"a string message naming {name}"},
               dict(use("toolu_0", "Bash", command=f"cat memory/{name}"), cwd=5)]
        self.entries(bad + [use("toolu_1", "Read", file_path=self.file), result("toolu_1")])
        self.assertIsNone(self.fire("y" * 6000))
        self.entries(bad)
        self.assertDenied(self.fire("y" * 6000), "read-proof")
        self.assertNotIn("no-transcript", self.log())

    def test_a_non_ascii_name_matches(self):
        cafe = os.path.join(self.proj, "café — notes.md")
        self.write(cafe, "z" * 2000)
        self.assertDenied(self.fire("y" * 2000, path=cafe), "read-proof")
        self.entries([use("toolu_1", "Read", file_path=cafe), result("toolu_1")])
        self.assertIsNone(self.fire("y" * 2000, path=cafe))

    def test_an_at_mention_is_proof(self):
        self.entries([{"type": "attachment", "attachment": {
            "type": "file", "filename": self.file, "displayPath": "x", "content": {}}}])
        self.assertIsNone(self.fire("y" * 6000))

    def test_a_subagent_is_judged_by_its_own_transcript(self):
        agent_transcript = os.path.join(self.proj, SID, "subagents", "agent-a1b2c3.jsonl")
        # The parent read it; the subagent did not.
        self.entries([use("toolu_1", "Read", file_path=self.file), result("toolu_1")])
        self.entries([], path=agent_transcript)
        self.assertDenied(self.fire("y" * 6000, agent_id="a1b2c3"), "read-proof")
        self.entries([use("toolu_9", "Read", file_path=self.file), result("toolu_9")],
                     path=agent_transcript)
        self.assertIsNone(self.fire("y" * 6000, agent_id="a1b2c3"))

    def test_no_transcript_skips_read_proof_but_keeps_shrink(self):
        os.remove(self.transcript)
        self.assertIsNone(self.fire("y" * 6000))
        self.assertIn("no-transcript", self.log())
        self.assertDenied(self.fire(), "shrink")

    def test_garbage_lines_are_skipped(self):
        with open(self.transcript, "a") as f:
            f.write('{"broken karaoke-personal-product.md\n')
        self.assertDenied(self.fire("y" * 6000), "read-proof")

    def test_fails_open(self):
        # Bad input, and a state dir that can't be written: the Write goes through.
        p = subprocess.run(["bash", HOOK], input="not json", capture_output=True, text=True,
                           env=dict(os.environ, XDG_STATE_HOME=self.state), timeout=10)
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertIn("error", self.log())
        blocked = os.path.join(self.tmp, "blocked")
        self.write(blocked, "")  # a file where the state dir should be
        p = subprocess.run(["bash", HOOK], input="not json", capture_output=True, text=True,
                           env=dict(os.environ, XDG_STATE_HOME=blocked), timeout=10)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_other_tools_pass(self):
        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.tmp,
                 "tool_name": "Edit", "tool_input": {"file_path": self.file}}
        p = subprocess.run(["bash", HOOK], input=json.dumps(event), capture_output=True,
                           text=True, env=dict(os.environ, XDG_STATE_HOME=self.state))
        self.assertEqual(p.stdout, "")


if __name__ == "__main__":
    unittest.main()
