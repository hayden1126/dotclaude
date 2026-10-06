"""The settings baseline: the sandbox posture, the teammate pin, the hook wiring and the
permission rules.

A wrong type or a missing suffix here fails silently in Claude Code (an unknown value is
ignored; a hook that exits non-2 doesn't block), so the baseline is pinned by test."""
import json
import os
import re
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

    def test_the_ledger_cli_runs_outside_the_sandbox(self):
        # Inside the sandbox no session pid is visible, so `open` and `watch` would call every
        # agent orphaned (A3). A bare call runs outside; the policy denies it to agents.
        self.assertIn("delegation-ledger *", S["sandbox"]["excludedCommands"])

    def test_policy_file_lists_cover_the_sandbox_lists(self):
        # The file tools run outside the sandbox; the policy applies the same lists to them,
        # and keeps its own copy for machines without a sandbox block.
        fs = S["sandbox"]["filesystem"]
        self.assertLessEqual(set(fs["denyRead"]), set(POLICY["protect"]["read_denied"]))
        self.assertLessEqual({p for p in fs["denyWrite"] if p.startswith("~/dotclaude")},
                             set(POLICY["protect"]["write_denied"]))

    def test_code_that_runs_outside_the_sandbox_is_write_protected(self):
        # Sandbox audit, 2026-10-04. ccstatusline and the Notification hook run these unsandboxed
        # on every refresh or toast; setup.sh runs or installs the rest, including the plugins
        # and tools its JSON lists.
        deny = S["sandbox"]["filesystem"]["denyWrite"]
        for p in ("statusline", "notify-toast.ps1", "codex", "setup.sh", "merge-settings.py",
                  "setup-chrome-wsl.sh", "sync.sh", "chrome-debug.ps1", "git", "plugins",
                  "tools.json", "tmux", "setup-tmux.sh"):
            self.assertIn("~/dotclaude/" + p, deny)

    def test_tool_credentials_and_shell_history_are_read_protected(self):
        # Sandbox audit, 2026-10-04. `claude` and `codex` run outside the sandbox, so they
        # still reach their own files.
        deny = S["sandbox"]["filesystem"]["denyRead"]
        for p in ("~/.npmrc", "~/.docker/config.json", "~/.config/.wrangler", "~/.supabase",
                  "~/.azure", "~/.claude.json", "~/.codex/config.toml", "~/.zsh_history",
                  "~/.bash_history"):
            self.assertIn(p, deny)

    def test_tmux_state_and_sounds_are_wired_once(self):
        # tmux-state.sh exits at once outside a tab, so every machine carries it. The permission
        # sound lives in notify.sh, gated like stop-ring.sh: an inline one would ring for every
        # session, the canary's `claude -p` runs included.
        want = {"UserPromptSubmit": "busy", "PreToolUse": "busy", "PostToolUse": "busy",
                "Stop": "idle", "Notification": "wait"}
        for event, state in want.items():
            with self.subTest(event=event):
                tmux = [h for e in S["hooks"][event] for h in e["hooks"]
                        if "tmux-state.sh" in h["command"]]
                self.assertEqual([h["command"] for h in tmux],
                                 [f'bash "$HOME/.claude/hooks/tmux-state.sh" {state}'])
                # It runs on every tool call: a stuck tmux server may cost 5 s, not the default.
                self.assertEqual(tmux[0]["timeout"], 5)
        every = [c for entries in S["hooks"].values() for e in entries for c in
                 (h["command"] for h in e["hooks"])]
        self.assertFalse([c for c in every if "SoundPlayer" in c])
        self.assertEqual(commands("Notification", "permission_prompt"),
                         ['bash "$HOME/.claude/hooks/notify.sh"'])
        # Both sound hooks ask tmux where a background session is shown; bound them too.
        for event, script in (("Stop", "stop-ring.sh"), ("Notification", "notify.sh")):
            (h,) = [h for e in S["hooks"][event] for h in e["hooks"] if script in h["command"]]
            self.assertEqual(h["timeout"], 5, script)

    def test_wait_glyph_needs_a_real_ask(self):
        # An unmatched Notification hook painted the green wait glyph on idle_prompt too, so a
        # session that stopped with a shell still running (stop-ring quiet) turned green while
        # waiting on the shell, not on the person (karaoke, 2026-10-06).
        (entry,) = [e for e in S["hooks"]["Notification"]
                    if any("tmux-state.sh" in h["command"] for h in e["hooks"])]
        self.assertEqual(entry.get("matcher"), "permission_prompt|elicitation_dialog")
        self.assertNotIn("idle_prompt", entry["matcher"])

    def test_allow_write_holds_caches_not_bin_dirs(self):
        for p in S["sandbox"]["filesystem"]["allowWrite"]:
            self.assertNotIn("/bin", p, p)
            self.assertTrue(p.startswith("~/"), p)

    def test_policy_hook_filters_main_thread_and_fails_closed(self):
        (cmd,) = commands("PreToolUse", "*")
        self.assertIn('"agent_id"', cmd)
        self.assertIn("timeout 8", cmd)
        self.assertIn("exit 2", cmd)

    def test_the_deadline_nudge_runs_for_subagents_only_and_fails_open(self):
        # PostToolUse fires on every call, the main thread's too: the same prefilter as the
        # policy hook keeps Python off the main thread's path. A nudge is advice, so nothing
        # here may block a call.
        (entry,) = [e for e in S["hooks"]["PostToolUse"]
                    if any("delegation-ledger" in h["command"] for h in e["hooks"])]
        self.assertEqual(entry["matcher"], "*")
        (h,) = entry["hooks"]
        self.assertIn("""case "$i" in *'"agent_id"'*)""", h["command"])
        self.assertIn('bash "$HOME/.claude/hooks/delegation-ledger.sh"', h["command"])
        self.assertNotIn("exit 2", h["command"])
        self.assertLessEqual(h["timeout"], 5)

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

    def test_due_checks_run_at_session_start_and_fail_open(self):
        (entry,) = [e for e in S["hooks"]["SessionStart"]
                    if any("delegation-due.sh" in h["command"] for h in e["hooks"])]
        # Not on clear or compact: one nudge per session, not one per context reset.
        self.assertEqual(entry["matcher"], "startup|resume")
        (h,) = entry["hooks"]
        self.assertNotIn("exit 2", h["command"])
        self.assertLessEqual(h["timeout"], 10)  # the first reply waits for SessionStart hooks
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "delegation-due.sh"), os.X_OK))

    def test_the_watch_guard_is_wired_on_stop_and_fails_open(self):
        (entry,) = [e for e in S["hooks"]["Stop"]
                    if any("watch-guard.sh" in h["command"] for h in e["hooks"])]
        (h,) = entry["hooks"]
        self.assertEqual(h["command"], 'bash "$HOME/.claude/hooks/watch-guard.sh"')
        self.assertNotIn("exit 2", h["command"])  # it blocks by JSON, never by exit code
        self.assertLessEqual(h["timeout"], 10)  # every stop waits for it
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "watch-guard.sh"), os.X_OK))

    def test_a_rearm_never_waits_on_a_permission_prompt(self):
        self.assertIn("Bash(delegation-ledger wait *)", S["permissions"]["allow"])

    def test_destructive_git_is_denied_and_anything_that_can_reach_main_asks(self):
        # Claude Code matches a Bash rule as a glob whose * spans spaces, deny beats ask, and
        # ask beats allow (verified live on 2.1.288 in default and auto mode). Each part of a
        # compound command is checked on its own (verified in default mode). Wrappers other than
        # these bash -c forms (bash -lc, sh -c, eval, git -c k=v) are left to auto mode's
        # classifier. A rule can't see the current branch, so every push form that could land
        # on main without naming it (no refspec, HEAD, @, --all, --mirror, a leading flag) asks;
        # the explicit `git push origin <branch>` runs. Merges ask. Leaks, accepted (Hayden,
        # 2026-10-05): a refspec-less push with a flag after the branch-less remote is caught,
        # but `git push origin feat -u`-style trailing flags and other remotes are not checked.
        def matching(kind, command):
            return [rule for rule in S["permissions"][kind]
                    if re.fullmatch(re.escape(rule[len("Bash("):-1]).replace(r"\*", ".*"),
                                    command)]

        denied = ["git push --force origin feat", "git push -f origin feat",
                  "git push origin feat --force", "git push origin feat -f",
                  "git push --force-with-lease origin feat",
                  "git -C . push --force origin feat", "git -C . push -f origin feat",
                  "git -C . push origin feat --force", "git -C . push origin feat -f",
                  "git reset --hard", "git reset HEAD --hard",
                  "git -C . reset --hard", "git -C . reset HEAD --hard",
                  # --merge drops a staged change too; --keep refuses to.
                  "git reset --merge", "git reset HEAD --merge",
                  "git -C . reset --merge", "git -C . reset HEAD --merge",
                  "git clean -fd", "git clean -d -f", "git -C . clean -fd",
                  'bash -c "git push --force origin feat"', 'bash -c "git reset --hard"']
        asked = ["git push", "git push origin", "git push --no-verify", "git push -u origin feat",
                 "git push origin --no-verify", "git push origin main", "git push origin feat:main",
                 "git push origin HEAD", "git push origin @", "git push origin feat --all",
                 "git push origin feat --mirror", "git push origin :feat",
                 "git -C . push", "git -C . push origin feat",
                 # A force the deny rules miss still asks.
                 "git push origin +feat", "git push -uf origin feat",
                 "gh pr merge 5 --squash", "gh api -X PUT repos/o/r/pulls/5/merge"]
        # Pushes to a named branch and opening a PR run (Hayden still approves each in words).
        allowed = ["git push origin feat/x", "git push origin feat-force-fix",
                   "git push origin fix/x --follow-tags", "gh pr create --base main --head feat/x"]
        # rm never asks: the sandbox bounds where it writes, and subagent-policy keeps a
        # delegated rm -r in its root (README has the overlay that brings the asks back).
        neither = ['git commit -am "push --force docs"', "git status",
                   "git reset --keep HEAD~1", "git reset --soft HEAD~1",
                   "rm a.txt", "rm -rf build", "rm -R build", "rm -f a.txt", "rm build -r",
                   "rm -v draft.txt"]
        for c in denied:
            self.assertTrue(matching("deny", c), c)
        for c in asked:
            self.assertFalse(matching("deny", c), c)
            self.assertTrue(matching("ask", c), c)
        for c in neither:
            self.assertFalse(matching("deny", c) + matching("ask", c), c)
        for c in allowed:
            self.assertFalse(matching("deny", c) + matching("ask", c), c)
            self.assertTrue(matching("allow", c), c)
        for c in asked:  # ask beats allow, so an allow rule may cover these too
            self.assertTrue(matching("ask", c), c)
        # Every rule is the only one of its kind that catches some case, so dropping one fails.
        for kind, cases in (("deny", denied), ("ask", asked)):
            for rule in S["permissions"][kind]:
                self.assertIn([rule], [matching(kind, c) for c in cases], rule)

    def test_the_stop_sound_rings_for_the_main_session_only(self):
        # Stop fires for subagents too; an inline sound rang for every one of them.
        stops = commands("Stop")
        self.assertIn('bash "$HOME/.claude/hooks/stop-ring.sh"', stops)
        self.assertFalse(any("powershell.exe" in c for c in stops), stops)
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "stop-ring.sh"), os.X_OK))


if __name__ == "__main__":
    unittest.main()
