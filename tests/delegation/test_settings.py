"""The settings baseline: the sandbox posture, the teammate pin, the hook wiring and the
permission rules.

A wrong type or a missing suffix here fails silently in Claude Code (an unknown value is
ignored; a hook that exits non-2 doesn't block), so the baseline is pinned by test."""
import contextlib
import glob
import io
import json
import os
import re
import shutil
import subprocess
import unittest

import command_inventory as inv
from _paths import REPO, load_script

with open(os.path.join(REPO, "settings.json")) as f:
    S = json.load(f)
POLICY = load_script("subagent-policy").load_policy()


def glob_match(pattern, command):
    """Claude Code matches a Bash rule or an excludedCommands pattern as a glob whose * spans
    spaces (verified live on 2.1.288)."""
    return re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), command) is not None


def matching(kind, command):
    """The permission rules of this kind that match a Bash command."""
    return [rule for rule in S["permissions"][kind] if glob_match(rule[len("Bash("):-1], command)]


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
        # A one-word exact form ("pass-respawn") is allowed only beside its " *" twin, which
        # carries every call with an argument; whether the one-word form matches the bare call
        # is unprobed, so /pass passes an argument.
        excluded = S["sandbox"]["excludedCommands"]
        for pat in excluded:
            self.assertTrue(pat.endswith(" *") or len(pat.split()) >= 2
                            or f"{pat} *" in excluded, pat)

    def test_the_credential_barrier_covers_github(self):
        fs = S["sandbox"]["filesystem"]
        self.assertIn("~/.config/gh", fs["denyRead"])
        excluded = S["sandbox"]["excludedCommands"]
        for pat in ("git push origin *", "git fetch *", "git pull *", "gh pr *", "gh api *"):
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
        # and tools its JSON lists; the canary (an excluded command) runs tests/.
        deny = S["sandbox"]["filesystem"]["denyWrite"]
        for p in ("statusline", "notify-toast.ps1", "codex", "setup.sh", "merge-settings.py",
                  "install-state.py", "setup-chrome-wsl.sh", "sync.sh", "chrome-debug.ps1",
                  "git", "plugins", "tools.json", "tmux", "setup-tmux.sh", "bin", "tests"):
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
        # stop-ring gets 10 s: it may read a big transcript cold to tell a Monitor from a
        # background Bash (PLAN.md A10; 2.5 s cold for 128 MiB), and a kill drops the ring and
        # the stop record. A normal ring still takes milliseconds.
        for event, script, limit in (("Stop", "stop-ring.sh", 10),
                                     ("Notification", "notify.sh", 5)):
            (h,) = [h for e in S["hooks"][event] for h in e["hooks"] if script in h["command"]]
            self.assertEqual(h["timeout"], limit, script)

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

    def test_the_overwrite_guard_is_wired_on_write_and_fails_open(self):
        # The Write tool's own read-before-write check last fired in 2.1.285. The guard runs
        # on every Write, the main thread's included, and denies by JSON, never by exit code.
        (cmd,) = commands("PreToolUse", "Write")
        self.assertEqual(cmd, 'bash "$HOME/.claude/hooks/overwrite-guard.sh"')
        (entry,) = [e for e in S["hooks"]["PreToolUse"] if e.get("matcher") == "Write"]
        self.assertLessEqual(entry["hooks"][0]["timeout"], 5)
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "overwrite-guard.sh"), os.X_OK))

    def test_the_pass_banner_is_wired_on_startup_only(self):
        # A /pass respawn starts as `startup`; the banner shows what the old session said in its
        # last turn, once. The first reply waits for SessionStart hooks, so the timeout stays
        # short.
        banner = 'bash "$HOME/.claude/hooks/pass-banner.sh"'
        self.assertEqual(commands("SessionStart", "startup"), [banner])
        (h,) = [h for e in S["hooks"]["SessionStart"] for h in e["hooks"]
                if "pass-banner" in h["command"]]
        self.assertEqual(h["timeout"], 5)
        self.assertEqual([c for entries in S["hooks"].values() for e in entries
                          for c in (h["command"] for h in e["hooks"]) if "pass-banner" in c],
                         [banner])
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "pass-banner.sh"), os.X_OK))
        self.assertTrue(os.path.exists(os.path.join(REPO, "hooks", "pass_banner.py")))

    def test_the_context_watcher_is_wired_on_stop_and_main_thread_tool_calls(self):
        # PLAN.md "PR 4": the tiers block a Stop, and reach long autonomous turns through
        # PostToolUse. PostToolUse fires on every call, a subagent's too, so the inline
        # pre-filter skips agent_id payloads before any Python starts. It never blocks by exit
        # code.
        watch = 'bash "$HOME/.claude/hooks/context-watch.sh"'
        self.assertIn(watch, commands("Stop"))
        (entry,) = [e for e in S["hooks"]["PostToolUse"]
                    if any("context-watch" in h["command"] for h in e["hooks"])]
        self.assertEqual(entry["matcher"], "*")
        (h,) = entry["hooks"]
        self.assertEqual(h["command"], "i=$(cat); case \"$i\" in *'\"agent_id\"'*) ;; *) "
                         "printf '%s' \"$i\" | " + watch + " ;; esac")
        hooks = [(event, h) for event in ("Stop", "PostToolUse") for e in S["hooks"][event]
                 for h in e["hooks"] if "context-watch" in h["command"]]
        self.assertEqual(len(hooks), 2)
        for event, h in hooks:
            # A Stop waits up to 1.5 s for the turn's final reply (spike A8), then may run tmux
            # and git, so it gets more room than a tool call.
            self.assertEqual(h["timeout"], 10 if event == "Stop" else 5)
            self.assertNotIn("exit 2", h["command"])
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "context-watch.sh"), os.X_OK))
        for f in ("context_watch.py", "autopass_state.py"):
            self.assertTrue(os.path.exists(os.path.join(REPO, "hooks", f)))

    def test_autopass_is_a_mod_command_not_a_prompt_hook(self):
        # skills/autopass is a mod (<name>@skills-dir): it registers /autopass as an immediate
        # command and runs hooks/autopass_toggle.py. A SKILL.md of the same name would make
        # the registration refuse and lose `immediate` (spike 3), and no settings hook answers it.
        self.assertFalse([h for entries in S["hooks"].values() for e in entries
                          for h in e["hooks"] if "autopass" in h["command"]])
        mod = os.path.join(REPO, "skills", "autopass")
        self.assertFalse(os.path.exists(os.path.join(mod, "SKILL.md")))
        with open(os.path.join(mod, ".claude-plugin", "plugin.json")) as f:
            self.assertEqual(json.load(f)["name"], "autopass")
        with open(os.path.join(mod, "hooks", "hooks.json")) as f:
            self.assertEqual(json.load(f), {"modules": ["./register.ts"]})
        with open(os.path.join(mod, "hooks", "register.ts")) as f:
            src = f.read()
        self.assertIn("immediate: true", src)
        self.assertIn('"$HOME/.claude/hooks/autopass_toggle.py"', src)
        self.assertTrue(os.path.exists(os.path.join(REPO, "hooks", "autopass_toggle.py")))

    def test_the_lane_hooks_are_wired_and_fail_open(self):
        # docs/lanes.md: the guard on every file-tool write; identity on every context reset (a
        # compact is the net for an unplanned auto-compact), and the mirror on Stop and
        # SessionEnd. Both deny or speak by JSON, never by exit code.
        guard = 'bash "$HOME/.claude/hooks/lane-guard.sh"'
        ident = 'bash "$HOME/.claude/hooks/lane-identity.sh"'
        self.assertEqual(commands("PreToolUse", "Edit|Write|MultiEdit"), [guard])
        self.assertEqual(commands("SessionStart", "startup|resume|clear|compact").count(ident), 1)
        for event in ("Stop", "SessionEnd"):
            self.assertEqual(commands(event).count(ident), 1, event)
        lane_hooks = [h for entries in S["hooks"].values() for e in entries for h in e["hooks"]
                      if "lane-" in h["command"]]
        self.assertEqual(len(lane_hooks), 4)
        for h in lane_hooks:
            self.assertNotIn("exit 2", h["command"])
            self.assertLessEqual(h["timeout"], 5)
        for script in ("lane-guard.sh", "lane-identity.sh"):
            self.assertTrue(os.access(os.path.join(REPO, "hooks", script), os.X_OK), script)
        # `lane new`, `ls` and `done` need the network and gh's credential (spike S3); `ls`,
        # `open`, `done` and `addr` need to see other processes. Only those run sandbox-off: `lane lock
        # -- <cmd>` must stay sandboxed, or the command it wraps would run outside the sandbox
        # without the dangerouslyDisableSandbox flag the delete guard checks. `new` and `adopt`
        # run the config's `setup` through a shell, so the config lives in the state dir, which
        # sandboxed Bash can't write (docs/lanes.md S3; tests/lanes ConfigTrust).
        excluded = S["sandbox"]["excludedCommands"]
        bare = ["lane init", "lane init *", "lane new *", "lane adopt *", "lane ls", "lane ls *",
                "lane open *", "lane done *", "lane addr *"]
        self.assertEqual([p for p in excluded if p.split()[0] == "lane"], bare)
        self.assertNotIn("lane *", excluded)
        for cmd in ("lane lock gate -- true", "lane lock gate -- rm -rf build", "lane whoami",
                    "lane claim 42", "lane note x"):
            self.assertEqual([p for p in excluded if glob_match(p, cmd)], [], cmd)
        for cmd in ("lane ls", "lane ls --json", "lane open chart-fix", "lane done chart-fix",
                    "lane addr lead"):
            self.assertTrue(any(glob_match(p, cmd) for p in excluded), cmd)

    def test_pass_respawn_runs_outside_the_sandbox(self):
        # It needs the tmux socket and the session's processes (/pass, spike S6). It is
        # sandbox-off code, so it checks every sandbox-writable input it reads (its docstring);
        # the delegated-agent policy denies it like every excluded command.
        excluded = S["sandbox"]["excludedCommands"]
        self.assertEqual([p for p in excluded if p.split()[0] == "pass-respawn"],
                         ["pass-respawn", "pass-respawn *"])
        self.assertLess(excluded.index("lane addr *"), excluded.index("pass-respawn"))
        for cmd in ("pass-respawn", "pass-respawn --compact", "pass-respawn --print -C /x"):
            self.assertTrue(any(glob_match(p, cmd) for p in excluded), cmd)
        # The allow rule skips the auto-mode classifier, which once refused a bare call as
        # "Create Unsafe Agents" (live run, 2026-10-12); the skill keeps -C first to match it.
        self.assertIn("Bash(pass-respawn -C *)", S["permissions"]["allow"])
        with open(os.path.join(REPO, "skills", "pass", "SKILL.md")) as f:
            skill = f.read()
        self.assertIn("`pass-respawn -C <toplevel> --compact`", skill)
        self.assertIn("Bash(pass-respawn -C *)", skill)
        script = os.path.join(REPO, "skills", "pass", "scripts", "pass-respawn")
        self.assertTrue(os.access(script, os.X_OK))
        with open(os.path.join(REPO, "setup.sh")) as f:
            self.assertIn('"$REPO_DIR"/skills/pass/scripts/pass-respawn', f.read())

    def test_the_delete_guard_runs_on_sandbox_off_bash_only_and_fails_open(self):
        # Every Bash call passes the matcher; the prefilter keeps Python off the sandboxed ones,
        # which can only reach the cwd and $TMPDIR. The guard denies by JSON, never by exit code.
        (cmd,) = commands("PreToolUse", "Bash")
        self.assertIn("""*'"dangerouslyDisableSandbox":true'*""", cmd)
        self.assertIn("""*'"dangerouslyDisableSandbox": true'*""", cmd)
        self.assertIn('bash "$HOME/.claude/hooks/delete-guard.sh"', cmd)
        self.assertNotIn("exit 2", cmd)
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "delete-guard.sh"), os.X_OK))

    def test_memory_is_committed_at_session_start_and_stop(self):
        # Every SessionStart source (a /clear too) and every Stop: Bash edits to memory are
        # caught within a turn. Never blocks.
        for event in ("SessionStart", "Stop"):
            with self.subTest(event=event):
                (entry,) = [e for e in S["hooks"][event]
                            if any("memory-git.sh" in h["command"] for h in e["hooks"])]
                self.assertNotIn("matcher", entry)
                (h,) = entry["hooks"]
                self.assertEqual(h["command"], 'bash "$HOME/.claude/hooks/memory-git.sh"')
                self.assertLessEqual(h["timeout"], 5)
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "memory-git.sh"), os.X_OK))

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
        # Also accepted (Hayden, 2026-10-07): deleting a non-main branch with `origin :feat`,
        # since no rule can catch ` :` without a :* (see the lint test below).
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
                 "git push origin feat --mirror", "git push origin :main",
                 "git -C . push", "git -C . push origin feat",
                 # A force the deny rules miss still asks.
                 "git push origin +feat", "git push -uf origin feat",
                 "gh pr merge 5 --squash", "gh api -X PUT repos/o/r/pulls/5/merge",
                 # --output writes a file, which the read-only git allows below must not cover.
                 "git log --output=README.md", "git diff --output=x"]
        # Pushes to a named branch and the PR lifecycle short of a merge run (Hayden still
        # approves each in words; 2026-10-09 he extended his "perms for PR requests" to ready,
        # edit, comment, close and reopen, after the classifier refused the handoff skill's own
        # `gh pr ready` as an unrequested commit).
        # A body read from a file asks (the inventory's gh file rules; Hayden, 2026-10-13).
        # Read-only git and pipe filters skip the classifier, which once refused a
        # `git status -sb | head -1` as an unrequested commit. Each part of a pipe needs its
        # own rule (live probe, 2.1.293), hence head, tail, wc and grep.
        allowed = ["git push origin feat/x", "git push origin feat-force-fix",
                   "git push origin fix/x --follow-tags", "gh pr create --base main --head feat/x",
                   "gh pr ready 5", "gh pr ready 5 --repo o/r", "gh pr edit 5 --body x",
                   "gh pr comment 5 --body x", "gh pr close 5", "gh pr reopen 5",
                   "git push origin :feat",
                   "git status", "git status -sb", "git log", "git log --oneline -5",
                   "git diff", "git diff HEAD", "git show", "git show HEAD:README.md",
                   "git rev-parse HEAD", "head", "head -1", "tail -n 5", "wc -l", "grep -n x a"]
        # No -C forms and no verb prefix: * spans spaces, so `git -C * log*` or `git diff*`
        # would let a commit, a branch delete or difftool through.
        not_allowed = ["git difftool", 'git -C . commit -m "log"', 'git commit -m "git status"',
                       "git branch -D feat", "git -C . status", "git statusx"]
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
        for c in not_allowed:
            self.assertFalse(matching("allow", c), c)
        for c in asked:  # ask beats allow, so an allow rule may cover these too
            self.assertTrue(matching("ask", c), c)
        # Every rule is the only one of its kind that catches some case, so dropping one fails.
        # The inventory's rules bring their own cases.
        for kind, cases in (("deny", denied + [s for r in inv.DENIES for s in r.samples]),
                            ("ask", asked + [s for r in inv.ASKS for s in r.samples])):
            for rule in S["permissions"][kind]:
                self.assertIn([rule], [matching(kind, c) for c in cases], rule)

    def test_every_gh_step_the_workflow_names_has_a_rule(self):
        # Hayden's rule (2026-10-05): only merges and pushes to main need his click. The rules
        # covered `gh pr create` alone, so the handoff skill's own `gh pr ready <n>` fell to the
        # classifier, which passed it in one session and refused it in another (2026-10-09).
        # Every `gh pr` or `gh run` verb that CLAUDE.md, a skill or an agent tells Claude to run
        # needs an allow or ask rule, so a new workflow step fails here instead of in a session.
        docs = ([os.path.join(REPO, "CLAUDE.md")]
                + glob.glob(os.path.join(REPO, "skills", "**", "*.md"), recursive=True)
                + glob.glob(os.path.join(REPO, "agents", "*.md")))
        verbs = set()
        for path in docs:
            with open(path) as f:
                verbs |= set(re.findall(r"\bgh (?:pr|run) [a-z]+", f.read()))
        self.assertIn("gh pr ready", verbs)  # the scan still reaches the handoff skill
        for verb in sorted(verbs):
            with self.subTest(verb=verb):
                command = verb + " 5"
                self.assertTrue(matching("allow", command) or matching("ask", command), verb)

    def test_no_rule_uses_the_colon_star_forms(self):
        # The glob model above is only true without a :*. Live probe, 2.1.293: a trailing :* is
        # the legacy prefix form (its other * stays literal, so `git push * :*` never matched),
        # and any other :* prints a warning at every start. `\:*` and `[:]*` don't escape it.
        for kind in ("allow", "ask", "deny"):
            for rule in S["permissions"][kind]:
                self.assertNotIn(":*", rule, f"{kind}: {rule}")

    def test_the_stop_sound_rings_for_the_main_session_only(self):
        # Stop fires for subagents too; an inline sound rang for every one of them.
        stops = commands("Stop")
        self.assertIn('bash "$HOME/.claude/hooks/stop-ring.sh"', stops)
        self.assertFalse(any("powershell.exe" in c for c in stops), stops)
        self.assertTrue(os.access(os.path.join(REPO, "hooks", "stop-ring.sh"), os.X_OK))


