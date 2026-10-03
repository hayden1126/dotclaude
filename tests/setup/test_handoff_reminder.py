"""hooks/handoff-reminder.sh: fires on a terse wrap-up command, never on injected content or
discussion (stdlib only)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "handoff-reminder.sh")


def run(payload, env=None):
    p = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True,
                       timeout=10, env=env)
    assert p.returncode == 0, p.stderr
    return "[handoff-reminder]" in p.stdout


def fires(prompt, **extra):
    return run(json.dumps({"prompt": prompt, **extra}))


class HandoffReminder(unittest.TestCase):
    def test_a_terse_wrap_up_command_fires(self):
        for prompt in ("let's wrap up", "/clear", "ok, hand off now", "call it a day",
                       "okay let's wrap up", "great work. let's call it a day",
                       "can we stop here?", "handoff now", "let's handoff",
                       "please do a handoff", "let's wrap this up and hand off",
                       "clear the context please", "wrap up the session", "I'm wrapping up"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

    def test_clear_next_to_punctuation_fires(self):
        for prompt in ("/clear?", "/clear,", "about to /clear.", "`/clear`"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

    def test_a_wrap_up_phrase_that_is_not_a_command_is_silent(self):
        # Negated, a question about code, or a noun phrase: the phrase doesn't start its clause
        # or doesn't end it.
        for prompt in ("don't stop here, keep going", "why is the parser stopping here?",
                       "add an end session button", "clear the session cache on logout",
                       "don't wrap up yet", "no, don't wrap up", "hand off the parser to the API",
                       'what does "wrap up" trigger?', "wrap up the loop engineering doc",
                       "a handoff would help here", "handoff?", "/clearance", "src/clear/x"):
            with self.subTest(prompt=prompt):
                self.assertFalse(fires(prompt))

    def test_talk_about_the_handoff_skill_is_silent(self):
        self.assertFalse(fires("the handoff skill fires too often"))

    def test_a_subagent_report_that_mentions_clear_is_silent(self):
        report = ("Another Claude session sent a message:\n<agent-message from=\"a1\">\n"
                  "[Subagent hand-back] The watch is adopted after /clear by the same process, "
                  "and the guard blocks once. Every suite is green.\n</agent-message>")
        self.assertFalse(fires(report))

    def test_a_short_agent_or_session_message_with_a_wrap_up_phrase_is_silent(self):
        for prompt in ('<agent-message from="a1">let\'s wrap up</agent-message>',
                       '<cross-session-message from="s">wrap up</cross-session-message>',
                       '<teammate-message from="t">wrap up</teammate-message>',
                       "[Subagent hand-back] let's wrap up"):
            with self.subTest(prompt=prompt):
                self.assertFalse(fires(prompt))

    def test_a_long_message_is_silent(self):
        self.assertFalse(fires(
            "I wonder whether the watch guard adopts a lapse after /clear correctly when the "
            "sessions file lags behind the env var for a while"))
        self.assertFalse(fires(
            "let's wrap up, but first tell me whether the parser tests cover the empty input "
            "case and the unicode case too"))

    def test_injected_content_is_silent(self):
        self.assertFalse(fires("<task-notification><status>killed</status></task-notification>"))

    def test_a_subagent_or_teammate_payload_is_silent(self):
        self.assertFalse(fires("let's wrap up", agent_id="a1", agent_type="writer"))

    def test_a_huge_injected_prompt_is_silent(self):
        # About 1 MB in 14 words, so rule 3 lets it through: grep -q quits at the marker on the
        # first line, which must not read as "no match" (printf | grep -q under pipefail did).
        self.assertFalse(fires("<task-notification>\n" + ("x" * 100000 + "\n") * 10
                               + "let's wrap up"))

    def test_an_unreadable_payload_is_silent(self):
        self.assertFalse(run("not json"))
        self.assertFalse(run(json.dumps(["let's wrap up"])))
        self.assertFalse(fires(""))

    def test_a_lone_surrogate_does_not_break_the_read(self):
        self.assertTrue(run('{"prompt": "let\'s wrap up\\ud800"}'))

    def test_without_python3_it_is_silent(self):
        # The raw payload is no stand-in for the prompt, so no python3 means no reminder.
        with tempfile.TemporaryDirectory() as bin_dir:
            for tool in ("bash", "cat", "grep", "wc", "tr"):
                os.symlink(shutil.which(tool), os.path.join(bin_dir, tool))
            env = {**os.environ, "PATH": bin_dir}
            self.assertFalse(run(json.dumps({"prompt": "/clear"}), env=env))
            self.assertFalse(run(json.dumps({"prompt": "let's wrap up"}), env=env))


if __name__ == "__main__":
    unittest.main()
