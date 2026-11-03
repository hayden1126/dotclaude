"""`lane sync-main [<PR>]`, the verified post-merge merge (DA15/DA16).

Lead mode (`lane sync-main <n>` from the main checkout) merges the commit gh names as PR n's
merge into the lead's branch; lane mode (no PR, inside a lane) merges the base branch's tip,
fetched fresh. Either way the merge is built in a fresh store under the state dir and the
checkout is written only from it, so the bytes come from git's hash checks, never from what
the shared common dir (which any lane's sandboxed Bash can write) says.

Each attack test first runs the plain chain this replaces (`git fetch origin main:main`, then
`git merge --no-ff main`) in a throwaway copy of the main checkout, as a control showing the
planted content lands there.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
import zlib
from unittest import mock

from _fixture import LANE, LanesRepo
from test_cli import load_lane_script

REAL = "#!/bin/sh\necho real\n"
EVIL = "#!/bin/sh\necho planted\n"
RULES = {"permissions": {"deny": ["Edit(~/.local/state/dotclaude/verified/**)"]},
         "sandbox": {"filesystem": {"denyWrite": ["~/.local/state/dotclaude/verified"]}}}


class SyncMain(LanesRepo):
    """The main checkout sits on the lead's branch `lead`, whose own commit adds STATUS.md."""

    state_in_home = True

    def setUp(self):
        super().setUp()
        self.settings(RULES)
        self.git("checkout", "-q", "-b", "lead")
        self.commit("STATUS.md", "# Status\n- lead line\n")
        self.gh_clone = os.path.join(self.tmp, "gh")
        self.git("clone", "-q", self.origin, self.gh_clone, cwd=self.tmp)
        self.verified = os.path.join(self.home, ".local", "state", "dotclaude", "verified")

    # --- helpers ---------------------------------------------------------------------------

    def settings(self, data):
        self.write(os.path.join(self.home, ".claude", "settings.json"), json.dumps(data))

    def gh_says(self, data):
        self.env["FAKE_GH_OUT"] = data if isinstance(data, str) else json.dumps(data)

    def merged(self, sha, base="main"):
        self.gh_says({"state": "MERGED", "mergeCommit": {"oid": sha}, "baseRefName": base})

    def land(self, files, n=7):
        """PR n: a commit with files made in the shared repo (a worktree on branch pr<n>, as a
        lane's commits are), merged --no-ff on origin's main. gh names its merge commit."""
        self.git("fetch", "-q", "origin")
        wt = os.path.join(self.tmp, f"wt{n}")
        self.git("worktree", "add", "-q", "-b", f"pr{n}", wt, "origin/main")
        for name, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(wt, name)), exist_ok=True)
            self.write(os.path.join(wt, name), text)
            self.git("add", name, cwd=wt)
        self.git("commit", "-q", "-m", f"pr {n}", cwd=wt)
        self.git("push", "-q", "origin", f"pr{n}", cwd=wt)
        self.git("fetch", "-q", "origin", cwd=self.gh_clone)
        self.git("reset", "-q", "--hard", "origin/main", cwd=self.gh_clone)
        self.git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{n}", f"origin/pr{n}",
                 cwd=self.gh_clone)
        self.git("push", "-q", "origin", "main", cwd=self.gh_clone)
        sha = self.git("rev-parse", "HEAD", cwd=self.gh_clone).strip()
        self.merged(sha)
        return sha

    def blob(self, ref, path):
        """path's blob in ref, a branch of the shared repo (a PR's, as a lane made it)."""
        return self.git("rev-parse", f"{ref}:{path}").strip()

    def sync(self, *args, cwd=None, env=None):
        e = dict(self.env, **(env or {}))
        return subprocess.run([sys.executable, LANE, "sync-main", *args], cwd=cwd or self.main,
                              env=e, capture_output=True, text=True, timeout=120)

    def sync_in(self, *args, cwd=None, patches=lambda mod: []):
        """sync-main in this process, so a test can patch the loaded CLI. (rc, out, err)."""
        mod = load_lane_script()
        out, err = io.StringIO(), io.StringIO()
        here = os.getcwd()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, self.env, clear=True))
            for p in patches(mod):
                stack.enter_context(p)
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            os.chdir(cwd or self.main)
            try:
                rc = mod.main(["sync-main", *args])
            finally:
                os.chdir(here)
        return rc, out.getvalue(), err.getvalue()

    def state(self, cwd=None):
        """Every ref and the checkout's files: what a refusal must leave as it was."""
        cwd = cwd or self.main
        refs = self.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=cwd)
        head = self.git("symbolic-ref", "HEAD", cwd=cwd)
        files = {}
        for d, dirs, names in os.walk(cwd):
            dirs[:] = [x for x in dirs if x not in (".git", ".lane")]
            for name in names:
                p = os.path.join(d, name)
                if name != ".git":
                    with open(p, "rb") as f:
                        files[os.path.relpath(p, cwd)] = f.read()
        return refs, head, files

    def control(self, path="hooks/x.sh"):
        """The plain chain in a throwaway copy of the main checkout: what lands at path."""
        copy = os.path.join(self.tmp, "control")
        shutil.copytree(self.main, copy, symlinks=True)
        subprocess.run(["git", "fetch", "-q", "origin", "main:main"], cwd=copy, env=self.env,
                       capture_output=True)
        subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "chain", "main"], cwd=copy,
                       env=self.env, capture_output=True)
        return self.read(os.path.join(copy, path))

    def evil_blob(self):
        p = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.main, env=self.env,
                           input=EVIL, capture_output=True, text=True, check=True)
        return p.stdout.strip()

    def parents(self, ref="HEAD", cwd=None):
        return self.git("rev-list", "--parents", "-n1", ref, cwd=cwd).split()[1:]

    # --- lead mode ---------------------------------------------------------------------------

    def test_merges_the_proven_commit(self):
        proven = self.land({"hooks/x.sh": REAL, "STATUS.md": "# Status\n- main carry line\n"})
        pinned = self.git("rev-parse", "HEAD").strip()
        p = self.sync("7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.parents(), [pinned, proven])
        self.assertEqual(self.read(os.path.join(self.main, "hooks", "x.sh")), REAL)
        # STATUS.md is the lead's whole file; main's side is printed for a hand merge.
        self.assertEqual(self.read(os.path.join(self.main, "STATUS.md")),
                         "# Status\n- lead line\n")
        self.assertEqual(self.git("show", "HEAD:STATUS.md"), "# Status\n- lead line\n")
        self.assertIn("+- main carry line", p.stdout)
        self.assertIn("follow-up commit", p.stdout)
        self.assertIn(proven[:12], p.stdout)
        self.assertEqual(self.git("status", "--porcelain", "-uno"), "")
        self.assertEqual(self.git("rev-parse", "refs/heads/main").strip(), proven)
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main").strip(), proven)
        self.assertTrue(os.path.isdir(os.path.join(self.verified, "main.git")))

    def test_already_up_to_date_is_a_clean_no_op(self):
        proven = self.land({"hooks/x.sh": REAL})
        self.assertEqual(self.sync("7").returncode, 0)
        before = self.state()
        self.merged(proven)
        p = self.sync("7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("up to date", p.stdout)
        self.assertEqual(self.state(), before)

    def test_up_to_date_still_checks_the_checkout_and_the_drift(self):
        # The pinned sha comes from a lane-writable branch ref. A lane points the lead's branch
        # at proven plus a change of its own and forges the index so status reads clean
        # (dirty_paths mocked): "up to date" must not vouch for that checkout.
        proven = self.land({"hooks/x.sh": REAL})
        self.git("fetch", "-q", "origin")
        wt = os.path.join(self.tmp, "evil")
        self.git("worktree", "add", "-q", "--detach", wt, "HEAD")
        self.git("merge", "-q", "--no-ff", "-m", "m", proven, cwd=wt)
        self.commit("README.md", "planted\n", cwd=wt)
        moved = self.git("rev-parse", "HEAD", cwd=wt).strip()
        self.git("update-ref", "refs/heads/lead", moved)
        self.merged(proven)
        rc, out, err = self.sync_in("7", patches=lambda mod: [
            mock.patch.object(mod, "dirty_paths", return_value=[])])
        self.assertEqual(rc, 1, out + err)
        self.assertNotIn("up to date", out)
        self.assertIn("README.md", err)
        # The checkout matches the branch, but it holds a path apart from the PR's merge.
        self.git("reset", "-q", "--hard", moved)
        p = self.sync("7")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("other than STATUS.md", p.stderr)
        self.assertIn("README.md", p.stderr)

    def test_plan_md_merges_clean_or_keeps_the_leads(self):
        self.commit("PLAN.md", "a\nb\nc\nd\ne\n")
        self.git("push", "-q", "origin", "lead:refs/heads/plan-base")
        # main changes a line far from the lead's later change: a clean merge keeps both.
        self.git("fetch", "-q", "origin", cwd=self.gh_clone)
        self.git("reset", "-q", "--hard", "origin/main", cwd=self.gh_clone)
        self.git("merge", "-q", "--no-ff", "-m", "plan", "origin/plan-base", cwd=self.gh_clone)
        self.write(os.path.join(self.gh_clone, "PLAN.md"), "A\nb\nc\nd\ne\n")
        self.git("commit", "-qam", "main plan", cwd=self.gh_clone)
        self.git("push", "-q", "origin", "main", cwd=self.gh_clone)
        proven = self.git("rev-parse", "HEAD", cwd=self.gh_clone).strip()
        self.commit("PLAN.md", "a\nb\nc\nd\nE\n")
        self.merged(proven)
        p = self.sync("7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.read(os.path.join(self.main, "PLAN.md")), "A\nb\nc\nd\nE\n")
        # Now a conflict on PLAN.md: the lead's file wins.
        self.write(os.path.join(self.gh_clone, "PLAN.md"), "main\n")
        self.git("commit", "-qam", "main plan 2", cwd=self.gh_clone)
        self.git("push", "-q", "origin", "main", cwd=self.gh_clone)
        self.commit("PLAN.md", "lead\n")
        self.merged(self.git("rev-parse", "HEAD", cwd=self.gh_clone).strip())
        p = self.sync("7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.read(os.path.join(self.main, "PLAN.md")), "lead\n")

    def test_lead_drift_on_another_path_refuses_before_writing(self):
        self.land({"hooks/x.sh": REAL})
        self.commit("hooks.txt", "lead only\n")
        before = self.state()
        p = self.sync("7")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("hooks.txt", p.stderr)
        self.assertEqual(self.state(), before)

    def test_a_conflict_outside_the_carries_refuses(self):
        self.commit("README.md", "lead readme\n")
        self.land({"README.md": "main readme\n"})
        before = self.state()
        p = self.sync("7")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("README.md", p.stderr)
        self.assertEqual(self.state(), before)

    def test_a_dirty_checkout_refuses(self):
        self.land({"hooks/x.sh": REAL})
        self.write(os.path.join(self.main, "README.md"), "edited\n")
        before = self.state()
        p = self.sync("7")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("README.md", p.stderr)
        self.assertEqual(self.state(), before)

    def test_an_untracked_extra_in_a_tracked_dir_refuses(self):
        self.commit("tools.txt", "x\n")
        os.makedirs(os.path.join(self.main, "hooks"))
        self.write(os.path.join(self.main, "hooks", "k"), "tracked\n")
        self.git("add", "hooks/k")
        self.git("commit", "-qm", "k")
        self.git("push", "-q", "origin", "lead:refs/heads/k")
        self.git("fetch", "-q", "origin", cwd=self.gh_clone)
        self.git("reset", "-q", "--hard", "origin/k", cwd=self.gh_clone)
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.gh_clone)
        self.git("merge", "-q", "--ff-only", "origin/k")
        proven = self.land({"hooks/x.sh": REAL})
        self.write(os.path.join(self.main, "hooks", "planted.sh"), EVIL)
        os.makedirs(os.path.join(self.main, "hooks", "__pycache__"))
        p = self.sync("7")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("hooks/planted.sh", p.stderr)
        self.assertNotIn("__pycache__", p.stderr)
        os.unlink(os.path.join(self.main, "hooks", "planted.sh"))
        self.merged(proven)
        p = self.sync("7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    # --- attacks -----------------------------------------------------------------------------

    def test_a_replace_ref_is_refused_by_the_tripwire(self):
        proven = self.land({"hooks/x.sh": REAL})
        self.git("replace", self.blob("pr7", "hooks/x.sh"), self.evil_blob())
        before = self.state()
        p = self.sync("7")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("refs/replace", p.stderr)
        self.assertEqual(self.state(), before)

    def test_attribute_files_outside_the_tree_never_convert_the_checkout(self):
        # A conversion from <common>/info/attributes (lane-writable) or the global attributes
        # file (read even with GIT_CONFIG_GLOBAL=/dev/null) would write other bytes than the
        # store's blob. The tripwire flags the first; with it off, neither reaches a file.
        config = os.path.join(self.home, ".config")
        self.env["XDG_CONFIG_HOME"] = config
        rule = "*.sh text eol=crlf\n"
        for n, where in enumerate((os.path.join(self.common, "info", "attributes"),
                                   os.path.join(config, "git", "attributes")), 7):
            with self.subTest(where=where):
                os.makedirs(os.path.dirname(where), exist_ok=True)
                self.write(where, rule)
                try:
                    proven = self.land({"hooks/x.sh": f"{REAL}# {n}\n"}, n=n)
                    blob = self.blob(f"pr{n}", "hooks/x.sh")
                    rc, out, err = self.sync_in(str(n), patches=lambda mod: [
                        mock.patch.object(mod.lanelib, "git_tamper", return_value=[])])
                    self.assertEqual(rc, 0, out + err)
                    with open(os.path.join(self.main, "hooks", "x.sh"), "rb") as f:
                        self.assertEqual(f.read(), self.git("cat-file", "blob", blob).encode())
                    self.assertEqual(self.parents()[1], proven)
                finally:
                    os.unlink(where)

    def test_a_replace_ref_never_reaches_the_checkout(self):
        proven = self.land({"hooks/x.sh": REAL})
        self.git("replace", self.blob("pr7", "hooks/x.sh"), self.evil_blob())
        self.assertEqual(self.control(), EVIL)  # the plain chain checks the planted blob out
        rc, out, err = self.sync_in("7", patches=lambda mod: [
            mock.patch.object(mod.lanelib, "git_tamper", return_value=[])])
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.read(os.path.join(self.main, "hooks", "x.sh")), REAL)
        self.assertEqual(self.parents()[1], proven)

    def test_an_overwritten_object_is_never_checked_out_and_fsck_refuses(self):
        proven = self.land({"hooks/x.sh": REAL})
        blob = self.blob("pr7", "hooks/x.sh")
        path = os.path.join(self.common, "objects", blob[:2], blob[2:])
        os.chmod(path, 0o644)
        with open(path, "wb") as f:
            f.write(zlib.compress(b"blob %d\0" % len(EVIL) + EVIL.encode()))
        self.assertEqual(self.control(), EVIL)  # git reads the file it finds by name
        p = self.sync("7")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(blob, p.stderr)
        self.assertIn("fsck", p.stderr)
        self.assertEqual(self.read(os.path.join(self.main, "hooks", "x.sh")), REAL)

    def test_a_moved_main_ref_is_ignored(self):
        proven = self.land({"hooks/x.sh": REAL})
        # A lane points refs/heads/main at a commit of its own (no PR merged it).
        self.git("fetch", "-q", "origin")
        wt = os.path.join(self.tmp, "evil")
        self.git("worktree", "add", "-q", "--detach", wt, "origin/main^1")
        os.makedirs(os.path.join(wt, "hooks"))
        self.write(os.path.join(wt, "hooks", "x.sh"), EVIL)
        self.git("add", "hooks/x.sh", cwd=wt)
        self.git("commit", "-qm", "evil", cwd=wt)
        self.git("update-ref", "refs/heads/main", self.git("rev-parse", "HEAD", cwd=wt).strip())
        self.assertEqual(self.control(), EVIL)
        p = self.sync("7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.read(os.path.join(self.main, "hooks", "x.sh")), REAL)
        self.assertEqual(self.parents()[1], proven)
        self.assertEqual(self.git("rev-parse", "refs/heads/main").strip(), proven)

    def test_a_branch_moved_before_the_update_refuses(self):
        self.land({"hooks/x.sh": REAL})
        moved = self.git("commit-tree", "-m", "moved", "HEAD^{tree}", "-p", "HEAD").strip()

        def patches(mod):
            real = mod.sync_checkout

            def racing(*a, **k):
                out = real(*a, **k)
                subprocess.run(["git", "update-ref", "refs/heads/lead", moved], cwd=self.main,
                               env=self.env, check=True)
                return out
            return [mock.patch.object(mod, "sync_checkout", racing)]
        rc, out, err = self.sync_in("7", patches=patches)
        self.assertEqual(rc, 1, out + err)
        self.assertIn("moved", err)
        self.assertEqual(self.git("rev-parse", "refs/heads/lead").strip(), moved)

    # --- fail-closed inputs ------------------------------------------------------------------

    def refuses_unchanged(self, needle, env=None):
        before = self.state()
        p = self.sync("7", env=env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(needle, p.stderr)
        self.assertEqual(self.state(), before)

    def test_gh_failing_refuses(self):
        self.land({"hooks/x.sh": REAL})
        del self.env["FAKE_GH_OUT"]
        self.refuses_unchanged("gh")

    def test_an_open_pr_refuses(self):
        proven = self.land({"hooks/x.sh": REAL})
        self.gh_says({"state": "OPEN", "mergeCommit": {"oid": proven}, "baseRefName": "main"})
        self.refuses_unchanged("OPEN")

    def test_malformed_json_refuses(self):
        self.land({"hooks/x.sh": REAL})
        for bad in ("{", "[]", '{"state": "MERGED"}', '{"state": "MERGED", "mergeCommit": null,'
                    ' "baseRefName": "main"}'):
            with self.subTest(bad=bad):
                self.gh_says(bad)
                self.refuses_unchanged("gh")

    def test_a_missing_or_short_oid_refuses(self):
        proven = self.land({"hooks/x.sh": REAL})
        for commit in ({}, {"oid": proven[:12]}, {"oid": proven.upper()}):
            with self.subTest(commit=commit):
                self.gh_says({"state": "MERGED", "mergeCommit": commit, "baseRefName": "main"})
                self.refuses_unchanged("gh")

    def test_another_base_refuses(self):
        proven = self.land({"hooks/x.sh": REAL})
        self.merged(proven, base="dev")
        self.refuses_unchanged("dev")

    def test_an_oid_not_on_the_base_refuses(self):
        self.land({"hooks/x.sh": REAL})
        # A commit pushed to the remote, and in the shared repo, but never merged to main.
        side = self.git("commit-tree", "-m", "side", "pr7^{tree}", "-p", "pr7").strip()
        self.git("push", "-q", "origin", f"{side}:refs/heads/side")
        self.merged(side)
        self.refuses_unchanged("not on")
        self.merged("0" * 40)
        self.refuses_unchanged("not on")

    def test_an_unreachable_remote_refuses(self):
        self.land({"hooks/x.sh": REAL})
        self.git("remote", "set-url", "origin", os.path.join(self.tmp, "gone.git"))
        self.refuses_unchanged("fetch")

    def test_a_sandboxed_run_refuses(self):
        self.land({"hooks/x.sh": REAL})
        self.refuses_unchanged("sandbox", env={"_LANE_TEST_SANDBOXED": "1"})
        self.assertFalse(os.path.exists(self.verified))

    def test_missing_rules_refuse_before_any_store(self):
        self.land({"hooks/x.sh": REAL})
        for data in ({}, {"permissions": RULES["permissions"]},
                     {"sandbox": RULES["sandbox"]}, "not json"):
            with self.subTest(data=data):
                if isinstance(data, str):
                    self.write(os.path.join(self.home, ".claude", "settings.json"), data)
                else:
                    self.settings(data)
                self.refuses_unchanged("settings.json")
                self.assertFalse(os.path.exists(self.verified))

    def test_a_state_dir_outside_home_refuses(self):
        mod = load_lane_script()
        elsewhere = os.path.join(self.tmp, "elsewhere")
        with mock.patch.dict(os.environ, dict(self.env, XDG_STATE_HOME=elsewhere), clear=True):
            with self.assertRaises(mod.LaneError) as cm:
                with mod.store_guard("main"):
                    pass
        self.assertIn(".local/state/dotclaude", str(cm.exception))
        self.assertFalse(os.path.exists(elsewhere))

    def test_per_worktree_config_refuses_in_lead_mode(self):
        self.land({"hooks/x.sh": REAL})
        self.git("config", "extensions.worktreeConfig", "true")
        self.git("config", "--worktree", "filter.x.smudge", "touch planted")
        self.refuses_unchanged("extensions.worktreeConfig")
        self.assertFalse(os.path.exists(os.path.join(self.main, "planted")))
        self.assertFalse(os.path.exists(self.verified))

    def guard(self, name="main"):
        mod = load_lane_script()
        with mock.patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(mod.LaneError) as cm:
                with mod.store_guard(name):
                    pass
        return str(cm.exception)

    def test_a_link_or_file_at_the_stores_dir_refuses(self):
        os.makedirs(os.path.dirname(self.verified), exist_ok=True)
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        os.symlink(outside, self.verified)
        self.assertIn(self.verified, self.guard())
        self.assertEqual(os.listdir(outside), [])  # no .lock, no store through the link
        os.unlink(self.verified)
        self.write(self.verified, "")
        self.assertIn(self.verified, self.guard())
        os.unlink(self.verified)
        os.makedirs(self.verified)
        os.symlink(outside, os.path.join(self.verified, "main.git"))
        self.assertIn("main.git", self.guard())
        self.assertEqual(os.listdir(outside), [])

    def test_only_the_main_checkout_runs_lead_mode(self):
        self.lane("new", "chart-fix")
        p = self.sync("7", cwd=self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lead", p.stderr)

    # --- lane mode ---------------------------------------------------------------------------

    def test_lane_mode_merges_the_fetched_base(self):
        self.lane("new", "chart-fix")
        lane = self.lane_path("chart-fix")
        self.commit("chart.txt", "lane work\n", cwd=lane)
        pinned = self.git("rev-parse", "HEAD", cwd=lane).strip()
        proven = self.land({"hooks/x.sh": REAL})
        self.git("update-ref", "refs/remotes/origin/main", pinned)  # a stale or planted ref
        p = self.sync(cwd=lane)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.parents(cwd=lane), [pinned, proven])
        self.assertEqual(self.read(os.path.join(lane, "hooks", "x.sh")), REAL)
        self.assertEqual(self.read(os.path.join(lane, "chart.txt")), "lane work\n")
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main").strip(), proven)

    def test_lane_mode_refuses_a_conflict(self):
        self.lane("new", "chart-fix")
        lane = self.lane_path("chart-fix")
        self.commit("README.md", "lane readme\n", cwd=lane)
        self.land({"README.md": "main readme\n"})
        before = self.state(lane)
        p = self.sync(cwd=lane)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("README.md", p.stderr)
        self.assertEqual(self.state(lane), before)


class CommitGraphOff(unittest.TestCase):
    """git takes a commit's parents from objects/info/commit-graph when there is one, and any
    lane can write that file (it exists legitimately, so the tripwire can't flag it). sync_env
    and harden_git_env turn the graph off: a planted parent never answers an ancestry check."""

    def setUp(self):
        self.tmp = os.path.realpath(__import__("tempfile").mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {"HOME": self.tmp, "PATH": os.environ["PATH"], "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        self.work = os.path.join(self.tmp, "repo")
        self.git("init", "-q", "-b", "main", self.work, cwd=self.tmp)
        self.common = os.path.join(self.work, ".git")
        # Dated in order, so the side commit's generation never rules it out as an ancestor.
        self.commit("a", 1000)
        self.git("branch", "side")
        self.git("checkout", "-q", "side")
        self.side = self.commit("s", 2000)
        self.git("checkout", "-q", "main")
        mid = self.commit("b", 3000)
        self.tip = self.commit("c", 4000)
        # The tip named on the command line parses from its object; its parent from the graph.
        self.plant_parent(mid, self.side)

    def git(self, *args, cwd=None, env=None):
        return subprocess.run(["git", *args], cwd=cwd or self.work, env=env or self.env,
                              check=True, capture_output=True, text=True).stdout

    def commit(self, msg, when):
        date = f"{1_600_000_000 + when} +0000"
        self.git("commit", "-q", "--allow-empty", "-m", msg,
                 env=dict(self.env, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date))
        return self.git("rev-parse", "HEAD").strip()

    def plant_parent(self, child, parent):
        """A commit-graph in which child's first parent is parent."""
        self.git("commit-graph", "write", "--reachable")
        path = os.path.join(self.common, "objects", "info", "commit-graph")
        with open(path, "rb") as f:
            data = bytearray(f.read())
        chunks = {bytes(data[8 + 12 * i:12 + 12 * i]):
                  int.from_bytes(data[12 + 12 * i:20 + 12 * i], "big") for i in range(data[6])}
        n = int.from_bytes(data[chunks[b"OIDF"] + 255 * 4:chunks[b"OIDF"] + 256 * 4], "big")
        oids = [bytes(data[chunks[b"OIDL"] + 20 * i:chunks[b"OIDL"] + 20 * i + 20]).hex()
                for i in range(n)]
        at = chunks[b"CDAT"] + 36 * oids.index(child) + 20
        data[at:at + 4] = oids.index(parent).to_bytes(4, "big")
        os.chmod(path, 0o644)
        with open(path, "wb") as f:
            f.write(data)

    def ancestor(self, env):
        full = dict(self.env, **env)
        return subprocess.run(["git", "merge-base", "--is-ancestor", self.side, self.tip],
                              cwd=self.work, env=full, capture_output=True).returncode

    def test_a_planted_parent_fools_plain_git(self):
        self.assertEqual(self.ancestor({}), 0)  # the control: the graph is read

    def test_sync_env_never_reads_the_graph(self):
        mod = load_lane_script()
        env = mod.sync_env(self.common)
        keys = {env[k]: env[k.replace("KEY", "VALUE")] for k in env
                if k.startswith("GIT_CONFIG_KEY_")}
        self.assertEqual(keys.get("core.commitGraph"), "false")
        self.assertEqual(self.ancestor(env), 1)

    def test_harden_git_env_never_reads_the_graph(self):
        mod = load_lane_script()
        with mock.patch.dict(os.environ, self.env, clear=True):
            mod.harden_git_env(mock.Mock(common_dir=self.common))
            env = dict(os.environ)
        self.assertIn("'core.commitGraph'='false'", env["GIT_CONFIG_PARAMETERS"])
        self.assertEqual(self.ancestor(env), 1)


if __name__ == "__main__":
    unittest.main()
