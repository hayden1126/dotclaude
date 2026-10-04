"""hooks/handoff_reminder.py and its shim hooks/handoff-reminder.sh: fires on a terse wrap-up
command, never on injected content or discussion (stdlib only).

The prompt cases call classify() in-process; ShimEndToEnd runs the shim itself."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "handoff-reminder.sh")
MODULE = os.path.join(REPO, "hooks", "handoff_reminder.py")

_spec = importlib.util.spec_from_file_location("handoff_reminder", MODULE)
handoff_reminder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handoff_reminder)


def fires(prompt):
    return handoff_reminder.classify(prompt)


def run(payload, hook=HOOK, env=None):
    p = subprocess.run(["bash", hook], input=payload, capture_output=True, text=True,
                       timeout=10, env=env)
    assert p.returncode == 0, p.stderr
    assert not p.stderr, p.stderr
    return "[handoff-reminder]" in p.stdout


class HandoffReminder(unittest.TestCase):
    def test_a_terse_wrap_up_command_fires(self):
        for prompt in ("let's wrap up", "/clear", "ok, hand off now", "call it a day",
                       "okay let's wrap up", "great work. let's call it a day",
                       "can we stop here?", "handoff now", "let's handoff",
                       "please do a handoff", "let's wrap this up and hand off",
                       "clear the context please", "wrap up the session", "I'm wrapping up",
                       "great work \u2014 let's wrap up", "ok - let's wrap up",
                       "thanks let's wrap up", "it's time to wrap up", "let\u2019s wrap up",
                       "let's wrap up today", "let's wrap up \U0001F44D",
                       "sweep fixes, handoff then push", "handoff", "great work\u2014let's wrap up",
                       "let's wrap up :)", "let's wrap up now and push", "let's stop here then",
                       "let's wrap up and push the branch",
                       "let's stop here and commit what we have", "wrap up and clear",
                       "let's wrap up for this session", "done for the day", "handoff, then push.",
                       "calling it a day", "calling it a night", "I'm calling it for the night.",
                       "handoff, please", "handoff; then push", "let's wrap up and push everything"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

    def test_clear_next_to_punctuation_fires(self):
        for prompt in ("/clear?", "/clear,", "about to /clear.", "`/clear`",
                       "tests pass, no changes needed /clear", "merged without conflicts /clear",
                       "how about we /clear", "what if we /clear", "when you're done I'll /clear"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

    def test_a_wrap_up_phrase_that_is_not_a_command_is_silent(self):
        # Negated, a question about code, or a noun phrase: the phrase doesn't start its clause
        # or doesn't end it.
        for prompt in ("don't stop here, keep going", "why is the parser stopping here?",
                       "add an end session button", "clear the session cache on logout",
                       "don't wrap up yet", "no, don't wrap up", "hand off the parser to the API",
                       'what does "wrap up" trigger?', "wrap up the loop engineering doc",
                       "a handoff would help here", "/clearance", "src/clear/x",
                       "stop here and explain why the test fails",
                       "clear the context for each subagent", "hand off for review",
                       "don't /clear yet", "don't run /clear yet", "no /clear yet",
                       "can't /clear, it's greyed out"):
            with self.subTest(prompt=prompt):
                self.assertFalse(fires(prompt))

    def test_praise_and_identifiers_are_not_commands(self):
        # A phrase glued to an identifier, praise for a handoff, or a task that follows it.
        for prompt in ("clear the session_id on logout", "clear the context-menu listeners",
                       "wipe the memory-mapped cache", "clear the context \u2013 per subagent",
                       "great handoff!", "nice handoff, thanks", "perfect handoff.",
                       "nice wrap up!", "the loop exits early: it's stopping here.",
                       "stop here and call the parser on the fixture",
                       "stop here then explain why the test fails",
                       "handoff now works with worktrees?",
                       "handoff and memory curation are separate steps, right?",
                       "stop here's why", "wrap up/down", "handoff: does it update memory too?",
                       "handoff, memory, docs: what order?", "calling it here, I get a 404",
                       "what does `/clear` do?", "what about /clear?", "what does /clear do?",
                       "stop here and clear the cache",
                       "handoff and push notifications are both broken",
                       "stop here and push back on the reviewer's point", "no need to /clear yet",
                       "keep going without a /clear", "what's /clear for?"):
            with self.subTest(prompt=prompt):
                self.assertFalse(fires(prompt))

    def test_handoff_as_typed_in_an_action_list_fires(self):
        # How "handoff" is typed in practice: one action among others, often after a status line,
        # with or without commas.
        for prompt in ("emailed. handoff", "commit, handoff and push", "push and handoff",
                       "Merge the PRs and handoff", "handoff, commit and push", "handoff?",
                       "Save memory and hand off to a fresh session.", "Handoff while we wait.",
                       "handoff first", "handoff so we start with phase D next.",
                       "deploy handoff and push", "proceed handoff and push all",
                       "yes remove it, then do the handoff", "merged, check deploy and full handoff",
                       "proceed with the plan, but handoff to do it", "handoff, probably not on main?",
                       "[Image #4] handoff everything to a new session", "Hand off to a new session.",
                       "hand off if there is anything left", "What's next? Handoff",
                       "Can you do a quick handoff here for a fresh session.", "hand it off",
                       "I'll tell you the features first, then you handoff",
                       "also can we handoff before the next step?", "Good commit and handoff"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

    def test_a_long_status_that_ends_in_handoff_fires(self):
        status = ("checked the profile, added the link to the bio, sent the email to the group and "
                  "updated the sheet with the new numbers")
        self.assertTrue(fires(status + ". handoff"))
        self.assertTrue(fires(status + ", then commit and handoff"))
        self.assertTrue(fires(status + ". handoff, then push"))
        self.assertTrue(fires(status + ". handoff, thanks"))
        # Only the last clauses count, and a statement about it never does.
        self.assertFalse(fires(status + " and we talked about whether to handoff earlier"))
        self.assertFalse(fires(status + " and handoff updated the wrong file again"))

    def test_a_question_praise_or_delegation_about_handoff_is_silent(self):
        for prompt in ("do we need to handoff?", "was handoff ran recently?", "Good handoff.",
                       "/handoff", "merged, run /handoff", "So hand off is done? If yes push",
                       "hand off to another agent in another directory to test this",
                       "handoff needed?", "Anything we need to handoff for?",
                       "Another session needs to handoff, what is the best way to do it?",
                       "Handoff here, don't load the skill", "Did a full handoff run there?"):
            with self.subTest(prompt=prompt):
                self.assertFalse(fires(prompt))

    def test_more_command_forms_fire(self):
        for prompt in ("Do the handoff.", "do a quick handoff", "run the handoff", "run your handoff",
                       "merged the hook PR. handoff", "push the skill fix, then handoff",
                       "hand off to a new chat", "handoff everything to a fresh agent",
                       "handoff and push what is left", "handoff so the next session is clean",
                       "emailed. handoff. next session: start phase D", "handoff. back at 10:30",
                       "done \u2014 handoff", "hand this off", "hand everything off",
                       "tests pass lets wrap up", "redeploy, and fully wrap up without losing anything",
                       "stop here, then also push"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

    def test_statements_delegations_and_examples_are_silent(self):
        for prompt in ("handoff doesn't work", "handoff didn't update STATUS.md", "Handoff looks good.",
                       "handoff not needed, just push", "handoff can wait",
                       "Handoff complete. Continue from STATUS.md", "hand off to Codex",
                       "hand off the parser to Codex", "hand off to another agent",
                       "we need to properly wrap up the stream before closing",
                       "I don't think it's time to wrap up",
                       "Should we make a skill for deploys? eg check bugs, then handoff, then PR?",
                       "a release checklist, e.g. fix the tests and handoff"):
            with self.subTest(prompt=prompt):
                self.assertFalse(fires(prompt))

    def test_adversarial_input_is_fast(self):
        for prompt in ("a" + "=" * 50000 + " b", "let" + "!" * 200000 + "s wrap up",
                       "x " * 9 + "-" * 100000):
            with self.subTest(size=len(prompt)):
                start = time.time()
                fires(prompt)
                self.assertLess(time.time() - start, 2)

    def test_a_comma_then_another_task_is_not_a_wrap_up(self):
        self.assertFalse(fires("stop here, then explain why the test fails"))
        self.assertFalse(fires("stop here, and explain why the test fails"))
        self.assertFalse(fires("just stop here, then explain why the test fails"))
        self.assertFalse(fires("stop here, then clear the cache"))
        self.assertFalse(fires("stop here, then push back on X"))
        self.assertFalse(fires("stop here. Why did you change the config?"))
        for prompt in ("stop here, then push", "stop here, thanks",
                       "let's stop here, then explain what's left"):
            with self.subTest(prompt=prompt):
                self.assertTrue(fires(prompt))

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


    def test_a_huge_injected_prompt_is_silent(self):
        # About 1 MB in 14 words, so rule 3 lets it through; the marker on the first line still wins.
        self.assertFalse(fires("<task-notification>\n" + ("x" * 100000 + "\n") * 10
                               + "let's wrap up"))

    def test_an_empty_prompt_is_silent(self):
        self.assertFalse(fires(""))


class ShimEndToEnd(unittest.TestCase):
    """The shim passes the event to the module and stays silent, exit 0, on any failure."""

    def test_a_wrap_up_fires_and_other_prompts_are_silent(self):
        self.assertTrue(run(json.dumps({"prompt": "let's wrap up"})))
        self.assertFalse(run(json.dumps({"prompt": "fix the parser"})))

    def test_a_subagent_or_teammate_payload_is_silent(self):
        self.assertFalse(run(json.dumps({"prompt": "let's wrap up", "agent_id": "a1",
                                         "agent_type": "writer"})))

    def test_an_unreadable_payload_is_silent(self):
        self.assertFalse(run("not json"))
        self.assertFalse(run(json.dumps(["let's wrap up"])))
        self.assertFalse(run(json.dumps({"prompt": ["let's wrap up"]})))

    def test_a_lone_surrogate_does_not_break_the_read(self):
        self.assertTrue(run('{"prompt": "let\'s wrap up\\ud800"}'))

    def test_run_through_a_symlink_it_finds_the_module(self):
        # setup.sh links only the .sh into ~/.claude/hooks; the module stays in the repo.
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "handoff-reminder.sh")
            os.symlink(HOOK, link)
            self.assertTrue(run(json.dumps({"prompt": "let's wrap up"}), hook=link))

    def test_without_the_module_it_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "handoff-reminder.sh")
            shutil.copy(HOOK, copy)
            self.assertFalse(run(json.dumps({"prompt": "let's wrap up"}), hook=copy))

    def test_without_python3_it_is_silent(self):
        # The raw payload is no stand-in for the prompt, so no python3 means no reminder.
        with tempfile.TemporaryDirectory() as bin_dir:
            for tool in ("bash", "cat", "grep", "wc", "tr", "readlink"):
                os.symlink(shutil.which(tool), os.path.join(bin_dir, tool))
            env = {**os.environ, "PATH": bin_dir}
            self.assertFalse(run(json.dumps({"prompt": "/clear"}), env=env))
            self.assertFalse(run(json.dumps({"prompt": "let's wrap up"}), env=env))


if __name__ == "__main__":
    unittest.main()