def excluded_by(command):
    return [p for p in S["sandbox"]["excludedCommands"] if glob_match(p, command)]


def help_text(*argv):
    p = subprocess.run(["claude", *argv, "--help"], capture_output=True, text=True, timeout=30)
    return p.stdout


class Inventory(unittest.TestCase):
    """command_inventory.py is the single source for what runs outside the sandbox and what asks;
    settings.json must say the same, in both directions."""

    def test_excluded_commands_are_the_inventory_in_order(self):
        self.assertEqual(S["sandbox"]["excludedCommands"], [e.pattern for e in inv.EXCLUDED])

    def test_each_sample_matches_its_entry_and_the_rest_stay_sandboxed(self):
        for e in inv.EXCLUDED:
            for s in e.samples:
                self.assertTrue(glob_match(e.pattern, s), (e.pattern, s))
        for s in inv.NO_ASK:
            self.assertTrue(excluded_by(s), s)
        for s in inv.SANDBOXED:
            self.assertEqual(excluded_by(s), [], s)

    def test_the_inventory_rules_are_in_settings(self):
        self.assertLessEqual({r.rule for r in inv.ASKS}, set(S["permissions"]["ask"]))
        self.assertLessEqual({r.rule for r in inv.DENIES}, set(S["permissions"]["deny"]))
        # Every other ask is the git and gh baseline that
        # test_destructive_git_is_denied_and_anything_that_can_reach_main_asks covers.
        for rule in set(S["permissions"]["ask"]) - {r.rule for r in inv.ASKS}:
            self.assertRegex(rule, r"^Bash\((git|gh) ", rule)

    def test_raw_samples_ask_and_the_hot_path_does_not(self):
        for r in inv.ASKS:
            for s in r.samples:
                self.assertIn(r.rule, matching("ask", s), s)
        for r in inv.DENIES:
            for s in r.samples:
                self.assertIn(r.rule, matching("deny", s), s)
        for s in inv.NO_ASK:
            self.assertEqual(matching("ask", s) + matching("deny", s), [], s)

    def test_every_tmux_spelling_asks_unless_read_only(self):
        # tmux takes an alias or any unambiguous prefix of a name, so each spelling of each of
        # the snapshot's commands is checked, bare and with an argument.
        table = inv.tmux_table()
        self.assertEqual(len(table), 91)
        self.assertLessEqual(inv.TMUX_READ_ONLY, {n for n, _ in table})
        for name, _ in table:
            for verb in sorted(inv.tmux_spellings(name, table)):
                self.assertEqual(inv.tmux_resolve(verb, table), name, verb)
                for cmd in (f"tmux {verb}", f"tmux {verb} -t x"):
                    asks = matching("ask", cmd)
                    if name in inv.TMUX_READ_ONLY:
                        self.assertEqual(asks, [], cmd)
                    else:
                        self.assertTrue(asks, cmd)
        # Each excluded tmux entry is a read-only verb.
        for p in S["sandbox"]["excludedCommands"]:
            if p.startswith("tmux "):
                self.assertIn(inv.tmux_resolve(p.split()[1], table), inv.TMUX_READ_ONLY, p)

    def test_each_excluded_tmux_verb_names_the_command_tmux_runs(self):
        # Written out by hand from tmux's cmd_find (exact alias, else a unique prefix), so a
        # slip in tmux_spellings can't hide behind tmux_resolve, which derives from it.
        expect = {"ls": "list-sessions", "list-sessions": "list-sessions",
                  "list-windows": "list-windows", "list-panes": "list-panes",
                  "list-clients": "list-clients", "list-keys": "list-keys",
                  "list-commands": "list-commands", "capture-pane": "capture-pane",
                  "display": "display-message", "show": "show-options",
                  "show-options": "show-options", "show-environment": "show-environment",
                  "show-messages": "show-messages", "show-hooks": "show-hooks"}
        verbs = {p.split()[1] for p in S["sandbox"]["excludedCommands"] if p.startswith("tmux ")}
        self.assertEqual(verbs, set(expect))
        for verb, name in expect.items():
            self.assertEqual(inv.tmux_resolve(verb), name, verb)
            self.assertIn(name, inv.TMUX_READ_ONLY, verb)
        # A default command-alias runs its target: the mutating ones ask, and none is excluded.
        for alias, name in inv.TMUX_DEFAULT_ALIASES.items():
            self.assertEqual(excluded_by(f"tmux {alias} -t x"), [], alias)
            if name not in inv.TMUX_READ_ONLY:
                self.assertTrue(matching("ask", f"tmux {alias} -t x"), alias)

    def test_wrapper_flags_an_ask_names_take_no_abbreviation(self):
        # argparse takes a unique prefix by default (`--aban` for --abandon), which an ask that
        # names the full flag would miss, so the excluded wrappers turn that off.
        lane = load_script("lane", os.path.join(REPO, "skills", "lanes", "scripts"))
        for argv in (["init", "--set", "x"], ["init", "--ro", "/x"], ["done", "x", "--aban"]):
            with self.assertRaises(SystemExit, msg=argv), contextlib.redirect_stderr(io.StringIO()):
                lane.parser().parse_args(argv)
        self.assertTrue(lane.parser().parse_args(["done", "x", "--abandon"]).abandon)
        cd = load_script("codex-delegate")
        cd.cmd_run = lambda a: a.network
        run = ["run", "--model", "m", "--dir", "/x", "--brief", "b.md"]
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cd.main(run + ["--net"])
        self.assertTrue(cd.main(run + ["--network"]))

    def test_installed_tmux_matches_the_snapshot(self):
        # `tmux -V` needs no server, so a tmux upgrade fails every suite run until the snapshot
        # and the read-only list are redone. The table itself needs a server, which the sandbox
        # blocks, so that half runs where a socket is reachable (the sandbox-off canary).
        if not shutil.which("tmux"):
            self.skipTest("no tmux on PATH")
        v = subprocess.run(["tmux", "-V"], capture_output=True, text=True, timeout=10)
        self.assertEqual(v.stdout.strip(), inv.TMUX_VERSION,
                         "re-snapshot `tmux list-commands` into " + inv.TMUX_SNAPSHOT)
        sock = f"dotclaude-inventory-{os.getpid()}"
        p = subprocess.run(["tmux", "-L", sock, "-f", "/dev/null", "start-server", ";",
                            "list-commands", ";", "kill-server"],
                           capture_output=True, text=True, timeout=10)
        if p.returncode != 0:
            self.skipTest("tmux reaches no server here: " + p.stderr.strip()[:80])
        with open(inv.TMUX_SNAPSHOT) as f:
            self.assertEqual(p.stdout, f.read())

    def test_git_program_flag_asks_cover_every_prefix_git_takes(self):
        # git takes any unique prefix of a long option, so each ask names the shortest one the
        # installed git accepts, and no other option of that verb trips it.
        if not shutil.which("git"):
            self.skipTest("no git on PATH")
        for verb, flags in inv.GIT_PROGRAM_FLAGS.items():
            p = subprocess.run(["git", verb, "--git-completion-helper-all"],
                               capture_output=True, text=True, timeout=10)
            opts = {o.rstrip("=") for o in p.stdout.split() if o.startswith("--")}
            self.assertLessEqual(set(flags), opts, verb)
            for flag, prefix in flags.items():
                short = next(flag[:i] for i in range(3, len(flag) + 1)
                             if [o for o in opts if o.startswith(flag[:i])] == [flag])
                self.assertEqual(prefix, short, f"git {verb} {flag}")
                for i in range(len(short), len(flag) + 1):
                    self.assertTrue(matching("ask", f"git {verb} origin {flag[:i]}=x"), flag[:i])
            mine = {r.rule for r in inv.ASKS}  # the baseline's push asks are another test's
            for o in sorted(opts - set(flags) - {"--"}):
                self.assertEqual(set(matching("ask", f"git {verb} origin {o}")) & mine, set(),
                                 f"git {verb} {o}")

    def test_installed_claude_flags_and_subcommands_are_classified(self):
        # A new Claude Code flag or subcommand fails every suite until the inventory classifies
        # it (Hayden accepted the cost, 2026-10-13): an unclassified loosening flag is what the
        # inventory exists to catch. The flags are the top level's and every "ok" leaf's, short
        # aliases included; a leaf that asks as a whole needs no flag list.
        if not shutil.which("claude"):
            self.skipTest("no claude on PATH")
        known = set(inv.CLAUDE_FLAG_ASKS) | inv.CLAUDE_FLAG_OK | set(inv.CLAUDE_LEAF_FLAG_ASKS)
        leaves = [()] + [path + (sub.split("|")[0],) for path, subs in inv.CLAUDE_COMMANDS.items()
                         for sub, cls in subs.items() if cls == "ok" and sub != "help"]
        for argv in leaves:
            text = help_text(*argv)
            self.assertIn("Usage: claude", text, argv)
            for short, *longs in re.findall(r"^  (?:(-\w), )?(--[\w-]+)(?:, (--[\w-]+))?",
                                            text, re.M):
                for flag in filter(None, longs):
                    self.assertIn(flag, known, f"classify claude {' '.join(argv)} {flag}")
                if short:
                    self.assertEqual(inv.CLAUDE_SHORT_FLAGS.get(short), longs[0],
                                     f"classify claude {' '.join(argv)} {short}")
        for path, subs in inv.CLAUDE_COMMANDS.items():
            text = help_text(*path)
            listed = re.findall(r"^  ([a-z][\w|-]*)", text.split("\nCommands:\n", 1)[-1], re.M)
            self.assertTrue(listed, path)
            for sub in listed:
                self.assertIn(sub, subs, f"classify claude {' '.join(path)} {sub}")

    def test_claude_classes_match_the_rules(self):
        for flag, glob_ in inv.CLAUDE_FLAG_ASKS.items():
            if glob_:
                self.assertTrue(matching("ask", f"claude -p {flag} x"), flag)
        for flag in inv.CLAUDE_FLAG_OK | inv.CLAUDE_HIDDEN_OK:
            self.assertEqual(matching("ask", f"claude -p {flag} x"), [], flag)
        for short, long_ in inv.CLAUDE_SHORT_FLAGS.items():
            self.assertIn(long_, inv.CLAUDE_FLAG_OK, short)  # an ask-class short needs a rule
            self.assertEqual(matching("ask", f"claude {short} x"), [], short)
        for flag, rule in inv.CLAUDE_LEAF_FLAG_ASKS.items():
            self.assertIn(rule, {r.rule for r in inv.ASKS}, flag)
        for path, subs in inv.CLAUDE_COMMANDS.items():
            for heads in ([path], [("plugins",)] if path == ("plugin",) else []):
                for head in heads:
                    for sub, cls in subs.items():
                        for name in sub.split("|"):
                            cmd = " ".join(["claude", *head, name, "x"])
                            if cls == "ask":
                                self.assertTrue(matching("ask", cmd), cmd)
                            elif cls == "deny":
                                self.assertTrue(matching("deny", cmd), cmd)
                            elif cls == "ok":
                                self.assertEqual(matching("ask", cmd) + matching("deny", cmd),
                                                 [], cmd)

    def test_every_model_run_command_in_skills_asks_nothing(self):
        # What CLAUDE.md, a skill or an agent tells Claude to run stays prompt-free (rule D),
        # and a call with arguments to an excluded wrapper or verb really runs outside.
        docs = ([os.path.join(REPO, "CLAUDE.md")]
                + glob.glob(os.path.join(REPO, "skills", "**", "*.md"), recursive=True)
                + glob.glob(os.path.join(REPO, "agents", "*.md")))
        tools = r"tmux|claude|codex|lane|pass-respawn|delegation-ledger|codex-delegate|gh"
        found = set()
        for path in docs:
            with open(path) as f:
                text = f.read()
            spans = re.findall(rf"`((?:{tools}) [^`]+)`", text)
            for block in re.findall(r"^```[^\n]*\n(.*?)^```", text, re.M | re.S):
                spans += re.findall(rf"^\s*((?:{tools}) .*?)(?:\s+#.*)?$", block, re.M)
            for span in spans:
                # <placeholder> becomes a word; an [--optional] group drops (it may ask).
                span = re.sub(r"\[[^]]*\]", "", re.sub(r"<[^>]*>", "x", span))
                found.add(" ".join(span.split()))
        self.assertIn("tmux capture-pane -p -t x", found)  # the scan still reaches the lanes skill
        self.assertIn("codex-delegate status", found)  # and the fenced blocks
        excluded = S["sandbox"]["excludedCommands"]
        for cmd in sorted(found):
            with self.subTest(cmd=cmd):
                if any(cmd.startswith(k) for k in inv.SKILL_ASKS):
                    self.assertTrue(matching("ask", cmd))
                    continue
                self.assertEqual(matching("ask", cmd) + matching("deny", cmd), [])
                words = cmd.split()
                family = [p for p in excluded if p.split()[:2] == words[:2]
                          or p.split()[0] == words[0] and p.split()[1:] == ["*"]]
                if family and len(words) > 2 or words[0] == "gh":  # gh is an allowlist
                    self.assertTrue(excluded_by(cmd))


if __name__ == "__main__":
    unittest.main()
