"""The settings baseline: the sandbox posture, the teammate pin and the hook wiring.

A wrong type or a missing suffix here fails silently in Claude Code (an unknown value is
ignored; a hook that exits non-2 doesn't block), so the baseline is pinned by test."""
import json
import os
import unittest

from _paths import REPO, load_script

with open(os.path.join(REPO, "settings.json")) as f:
    S = json.load(f)
POLICY = load_script("subagent-policy").load_policy()


def commands(event, matcher=None):
    return [h["command"] for entry in S["hooks"].get(event, [])
            if matcher is None or entry.get("matcher") == matcher for h in entry["hooks"]]


class Baseline(unittest.TestCase):
    def test_teammates_stay_in_process(self):
        # Split-pane teammates are separate processes whose hook input has no agent_id, so
        # the subagent policy would never see them.
        self.assertEqual(S["teammateMode"], "in-process")

    def test_sandbox_posture(self):
        sb = S["sandbox"]
        # Booleans, per the 2.1.285 binary schema (the settings reference shows a string enum
        # for allowUnsandboxedCommands; the binary wins).
        self.assertIs(sb["enabled"], True)
        self.assertIs(sb["failIfUnavailable"], True)  # no silent unsandboxed fallback
        self.assertIs(sb["autoAllowBashIfSandboxed"], False)  # keep Hayden's prompts
        self.assertIs(sb["allowUnsandboxedCommands"], True)  # the main thread's escape

    def test_excluded_patterns_have_a_form_claude_code_matches(self):
        # Live probe, 2026-09-30: "cp *" matched `cp a b`, a bare "touch" did not match
        # `touch x`. Multi-word exact forms ("git push") cover the argument-less call.
        for pat in S["sandbox"]["excludedCommands"]:
            self.assertTrue(pat.endswith(" *") or len(pat.split()) >= 2, pat)

    def test_the_credential_barrier_covers_github(self):
        fs = S["sandbox"]["filesystem"]
        self.assertIn("~/.config/gh", fs["denyRead"])
        excluded = S["sandbox"]["excludedCommands"]
        for pat in ("git push *", "git fetch *", "git pull *", "gh *"):
            self.assertIn(pat, excluded)
        self.assertNotIn("git clone *", excluded)  # it stays sandboxed: public clones only

    def test_policy_file_lists_cover_the_sandbox_lists(self):
        # The file tools run outside the sandbox; the policy applies the same lists to them,
        # and keeps its own copy for machines without a sandbox block.
        fs = S["sandbox"]["filesystem"]
        self.assertLessEqual(set(fs["denyRead"]), set(POLICY["protect"]["read_denied"]))
        self.assertLessEqual({p for p in fs["denyWrite"] if p.startswith("~/dotclaude")},
                             set(POLICY["protect"]["write_denied"]))

    def test_allow_write_holds_caches_not_bin_dirs(self):
        for p in S["sandbox"]["filesystem"]["allowWrite"]:
            self.assertNotIn("/bin", p, p)
            self.assertTrue(p.startswith("~/"), p)

    def test_policy_hook_filters_main_thread_and_fails_closed(self):
        (cmd,) = commands("PreToolUse", "*")
        self.assertIn('"agent_id"', cmd)
        self.assertIn("timeout 8", cmd)
        self.assertIn("exit 2", cmd)

    def test_spawn_guard_fails_closed_on_a_missing_link(self):
        (cmd,) = commands("PreToolUse", "Agent|Task")
        self.assertTrue(cmd.endswith("|| exit 2"), cmd)

    def test_report_check_is_wired_and_fails_open(self):
        (cmd,) = commands("PreToolUse", "SubagentHandback")
        self.assertIn("report-check.sh", cmd)
        stops = commands("SubagentStop")
        self.assertTrue(any("report-check.sh" in c for c in stops))
        self.assertTrue(any("delegation-ledger.sh" in c for c in stops))
        for c in [cmd] + [c for c in stops if "report-check" in c]:
            self.assertNotIn("exit 2", c)


if __name__ == "__main__":
    unittest.main()
