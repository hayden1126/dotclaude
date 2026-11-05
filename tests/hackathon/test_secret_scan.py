"""skills/hackathon/scripts/secret-scan: planted secrets in temp git repos.

Every fake value is built at runtime from a seeded generator, so this file holds nothing that
looks like a real token, and a scan of the file itself stays clean."""
import glob
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "hackathon")
SCRIPT = os.path.join(SKILL, "scripts", "secret-scan")

RNG = random.Random(20261105)


def tail(n, alphabet=string.ascii_letters + string.digits):
    """A random-looking run, with a digit and a letter so the entropy check always passes."""
    return "a7" + "".join(RNG.choices(alphabet, k=n - 2))


def upper_tail(n):
    return "A7" + "".join(RNG.choices(string.ascii_uppercase + string.digits, k=n - 2))


# rule -> (line to commit, the part that must never be printed)
def planted():
    out = {}

    def add(rule, line_format, prefix, secret):
        out[rule] = (line_format.format(prefix + secret), secret)

    add("aws-access-key", "aws_id = {}", "AK" + "IA", upper_tail(16))
    add("github-token", "gh = {}", "gh" + "p_", tail(36))
    add("stripe-key", "pay = {}", "sk_" + "live_", tail(24))
    add("google-key", "maps = {}", "AI" + "za", tail(35))
    add("slack-token", "chat = {}", "xo" + "xb-", tail(40))
    add("slack-webhook", "hook = https://{}", "hooks.slack.com/services/T" + "123/B456/", tail(24))
    add("openai-key", "llm = {}", "sk-" + "proj-", tail(40))
    add("anthropic-key", "llm2 = {}", "sk-" + "ant-", tail(40))
    add("assignment", "API_KEY={}", "", tail(32))
    add("url-password", "url = postgres://admin:{}@db.vendor.test/app", "", tail(20))
    return out


def private_key_line():
    return "-----BEGIN " + "RSA PRIVATE" + " KEY-----"


class ScanCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="secret-scan-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        # The sandbox and the machine's git config stay out: only what a test sets applies.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=self.home, XDG_CONFIG_HOME=self.home, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t.test",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t.test")
        self.work = os.path.join(self.root, "work")
        os.makedirs(self.work)
        self.git("init", "-q", "-b", "main")

    def git(self, *args, cwd=None):
        p = subprocess.run(["git", *args], cwd=cwd or self.work, env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def commit(self, name, text, message="c"):
        path = os.path.join(self.work, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        self.git("add", "-f", "--", name)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def scan(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-I", SCRIPT, *args], cwd=cwd or self.work,
                              env=env or self.env, capture_output=True, text=True)

    def add_pushed_upstream(self):
        """A bare remote holding what's committed so far, with main tracking it."""
        bare = os.path.join(self.root, "remote.git")
        self.git("init", "-q", "--bare", bare)
        self.git("remote", "add", "origin", bare)
        self.git("push", "-q", "-u", "origin", "main")


class Shape(unittest.TestCase):
    def test_it_starts_isolated_and_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with open(SCRIPT) as f:
            self.assertEqual(f.readline().rstrip("\n"), "#!/usr/bin/python3 -I")


class Secrets(ScanCase):
    def test_each_kind_is_caught_and_its_value_never_printed(self):
        for rule, (line, secret) in planted().items():
            with self.subTest(rule):
                self.commit("app.txt", f"before\n{line}\n", rule)
                p = self.scan()
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(f"app.txt:2 {rule} ", p.stdout)
                self.assertNotIn(secret, p.stdout + p.stderr)
                self.git("rm", "-q", "app.txt")
                self.git("commit", "-q", "-m", "gone")

    def test_a_private_key_block_is_caught(self):
        self.commit("k.txt", private_key_line() + "\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1)
        self.assertIn("k.txt:1 private-key-block ", p.stdout)
        self.assertNotIn("RSA", p.stdout)

    def test_the_report_names_the_commit_path_line_and_rule(self):
        line, _ = planted()["github-token"]
        sha = self.commit("src/a b.py", f"one\ntwo\n{line}\n")
        p = self.scan()
        self.assertIn(f"{sha[:12]} src/a b.py:3 github-token gh", p.stdout)

    def test_assignment_forms(self):
        for line in ('apiKey: "{}"', '"client_secret": "{}"', "export X_TOKEN='{}'",
                     'password = "{}"', "AWS_SECRET_ACCESS_KEY={}"):
            with self.subTest(line):
                value = tail(32)
                self.commit("cfg.txt", line.format(value) + "\n", line)
                p = self.scan()
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn("cfg.txt:1 assignment ***", p.stdout)
                self.assertNotIn(value, p.stdout)
                self.git("rm", "-q", "cfg.txt")
                self.git("commit", "-q", "-m", "gone")

    def test_secret_files_by_name(self):
        for name in (".env", ".env.local", "deep/er/server.pem", "id_rsa", "sub/credentials.json"):
            with self.subTest(name):
                self.commit(name, "nothing secret inside\n", name)
                p = self.scan()
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn(f"{name}:- secret-file", p.stdout)
                self.git("rm", "-q", "--", name)
                self.git("commit", "-q", "-m", "gone")

    def test_a_binary_secret_file_is_caught_by_name_and_counted(self):
        path = os.path.join(self.work, "bundle.p12")
        with open(path, "wb") as f:
            f.write(b"\0\1\2binary")
        self.git("add", "-f", "bundle.p12")
        self.git("commit", "-q", "-m", "binary")
        p = self.scan()
        self.assertEqual(p.returncode, 1)
        self.assertIn("bundle.p12:- secret-file", p.stdout)
        self.assertIn("1 binary file change(s)", p.stderr)

    def test_a_secret_only_a_merge_adds_is_seen(self):
        line, _ = planted()["stripe-key"]
        self.commit("a.txt", "base\n")
        self.git("checkout", "-q", "-b", "side")
        self.commit("b.txt", "side\n")
        self.git("checkout", "-q", "main")
        self.commit("c.txt", "main\n")
        self.git("merge", "-q", "--no-ff", "--no-commit", "side")
        with open(os.path.join(self.work, "evil.txt"), "w") as f:
            f.write(line + "\n")
        self.git("add", "evil.txt")
        self.git("commit", "-q", "-m", "merge")
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("evil.txt:1 stripe-key", p.stdout)

    def test_a_secret_from_a_side_branch_is_reported_once_not_again_at_its_merge(self):
        line, _ = planted()["stripe-key"]
        self.commit("a.txt", "base\n")
        self.git("checkout", "-q", "-b", "side")
        self.commit("b.txt", line + "\n")
        self.git("checkout", "-q", "main")
        self.commit("c.txt", "main\n")
        self.git("merge", "-q", "--no-ff", "-m", "merge", "side")
        p = self.scan()
        self.assertEqual(p.stdout.count("stripe-key"), 1, p.stdout)


class Clean(ScanCase):
    def test_clean_commits_pass(self):
        self.commit("README.md", "# A project\n\nNo secrets here.\n")
        self.commit("src/app.py", "def main():\n    return 1\n")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("clean, 2 commit(s)", p.stdout)

    def test_ordinary_code_is_not_a_finding(self):
        lines = ["token = generateTokenForSessionHandler(user)",
                 "API_KEY = process.env.STRIPE_SECRET_KEY_2",
                 "API_KEY=your_api_key_goes_here_123",
                 "monkey = a7b8c9d0e1f2a3b4c5d6",
                 "password_hint = 1111111111111111a",
                 "token_url = https://auth.vendor.test/oauth2/token1",
                 "DATABASE_URL=postgres://postgres:devpass@localhost:5432/app",
                 "task-switching-risk-assessment-for-long-css-class-names",
                 ".env is listed in the docs, as is id_rsa"]
        self.commit("code.txt", "\n".join(lines) + "\n")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_an_example_env_file_passes_by_name_but_its_content_is_read(self):
        self.commit(".env.example", "API_KEY=\n")
        self.assertEqual(self.scan().returncode, 0)
        line, _ = planted()["assignment"]
        self.commit(".env.example", line + "\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1)
        self.assertIn(".env.example:1 assignment", p.stdout)

    def test_deleting_a_secret_file_is_not_a_new_finding(self):
        self.commit(".env", "x\n")
        self.add_pushed_upstream()
        self.git("rm", "-q", ".env")
        self.git("commit", "-q", "-m", "remove")
        self.assertEqual(self.scan().returncode, 0)

    def test_an_added_line_that_reads_like_a_diff_header_changes_nothing(self):
        line, _ = planted()["github-token"]
        self.commit("patch.txt", "++ b/.env\ndiff --git a/x b/x\n" + line + "\n")
        p = self.scan()
        self.assertIn("patch.txt:3 github-token", p.stdout)
        self.assertNotIn(".env", p.stdout)


class Allow(ScanCase):
    def test_the_comment_suppresses_that_line_only(self):
        line, _ = planted()["stripe-key"]
        self.commit("a.py", f"{line}  # secret-scan: allow\n")
        self.assertEqual(self.scan().returncode, 0)
        other, _ = planted()["stripe-key"]
        self.commit("a.py", f"{line}  # secret-scan: allow\n{other}\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1)
        self.assertIn("a.py:2 stripe-key", p.stdout)
        self.assertNotIn("a.py:1", p.stdout)

    def test_it_does_not_excuse_a_file_name(self):
        self.commit(".env", "A=1  # secret-scan: allow\n")
        self.assertEqual(self.scan().returncode, 1)


class Ranges(ScanCase):
    def test_all_reaches_a_secret_removed_in_a_later_commit(self):
        line, secret = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.commit("a.txt", "clean now\n")
        self.add_pushed_upstream()
        self.assertEqual(self.scan().returncode, 0)  # the push range is empty
        p = self.scan("--all")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("a.txt:1 github-token", p.stdout)
        self.assertNotIn(secret, p.stdout)

    def test_all_reaches_another_branch_but_not_the_stash(self):
        line, _ = planted()["github-token"]
        self.commit("a.txt", "base\n")
        with open(os.path.join(self.work, "a.txt"), "w") as f:
            f.write(line + "\n")
        self.git("stash", "-q")
        self.assertEqual(self.scan("--all").returncode, 0)
        self.git("checkout", "-q", "-b", "other")
        self.commit("b.txt", line + "\n")
        self.git("checkout", "-q", "main")
        p = self.scan("--all")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("b.txt:1", p.stdout)

    def test_with_an_upstream_only_unpushed_commits_are_read(self):
        old, _ = planted()["github-token"]
        self.commit("old.txt", old + "\n")
        self.add_pushed_upstream()
        self.assertEqual(self.scan().returncode, 0)
        self.commit("clean.txt", "fine\n")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("clean, 1 commit(s), @{push}..HEAD", p.stdout)
        new, _ = planted()["stripe-key"]
        self.commit("new.txt", new + "\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1)
        self.assertIn("new.txt:1 stripe-key", p.stdout)
        self.assertNotIn("old.txt", p.stdout)

    def test_a_secret_removed_before_the_push_still_counts(self):
        # It's in a commit being pushed, so a public remote would serve it.
        self.commit("a.txt", "base\n")
        self.add_pushed_upstream()
        line, _ = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.commit("a.txt", "clean\n")
        self.assertEqual(self.scan().returncode, 1)

    def test_with_no_upstream_all_of_heads_history_is_read(self):
        line, _ = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.commit("a.txt", "clean now\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("all of HEAD's history", p.stdout)

    def test_a_detached_head_reads_all_of_its_history(self):
        line, _ = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.add_pushed_upstream()
        self.git("checkout", "-q", "--detach")
        self.assertEqual(self.scan().returncode, 1)

    def test_the_users_git_config_cannot_hide_anything(self):
        # Each of these changes `git log -p` output a parser would otherwise trust.
        line, _ = planted()["github-token"]
        self.commit("sub/a.txt", line + "\n")
        for key, value in (("log.showroot", "false"), ("diff.noprefix", "true"),
                           ("diff.mnemonicPrefix", "true"), ("color.ui", "always"),
                           ("diff.relative", "true"), ("diff.renames", "copies"),
                           ("log.showSignature", "true"),
                           ("diff.external", "/bin/false")):
            with self.subTest(key):
                self.git("config", key, value)
                p = self.scan(cwd=os.path.join(self.work, "sub"))
                self.git("config", "--unset", key)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn("sub/a.txt:1 github-token", p.stdout)


class CantRun(ScanCase):
    def assert_cant_run(self, p):
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertNotIn("clean", p.stdout)
        self.assertIn("can't run", p.stderr)

    def test_outside_a_repo(self):
        outside = os.path.join(self.root, "plain")
        os.makedirs(outside)
        env = {**self.env, "GIT_CEILING_DIRECTORIES": self.root}
        self.assert_cant_run(self.scan(cwd=outside, env=env))

    def test_a_repo_with_no_commits(self):
        self.assert_cant_run(self.scan())

    def test_git_missing(self):
        self.commit("a.txt", "x\n")
        empty = os.path.join(self.root, "nobin")
        os.makedirs(empty)
        self.assert_cant_run(self.scan(env={**self.env, "PATH": empty}))

    def test_a_git_failure_partway_is_not_clean(self):
        blob = self.git("rev-parse", self.commit("a.txt", "x\n") + ":a.txt")
        os.remove(os.path.join(self.work, ".git", "objects", blob[:2], blob[2:]))
        self.assert_cant_run(self.scan())

    def test_a_shallow_clone_cannot_claim_a_whole_history(self):
        self.commit("a.txt", "one\n")
        self.commit("a.txt", "two\n")
        clone = os.path.join(self.root, "shallow")
        self.git("clone", "-q", "--depth", "1", "file://" + self.work, clone)
        self.assert_cant_run(self.scan("--all", cwd=clone))

    def test_a_bad_argument(self):
        self.commit("a.txt", "x\n")
        self.assertEqual(self.scan("--nope").returncode, 2)


class TheSkillsOwnFiles(ScanCase):
    def test_they_scan_clean_when_copied_into_a_project(self):
        # A team may copy this folder into its repo: the scan must not trip on itself.
        files = [SCRIPT, os.path.abspath(__file__)]
        files += [p for p in glob.glob(os.path.join(SKILL, "**", "*"), recursive=True)
                  if os.path.isfile(p)]
        self.assertGreater(len(files), 5)
        for i, path in enumerate(sorted(set(files))):
            shutil.copy(path, os.path.join(self.work, f"{i}-{os.path.basename(path)}"))
        self.git("add", "-A", "-f")
        self.git("commit", "-q", "-m", "copy")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
