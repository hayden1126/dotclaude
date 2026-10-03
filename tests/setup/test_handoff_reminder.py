"""hooks/handoff-reminder.sh: fires on a terse wrap-up command, never on injected content or
discussion (stdlib only)."""
import json
import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "handoff-reminder.sh")


def fires(prompt):
    p = subprocess.run(["bash", HOOK], input=json.dumps({"prompt": prompt}),
                       capture_output=True, text=True, timeout=10)
    assert p.returncode == 0, p.stderr
    return "[handoff-reminder]" in p.stdout


class HandoffReminder(unittest.TestCase):
    def test_a_terse_wrap_up_command_fires(self):
        for prompt in ("let's wrap up", "/clear", "ok, hand off now", "call it a day"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

    def test_a_subagent_report_that_mentions_clear_is_silent(self):
        report = ("Another Claude session sent a message:\n<agent-message from=\"a1\">\n"
                  "[Subagent hand-back] The watch is adopted after /clear by the same process, "
                  "and the guard blocks once. Every suite is green.\n</agent-message>")
        self.assertFalse(fires(report))

    def test_a_short_subagent_message_with_a_wrap_up_phrase_is_silent(self):
        self.assertFalse(fires("<agent-message from=\"a1\">let's wrap up</agent-message>"))
        self.assertFalse(fires("<cross-session-message from=\"s\">wrap up</cross-session-message>"))

    def test_a_long_message_that_discusses_clear_is_silent(self):
        self.assertFalse(fires(
            "I wonder whether the watch guard adopts a lapse after /clear correctly when the "
            "sessions file lags behind the env var for a while"))

    def test_injected_content_is_silent(self):
        self.assertFalse(fires("<task-notification><status>killed</status></task-notification>"))


if __name__ == "__main__":
    unittest.main()
