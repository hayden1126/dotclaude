"""skills/hackathon/scripts/secret-scan: planted secrets in temp git repos.

Every fake value is built at runtime from a seeded generator, so this file holds nothing that
looks like a real token, and a scan of the file itself stays clean."""
import glob
import os
import random
import re
import shlex
import shutil
import string
import subprocess
import sys
import tempfile
import time
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
    add("openrouter-key", "llm3 = {}", "sk-" + "or-" + "v1-", tail(64))
    add("groq-key", "llm4 = {}", "gs" + "k_", tail(52))
    add("huggingface-token", "llm5 = {}", "hf" + "_", tail(34))
    add("replicate-token", "llm6 = {}", "r8" + "_", tail(40))
    add("xai-key", "llm7 = {}", "xa" + "i-", tail(80))
    add("jwt", "session = {}", "ey" + "J", tail(20) + ".ey" + "J" + tail(30) + "." + tail(20))
    add("bearer-token", "curl -H 'Authorization: Bearer {}'", "", tail(32))
    add("assignment", "API_KEY={}", "", tail(32))
    add("url-password", "url = postgres://admin:{}@db.vendor.test/app", "", tail(20))
    return out


def private_key_line():
    return "-----BEGIN " + "RSA PRIVATE" + " KEY-----"


# File names, shared by the scan's tests and the template's, and each table checked by both.
# Flagged by the scan and hidden by the gitignore template.
FLAGGED_AND_IGNORED = (
    ".env", ".env.local", ".env-local", ".env_prod", ".envrc", ".envrc.local", ".envrc-local",
    ".envrc_local", ".env copy", ".env (1)", ".env(1)", ".env - Copy", ".env 2", ".envrc copy", ".envrc (1)",
    ".envrc(1)",
    ".env~", ".envrc~", "#.env#", "#.envrc#", ".env.~1~", ".envrc.~1~", ".env.bak", ".env.save",
    ".envrc.bak", ".env-local~", ".envrc-local~", ".env.example~", ".env.sample.bak",
    "secrets.env", "prod.env", ".secrets.env", "prod.env~", "prod.env.bak", "deep/er/.env~",
    "id_rsa~", "#id_rsa#", "id_rsa.~1~", "id_rsa.bak", "id_rsa.bak~", "id_rsa~.bak", "id_rsa.old",
    "server.pem.bak", "server.pem~", "#.pem", "server.key~", "credentials.json~",
    "credentials.json.orig", "service-account.json.tmp", "service_account.json", "bundle.p12.backup", "app.jks.temp",
    ".netrc", ".pgpass", ".htpasswd", ".git-credentials", "app.jks", "app.keystore",
)
# Flagged by the scan only: the template leaves `.save` and copies outside the env family to it.
FLAGGED_NOT_IGNORED = (
    "credentials (1).json", "credentials(1).json", "credentials 2.json", "id_rsa 2", "id_rsa(1)",
    "credentials copy.json", "credentials copy 2.json",
    "credentials - Copy.json", "credentials - Copy (2).json", "credentials (copy).json",
    "credentials (copy 2).json", "credentials (another copy).json", "credentials (3rd copy).json",
    "id_rsa copy", "id_rsa (1)", "id_rsa - Copy", "server.key.save",
    "server.key.save.1", "credentials (conflicted copy 2018-04-10 093612).json",
    "credentials (someone's conflicted copy 2026-01-01).json",
    "credentials.sync-conflict-20260101-120000-ABCDEFG.json",
    "id_rsa.sync-conflict-20260101-120000-ABCDEFG",
)
# Each safe word in these forms is clean to the scan and kept by the template.
SAFE_FORMS = (".env.{}", ".env-{}", ".env_{}", ".envrc.{}", ".envrc-{}", ".envrc_{}", "{}.env", ".{}.env",
              "app.{}.env", "app-{}.env", "app_{}.env")
# Clean to the scan and kept by the template.
CLEAN_AND_KEPT = (
    ".environment.ts", ".envoy.yaml", "report (1).pdf", "id_rsa.pub", "keys copy.txt",
    "credentials.py", "credentials.json.ts", "level1.save",
)
# Clean to the scan, hidden as an ordinary backup.
CLEAN_AND_IGNORED = ("notes.bak", "draft~", "#draft#", "id_rsa.pub.bak", ".main.py.swp", "data.old")


def read_skill(name):
    with open(os.path.join(REPO, "skills", name, "SKILL.md"), encoding="utf-8") as f:
        return f.read()


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

    def commit_names(self, names):
        """One commit of harmless files, so a single scan reads every name."""
        for name in names:
            path = os.path.join(self.work, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("nothing secret inside\n")
        self.git("add", "-f", "--", *names)
        self.git("commit", "-q", "-m", "names")

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

    def test_a_crash_is_cant_run_never_clean(self):
        with open(SCRIPT) as f:
            source = f.read()
        self.assertIn("def main():", source)
        broken = source.replace("def main():", "def main():\n    raise RuntimeError('boom')\n\n\ndef _main():", 1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "broken")
            with open(path, "w") as f:
                f.write(broken)
            p = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, cwd=d)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("can't run", p.stderr)


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

    def test_env_file_variants_by_name(self):
        # The clean names first: the scan reads all of HEAD's history, so a flagged name stays found.
        for name in (".environment.ts", ".env.example", ".env-example", ".env_sample"):
            with self.subTest(name):
                self.commit(name, "nothing secret inside\n", name)
                p = self.scan()
                self.assertEqual(p.returncode, 0, p.stdout)
        for name in (".envrc", ".envrc.local", ".env-local", ".env_prod", "deploy/.env.staging"):
            with self.subTest(name):
                self.commit(name, "nothing secret inside\n", name)
                p = self.scan()
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn(f"{name}:- secret-file", p.stdout)

    def test_each_family_name_is_flagged(self):
        self.commit_names(FLAGGED_AND_IGNORED + FLAGGED_NOT_IGNORED)
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        for name in FLAGGED_AND_IGNORED + FLAGGED_NOT_IGNORED:
            with self.subTest(name):
                self.assertIn(f" {name}:- secret-file", p.stdout)

    def test_a_name_with_no_secret_under_its_marks_is_clean(self):
        self.commit_names(CLEAN_AND_KEPT + CLEAN_AND_IGNORED)
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_the_example_names_pass(self):
        names = [form.format(word) for word in ("example", "sample", "template", "dist", "default", "defaults")
                 for form in SAFE_FORMS]
        self.commit_names(names)
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_a_backup_mark_on_a_name_git_quotes(self):
        self.commit_names(['a"b.env~'])  # git quotes a path that holds a double quote
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("secret-file", p.stdout)

    def test_a_binary_secret_file_is_caught_by_name(self):
        path = os.path.join(self.work, "bundle.p12")
        with open(path, "wb") as f:
            f.write(b"\0\1\2binary")
        self.git("add", "-f", "bundle.p12")
        self.git("commit", "-q", "-m", "binary")
        p = self.scan()
        self.assertEqual(p.returncode, 1)
        self.assertIn("bundle.p12:- secret-file", p.stdout)

    def assert_each_line_found(self, cases):
        for line, rule, secret in cases:
            with self.subTest(line=line):
                sha = self.commit("cfg.txt", line + "\n", "case")
                p = self.scan()
                self.assertEqual(p.returncode, 1, p.stdout)
                own = [row for row in p.stdout.splitlines() if row.startswith(sha[:12])]
                self.assertEqual(len(own), 1, p.stdout)
                self.assertIn(f"cfg.txt:1 {rule} ", own[0])
                self.assertNotIn(secret, p.stdout + p.stderr)
                self.git("rm", "-q", "cfg.txt")
                self.git("commit", "-q", "-m", "gone")

    def test_a_token_is_caught_wherever_it_sits_on_the_line(self):
        groq = "gs" + "k_" + tail(52)
        hf = "hf" + "_" + tail(34)
        jwt = "ey" + "J" + tail(20) + ".ey" + "J" + tail(30) + "." + tail(20)
        self.assert_each_line_found([
            (f'headers = {{"Authorization": "Bearer {groq}"}}', "groq-key", groq[4:]),
            (f'const k = process.env.K || "{hf}"', "huggingface-token", hf[4:]),
            (f'new Groq("{groq}")', "groq-key", groq[4:]),
            (f"SUPABASE_SERVICE_ROLE={jwt}", "jwt", jwt[4:]),
        ])

    def test_the_wider_assignment_names(self):
        value = tail(32)
        self.assert_each_line_found([
            (f"{name}={value}", "assignment", value)
            for name in ("DB_PASS", "pass_prod", "api_keys", "tokens", "SUPABASE_SERVICE_ROLE", "serviceRoleKey")
        ] + [(f'"Authorization": "{value}"', "assignment", value)])

    def test_a_type_annotation_does_not_hide_a_value(self):
        value = tail(32)
        self.assert_each_line_found([(f'api_key: str = "{value}"', "assignment", value)])

    def test_a_short_plain_password_is_a_finding(self):
        plain = "Hack" + "athon2026!"
        self.assert_each_line_found([
            (f"ADMIN_PASSWORD={plain}", "assignment", plain),
            (f"DB_PASS={'sun' + 'shine'}", "assignment", "sunshine"),
            (f"- POSTGRES_PASSWORD={'sun' + 'shine'}", "assignment", "sunshine"),
            (f'passwd = "{plain}"', "assignment", plain),
            ('"pwd": "{}"'.format("correct " + "horse"), "assignment", "correct horse"),
            (f'db_password: str = "{plain}"', "assignment", plain),
            (f'connect(password="{plain}")', "assignment", plain),
            (f'if (password === "{plain}") ok()', "assignment", plain),
            (f"pass: {'hunter' + '2222'}", "assignment", "hunter2222"),
        ])

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

    def test_ordinary_password_and_bearer_code_is_not_a_finding(self):
        lines = ["password = user.password",
                 "password: hashedPassword,",
                 "connect(password=db_password)",
                 "pass: config.db2.pass",
                 "password = getPassword2(12345678)",
                 "PASSWORD=changeme123",
                 "PASSWORD=$DB_PASSWORD",
                 'password: "********"',
                 'password = "short"',
                 'password = "<your password>"',
                 'password = f"{prefix}{suffix}"',
                 'password: `${first}${second}`',
                 'pass = "{{ secrets.DB_PASS }}"',
                 "PWD=/srv/app/current",
                 "pass_through = upstream12",
                 "const pass = process.env.DB_PASS",
                 '"Bearer ${token}"',
                 "Bearer YOUR_ACCESS_TOKEN_GOES_HERE",
                 "the bearer token goes in the header"]
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

    def test_an_example_envrc_passes_by_name_but_its_content_is_read(self):
        self.commit(".envrc.example", "export API_KEY=\n")
        self.assertEqual(self.scan().returncode, 0)
        line, _ = planted()["assignment"]
        self.commit(".envrc.example", line + "\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1)
        self.assertIn(".envrc.example:1 assignment", p.stdout)

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

    def test_the_summary_counts_what_the_comment_suppressed(self):
        one, _ = planted()["stripe-key"]
        two, _ = planted()["github-token"]
        self.commit("a.py", f"{one}  # secret-scan: allow\n{two}  # secret-scan: allow\n")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("clean, 1 commit(s), 2 line(s) allowed by comment", p.stdout)
        third, _ = planted()["groq-key"]
        self.commit("b.py", third + "\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("2 line(s) allowed by comment", p.stdout)

    def test_a_comment_on_a_line_with_no_finding_counts_for_nothing(self):
        self.commit("a.py", "x = 1  # secret-scan: allow\n")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("allowed", p.stdout)

    def test_a_merge_does_not_count_an_allowed_line_twice(self):
        line, _ = planted()["stripe-key"]
        self.commit("a.txt", "base\n")
        self.git("checkout", "-q", "-b", "side")
        self.commit("b.txt", f"{line}  # secret-scan: allow\n")
        self.git("checkout", "-q", "main")
        self.commit("c.txt", "main\n")
        self.git("merge", "-q", "--no-ff", "-m", "merge", "side")
        self.assertIn("1 line(s) allowed by comment", self.scan().stdout)


class AllowName(ScanCase):
    def test_it_excuses_that_base_name_and_says_so(self):
        self.commit("docs/pitch.key", "a deck\n")
        self.assertEqual(self.scan().returncode, 1)
        p = self.scan("--allow-name", "pitch.key")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("allowed by --allow-name: docs/pitch.key", p.stdout)
        self.assertIn("clean, 1 commit(s), 1 file name(s) allowed by --allow-name", p.stdout)

    def test_it_is_repeatable_and_excuses_nothing_else(self):
        self.commit("pitch.key", "a deck\n")
        self.commit("demo.key", "a deck\n")
        self.commit("server.key", "not a deck\n")
        p = self.scan("--allow-name", "pitch.key", "--allow-name", "demo.key")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("server.key:- secret-file", p.stdout)
        self.assertNotIn("pitch.key:-", p.stdout)
        self.assertNotIn("demo.key:-", p.stdout)
        self.assertIn("2 file name(s) allowed", p.stdout)

    def test_it_takes_the_name_as_committed_marks_included(self):
        self.commit("id_rsa~", "x\n")
        self.assertEqual(self.scan("--allow-name", "id_rsa~").returncode, 0)
        self.assertEqual(self.scan("--allow-name", "id_rsa").returncode, 1)

    def test_it_excuses_the_name_not_the_content(self):
        line, _ = planted()["github-token"]
        self.commit("pitch.key", line + "\n")
        p = self.scan("--allow-name", "pitch.key")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("pitch.key:1 github-token", p.stdout)


class HiddenContent(ScanCase):
    def setUp(self):
        super().setUp()
        self.line, self.secret = planted()["aws-access-key"]

    def assert_found(self, path, rule="aws-access-key"):
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"{path}:1 {rule}", p.stdout)
        self.assertNotIn(self.secret, p.stdout + p.stderr)

    def test_a_repo_attributes_file(self):
        self.commit(".gitattributes", "* -diff\n")
        self.commit("a.txt", self.line + "\n")
        self.assert_found("a.txt")

    def test_a_binary_attribute_on_a_folder(self):
        self.commit(".gitattributes", "data/** binary\n")
        self.commit("data/a.txt", self.line + "\n")
        self.assert_found("data/a.txt")

    def test_info_attributes(self):
        with open(os.path.join(self.work, ".git", "info", "attributes"), "w") as f:
            f.write("* -diff\n")
        self.commit("a.txt", self.line + "\n")
        self.assert_found("a.txt")

    def test_the_global_attributes_file(self):
        path = os.path.join(self.home, "attributes")
        with open(path, "w") as f:
            f.write("* -diff\n")
        self.git("config", "core.attributesFile", path)
        self.commit("a.txt", self.line + "\n")
        self.assert_found("a.txt")

    def test_a_low_big_file_threshold(self):
        self.git("config", "core.bigFileThreshold", "1")
        self.commit("a.txt", self.line + "\n")
        self.assert_found("a.txt")

    def test_a_replace_ref(self):
        self.commit("a.txt", self.line + "\n")
        with open(os.path.join(self.root, "clean"), "w") as f:
            f.write("nothing here\n")
        clean = self.git("hash-object", "-w", os.path.join(self.root, "clean"))
        self.git("replace", self.git("rev-parse", "HEAD:a.txt"), clean)
        self.assertNotIn("AK", self.git("log", "-p", "-1"))  # git itself now shows the swap
        self.assert_found("a.txt")

    def test_a_graft_file(self):
        self.commit("clean.txt", "clean\n")
        first = self.git("rev-parse", "HEAD").strip()
        self.commit("a.txt", self.line + "\n")
        self.commit("a.txt", "gone\n")
        with open(os.path.join(self.work, ".git", "info", "grafts"), "w") as f:
            f.write(f"{self.git('rev-parse', 'HEAD').strip()} {first}\n")
        self.assert_found("a.txt")

    def test_a_utf16_file(self):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            with self.subTest(encoding):
                with open(os.path.join(self.work, "a.txt"), "wb") as f:
                    f.write((self.line + "\nnext line\n").encode(encoding))
                self.git("add", "a.txt")
                self.git("commit", "-q", "-m", encoding)
                self.assert_found("a.txt")
                self.git("rm", "-q", "a.txt")
                self.git("commit", "-q", "-m", "gone")

    def test_a_utf16_line_past_the_first(self):
        with open(os.path.join(self.work, "a.txt"), "wb") as f:
            f.write(("one\ntwo\n" + self.line + "\n").encode("utf-16"))
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "utf16")
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("a.txt:3 aws-access-key", p.stdout)

    def test_a_token_among_binary_bytes(self):
        with open(os.path.join(self.work, "blob.bin"), "wb") as f:
            f.write(b"\0\1\2\xff\xfe" + self.line.encode() + b"\n\0\3")
        self.git("add", "blob.bin")
        self.git("commit", "-q", "-m", "binary")
        self.assert_found("blob.bin")

    def test_a_very_long_line_does_not_stall_the_scan(self):
        self.commit("bundle.txt", "a" * 2_000_000 + "\n" + self.line + "\n")
        p = subprocess.run([sys.executable, "-I", SCRIPT], cwd=self.work, env=self.env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("bundle.txt:2 aws-access-key", p.stdout)


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
        self.assertIn("clean, 1 commit(s), HEAD, commits not on any remote-tracking ref", p.stdout)
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

    def test_with_no_remote_tracking_refs_all_of_heads_history_is_read(self):
        line, _ = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.commit("a.txt", "clean now\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("all of HEAD's history", p.stdout)

    def test_a_detached_head_reads_what_is_not_pushed(self):
        old, _ = planted()["github-token"]
        self.commit("old.txt", old + "\n")
        self.add_pushed_upstream()
        self.git("checkout", "-q", "--detach")
        self.assertEqual(self.scan().returncode, 0)
        new, _ = planted()["stripe-key"]
        self.commit("new.txt", new + "\n")
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertNotIn("old.txt", p.stdout)

    def test_a_secret_on_another_branch_needs_that_branch_named(self):
        # The case the old @{push}..HEAD got wrong: `git push origin task-a` from main.
        self.commit("a.txt", "base\n")
        self.add_pushed_upstream()
        self.git("checkout", "-q", "-b", "task-a")
        line, _ = planted()["github-token"]
        self.commit("b.txt", line + "\n")
        self.git("checkout", "-q", "main")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("HEAD, commits not on", p.stdout)  # it says it read HEAD, not task-a
        p = self.scan("task-a")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("b.txt:1 github-token", p.stdout)
        self.assertIn("task-a, commits not on", p.stdout)

    def test_several_refs_are_all_read(self):
        self.commit("a.txt", "base\n")
        self.add_pushed_upstream()
        for branch, rule in (("one", "github-token"), ("two", "stripe-key")):
            self.git("checkout", "-q", "-b", branch, "main")
            self.commit(branch + ".txt", planted()[rule][0] + "\n")
        self.git("checkout", "-q", "main")
        p = self.scan("one", "two")
        self.assertIn("one.txt:1 github-token", p.stdout)
        self.assertIn("two.txt:1 stripe-key", p.stdout)

    def add_second_remote(self):
        bare = os.path.join(self.root, "public.git")
        self.git("init", "-q", "--bare", bare)
        self.git("remote", "add", "public", bare)
        return bare

    def test_remote_reads_what_that_remote_lacks(self):
        self.commit("a.txt", "base\n")
        self.add_pushed_upstream()
        self.add_second_remote()
        self.git("push", "-q", "public", "main")
        line, _ = planted()["github-token"]
        self.commit("b.txt", line + "\n")
        self.git("push", "-q", "origin", "main")
        self.assertEqual(self.scan().returncode, 0)  # on origin, so the default skips it
        p = self.scan("--remote", "public")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("b.txt:1 github-token", p.stdout)
        self.assertIn("commits not on public", p.stdout)

    def test_a_remote_never_pushed_to_means_the_whole_history(self):
        line, _ = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.commit("a.txt", "clean now\n")
        self.add_pushed_upstream()
        self.add_second_remote()
        p = self.scan("--remote", "public")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("all of HEAD's history (nothing tracked from public)", p.stdout)

    def test_a_remote_name_matches_only_that_remote(self):
        # `--remote pub` must not take its exclusions from `public`.
        line, _ = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.add_second_remote()
        self.git("push", "-q", "public", "main")
        self.assertEqual(self.scan("--remote", "public").returncode, 0)
        self.assertEqual(self.scan("--remote", "pub").returncode, 1)

    def test_a_key_in_pushed_history_does_not_trip_a_new_branch(self):
        line, _ = planted()["github-token"]
        self.commit("a.txt", line + "\n")
        self.commit("a.txt", "rotated\n")
        self.add_pushed_upstream()
        self.git("checkout", "-q", "-b", "new-branch")
        self.commit("b.txt", "fine\n")
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("clean, 1 commit(s)", p.stdout)
        p = self.scan("--all")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("a.txt:1 github-token", p.stdout)

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

    def test_a_shallow_clone_with_nothing_to_exclude_refuses(self):
        self.commit("a.txt", "one\n")
        self.commit("a.txt", "two\n")
        clone = os.path.join(self.root, "shallow")
        self.git("clone", "-q", "--depth", "1", "file://" + self.work, clone)
        self.assert_cant_run(self.scan("--remote", "public", cwd=clone))
        self.assertEqual(self.scan(cwd=clone).returncode, 0)  # origin's ref bounds the range
        self.git("remote", "remove", "origin", cwd=clone)
        self.assert_cant_run(self.scan(cwd=clone))

    def test_a_ref_that_does_not_resolve(self):
        self.commit("a.txt", "x\n")
        self.assert_cant_run(self.scan("no-such-branch"))
        self.assert_cant_run(self.scan("HEAD", "no-such-branch"))
        self.assert_cant_run(self.scan("HEAD~1..HEAD"))
        self.assert_cant_run(self.scan("HEAD:a.txt"))

    def test_a_ref_cannot_be_an_option_to_git_log(self):
        self.commit("a.txt", "x\n")
        self.assertEqual(self.scan("--", "--not").returncode, 2)

    def test_a_remote_that_is_a_pattern(self):
        self.commit("a.txt", "x\n")
        for pattern in ("*", "pub*", "", "[a]", "a\\b"):
            with self.subTest(pattern):
                self.assert_cant_run(self.scan("--remote", pattern))

    def test_all_takes_no_ref_or_remote(self):
        self.commit("a.txt", "x\n")
        self.assertEqual(self.scan("--all", "HEAD").returncode, 2)
        self.assertEqual(self.scan("--all", "--remote", "origin").returncode, 2)

    def test_a_bad_argument(self):
        self.commit("a.txt", "x\n")
        self.assertEqual(self.scan("--nope").returncode, 2)
        self.assertEqual(self.scan("--allow", "x").returncode, 2)  # no abbreviated flags


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


class Round2(ScanCase):
    """Shapes real projects hold. Fake values are built at runtime, as everywhere in this file."""

    def findings(self, line):
        self.commit("cfg.txt", line + "\n", line)
        p = self.scan()
        self.git("rm", "-q", "cfg.txt")
        self.git("commit", "-q", "-m", "gone")
        self.git("update-ref", "refs/remotes/seen/main", "HEAD")  # the next scan reads only its own line
        return p

    def assert_found(self, lines):
        for line, secret in lines:
            with self.subTest(line):
                p = self.findings(line)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertNotIn(secret, p.stdout)

    def assert_clean(self, lines):
        for line in lines:
            with self.subTest(line):
                p = self.findings(line)
                self.assertEqual(p.returncode, 0, p.stdout)

    def test_a_secret_inside_another_names_value(self):
        value = tail(24)
        short = "hunter" + "2222"
        self.assert_found([
            (f'fetch("https://newsapi.org/v2/top?apiKey={value}")', value),
            (f"run: API_KEY={value}", value),
            (f"jdbc:postgresql://h/db?user=u&password={short}", short),
            (f'cmd: "curl https://x.test/?token={value}&a=b"', value),
        ])

    def test_a_compound_name_in_one_word(self):
        value = tail(24)
        self.assert_found([(f"{name}={value}", value) for name in
                           ("PGPASSWORD", "AUTHTOKEN", "CLIENTSECRET", "SECRETKEY", "dbpassword", "APITOKEN")])
        plain = "sun" + "shine"
        self.assert_found([(f"PGPASSWORD={plain}", plain)])

    def test_words_that_only_end_like_a_secret_word(self):
        value = tail(24)
        self.assert_clean([f"{name} = {value}" for name in ("monkey", "turkey", "compass", "bypass", "cwd")])

    def test_a_weak_key_in_a_secret_name_with_no_digit(self):
        weak = "supersecret" + "keyforourapp"
        dashed = "my-super-" + "secret-signing-key"
        self.assert_found([
            (f'app.secret_key = "{weak}"', weak),
            (f"JWT_SECRET={weak}", weak),
            (f'client_secret: "{dashed}"', dashed),
            (f'const API_TOKEN = "{dashed}";', dashed),
            (f'signingKey: "{weak}"', weak),
        ])

    def test_a_name_that_only_holds_a_secret_word_keeps_its_word_shaped_value(self):
        self.assert_clean([
            'const STORAGE_KEY = "hackathon-demo-state-v1"',
            'const TOKEN_KEY = "app_access_token_v2"',
            'cacheKey: "user-session-cache-2024"',
            'SECRET_HEADER = "X-Webhook-Signature"',
            'token_endpoint = "oauth/access/token-exchange"',
            'api_key = "OPENWEATHER_API_KEY"',
            'secret: "see the docs for what goes here"',
            "secret_key = get_secret_key_from_vault",
            "client_secret=client_secret_value,",
        ])

    def test_a_kwarg_on_its_own_line_is_not_an_env_line(self):
        self.assert_clean(["    password=hashed_password,", "    password=hashed_password",
                           "  db_password=settings_password,  # from the vault"])
        plain = "sun" + "shine"
        self.assert_found([(f"    DB_PASSWORD={plain}", plain), (f"PASSWORD={plain}  # dev", plain)])

    def test_a_url_template_is_not_a_password(self):
        self.assert_clean(['url = f"postgres://{user}:{password}@{host}/db"',
                           "mongodb+srv://<username>:<password>@cluster0.mongodb.net/",
                           "postgres://user:password@host:5432/db",
                           "redis://default:%(pw)s@cache.vendor.test",
                           "postgres://$USER:$PASS@host/db",
                           "amqp://guest:secret@broker.vendor.test"])

    def test_a_url_with_no_username_still_holds_a_password(self):
        value = tail(12)
        self.assert_found([(f"REDIS_URL=redis://:{value}@cache.vendor.test:6379", value)])

    def test_a_placeholder_shaped_token_is_not_a_finding(self):
        self.assert_clean(["OPENAI_API_KEY=sk-" + "x" * 24,
                           "key = sk-" + "0" * 24,
                           "aws = AK" + "IAIOSFODNN7" + "EXAMPLE",
                           "gh = gh" + "p_" + "x" * 36])

    def test_a_message_is_not_a_password(self):
        self.assert_clean(['errors.password = "Password is required"',
                           'password: "Enter your password",',
                           'pass: "Must be at least 8 characters"',
                           'password = "Please try again later"',
                           '{"pass' + 'word": "y", "user": "someone"}'])
        phrase = "correct horse " + "battery staple"
        self.assert_found([(f'password = "{phrase}"', phrase)])

    def test_more_token_shapes(self):
        sendgrid = "SG" + "." + tail(22) + "." + tail(43)
        npm = "np" + "m_" + tail(36)
        supabase = "sb" + "p_" + tail(40, "abcdef0123456789")
        basic = "dXNlcjpwYXNz" + "d29yZDEyMw=="
        self.assert_found([(f'sgMail.setApiKey("{sendgrid}")', sendgrid), (f"reg = {npm}", npm),
                           (f"sup = {supabase}", supabase), (f"Authorization: Basic {basic}", basic)])
        self.assert_clean(["Basic authentication is on", "Basic ${credentials}", "// Basic usageExamples below"])

    def test_a_bracket_assignment(self):
        value = tail(24)
        plain = "Hack" + "athon2026!"
        self.assert_found([(f"app.config['SECRET_KEY'] = '{value}'", value),
                           (f'os.environ["DB_PASSWORD"] = "{plain}"', plain),
                           (f"settings['api_key'] = \"{value}\"", value)])
        self.assert_clean(["headers['Content-Type'] = 'application/json'", "cache['user_key'] = 'profile-page'"])

    def test_punctuation_inside_a_quoted_value(self):
        generated = "a7k2(m9x!q3" + "z)w8v^t5r&y1u%p6n#s4b"
        insecure = "django-insecure-" + "1a(2b3c4d5e6f7g"
        self.assert_found([(f"SECRET_KEY = '{generated}'", generated), (f"SECRET_KEY = '{insecure}'", insecure),
                           (f'client_secret: "{generated}"', generated)])

    def test_a_value_later_on_the_line(self):
        value = tail(24)
        weak = "supersecret" + "123"
        plain = "Hack" + "athon2026!"
        self.assert_found([(f'const JWT_SECRET = process.env.JWT_SECRET || "{weak}"', weak),  # practices-allow: SEC-41-fallback a planted line for the scanner to find
                           (f'API_KEY = os.getenv("API_KEY", "{value}")', value),  # practices-allow: SEC-41-fallback a planted line for the scanner to find
                           (f'secret_key: str | None = "{value}"', value),
                           (f'db_password = os.environ.get("DB_PASSWORD", "{plain}")', plain),  # practices-allow: SEC-41-fallback a planted line for the scanner to find
                           (f'"api_key = \\"{value}\\"\\n",', value),
                           (f'{{\\"pass' + f'word\\": \\"{plain}\\"}}', plain)])
        self.assert_clean(['const token = localStorage.getItem("auth_token_storage")',
                           'token = request.headers.get("X-Auth-Token-Header")',
                           'const apiKey = env.API_KEY ?? "missing-configuration"',
                           'secret = load("config/secrets.production.yml")',
                           'token = encode(`crypto.randomBytes(32).toString`)',
                           "the pass picked here (`skills/pass/SKILL.md:23,80,103`) stays"])

    def test_a_short_value_under_a_strong_name(self):
        self.assert_found([("JWT_SECRET=my" + "secret123", "secret123"), ('API_TOKEN = "abc' + '123def"', '123def')])
        self.assert_clean(['token: "required"', 'token = "Bearer"', 'tokens: "12345678"', 'token = "session-v2"'])

    def test_a_suffix_after_the_secret_word(self):
        plain = "Hack" + "athon2026!"
        self.assert_found([(f"DB_PASSWORD_PROD={plain}", plain), (f"ADMIN_PASSWORD_2={plain}", plain),
                           ("JWT_SECRET_STAGING=my" + "secret123", "secret123")])
        self.assert_clean(['password_hint = "the name of my dog"', "password_reset_url = /reset/form/here"])

    def test_a_dollar_sign_inside_a_real_value(self):
        dollar = "$uper" + "S3cret!"
        self.assert_found([("mongodb+srv://u:Pa$$" + "w0rd1@cluster0.vendor.test/", "w0rd1"),
                           (f'password = "{dollar}"', "S3cret")])
        self.assert_clean(["PASSWORD=$DB_PASSWORD", "PASSWORD=${DB_PASSWORD}", "password = $(cat /run/secret)",
                           "postgres://$USER:$PASS@host/db", 'secrets="$HOME/.secrets.env"'])

    def test_a_code_reference_is_not_a_secret(self):
        self.assert_clean(["clientSecret: env.AUTH0_CLIENT_SECRET,", "client_secret=settings.OAUTH2_CLIENT_SECRET,",
                           "authenticate(password=password1)", "apiKey: config.google.mapsKey2,"])
        value = tail(24)
        self.assert_found([(f"api_key: {value}", value), ("pass: hunter" + "2222", "2222")])

    def test_ordinary_values_under_a_weak_name(self):
        self.assert_clean(['authDomain: "my-app-a1b2c.firebaseapp.com"', 'Key: "uploads/avatars/user123.png"',
                           'token_endpoint: "/oauth2/v1/token"', "key: ubuntu22-node18-deps",
                           '"pass' + 'word": "Pass' + 'word"', 'errors.password = "Too short"'])

    def test_two_values_in_a_merge_are_both_reported(self):
        first, second = tail(24), tail(24)
        self.commit("a.txt", "base\n")
        self.git("checkout", "-q", "-b", "side")
        self.commit("cfg.txt", f"API_KEY={first}\n")
        self.git("checkout", "-q", "main")
        self.commit("c.txt", "main\n")
        self.git("merge", "-q", "--no-ff", "--no-commit", "side")
        with open(os.path.join(self.work, "cfg.txt"), "a") as f:
            f.write(f"JWT_SECRET={second}\n")
        self.git("add", "cfg.txt")
        self.git("commit", "-q", "-m", "merge")
        p = self.scan()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(p.stdout.count("cfg.txt:"), 2, p.stdout)

    def test_a_dotted_run_does_not_stall_the_scan(self):
        started = time.monotonic()
        self.commit("min.js", "a." * 200000 + "\n")
        self.assertEqual(self.scan().returncode, 0)
        self.assertLess(time.monotonic() - started, 60)

    def test_provider_tokens_under_a_neutral_name(self):
        hexa = "0123456789abcdef"
        cases = [("gl" + "pat-", tail(24)), ("nt" + "n_", tail(46)), ("do" + "p_v1_", tail(64, hexa)),
                 ("dp" + ".pt.", tail(40)), ("li" + "n_api_", tail(40)), ("sh" + "pat_", tail(32, hexa)),
                 ("pscale" + "_tkn_", tail(40)), ("pp" + "lx-", tail(48)), ("xkey" + "sib-", tail(64, hexa)),
                 ("sntry" + "s_", tail(60)), ("hv" + "s.", tail(40)), ("da" + "pi", tail(32, hexa)),
                 ("tv" + "ly-", tail(32)), ("pc" + "sk_", tail(40)), ("vc" + "p_", tail(30)),
                 ("sk_" + "prod_", tail(30)), ("api" + "_org_", tail(34)), ("key" + "-", tail(32, hexa)),
                 ("SK", tail(32, hexa)), ("fc" + "-", tail(32, hexa))]
        self.assert_found([(f'value = "{prefix}{body}"', body) for prefix, body in cases])

    def test_a_token_with_no_fixed_prefix_shows_none_of_itself(self):
        hexa = "0123456789abcdef"
        azure = tail(3) + "8" + "Q" + "~" + tail(34)
        twilio = "SK" + tail(32, hexa)
        discord = "M" + tail(23) + "." + tail(6) + "." + tail(27)
        telegram = "1234567890" + ":" + "AA" + tail(33)
        replicate = "r8" + "_" + "Q" + tail(24)
        for value, rule, shown in ((azure, "azure-secret", "***"), (twilio, "twilio-key", "SK***"),
                                   (discord, "discord-token", "***"), (telegram, "telegram-token", "***"),
                                   (replicate, "replicate-token", "r8_***")):
            with self.subTest(rule):
                p = self.findings(f"value = {value}")
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn(f"{rule} {shown}\n", p.stdout)
                self.assertNotIn(value[:4] + "***", p.stdout)

    def test_a_webhook_url_or_a_curl_user(self):
        body = tail(24)
        self.assert_found([(f"post https://discord.com/api/webhooks/{'1' * 18}/{body}", body),
                           (f"https://hooks.slack.com/services/{body}{body}", body),
                           (f"curl -u elastic:{body} https://localhost:9200", body)])
        self.assert_clean(["curl -u $USER:$PASS https://localhost:9200", "curl --user admin https://x.test"])

    def test_a_bare_value_under_a_strong_name_in_code_or_yaml(self):
        short = tail(15)
        dotted = "dp." + "xy." + tail(30)
        self.assert_found([(f"dropboxToken = {short}", short), (f"dropbox_token: {short}", short),
                           (f"some_token: {dotted}", dotted)])
        self.assert_clean(["token = request.token2", "api_token: config.tokens.apiToken1", "token: oauth2ClientToken"])

    def test_a_long_numeric_token_under_a_strong_name(self):
        digits = "1" + "918588660504966"
        self.assert_found([(f'asanaToken = "{digits}"', digits), (f"DISCORD_TOKEN={digits}", digits)])
        self.assert_clean(['tokens: "12345678"', 'token = "1111111111111111"'])

    def test_names_that_hold_a_secret_word_without_being_one(self):
        self.assert_clean(["credentialsId: 'ff083f76-7804-4ef1-80e4-fe975bb9141b'",
                           '"credentialId": "B9mTcFSck2LzJO2S3ols63"',
                           "(id)hf_" + "requiredCharacteristicTypesForDisplayMetadata;",
                           'const privateToken = "' + "a" * 32 + '";'])

    def test_a_merge_of_what_is_already_pushed_reports_nothing(self):
        line, _ = planted()["stripe-key"]
        self.commit("a.txt", "base\n")
        self.add_pushed_upstream()
        self.git("checkout", "-q", "-b", "task")
        self.commit("t.txt", "task\n")
        self.git("checkout", "-q", "main")
        self.commit("b.txt", line + "\n")
        self.commit(".env", "A=1\n")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "task")
        self.git("merge", "-q", "--no-ff", "-m", "merge", "main")
        p = self.scan("task")
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_a_merge_still_shows_what_neither_parent_held(self):
        line, _ = planted()["stripe-key"]
        other, _ = planted()["github-token"]
        self.commit("a.txt", "base\n")
        self.add_pushed_upstream()
        self.git("checkout", "-q", "-b", "task")
        self.commit("t.txt", "task\n")
        self.git("checkout", "-q", "main")
        self.commit("b.txt", line + "\n")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "task")
        self.git("merge", "-q", "--no-ff", "--no-commit", "main")
        with open(os.path.join(self.work, "b.txt"), "a") as f:
            f.write(other + "\n")
        self.git("add", "b.txt")
        self.git("commit", "-q", "-m", "merge")
        p = self.scan("task")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("b.txt:2 github-token", p.stdout)
        self.assertNotIn("stripe-key", p.stdout)

    def test_all_says_it_covers_this_clones_refs(self):
        self.commit("a.txt", "base\n")
        p = self.scan("--all")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("every commit on this clone's refs", p.stdout)

    def test_the_fetch_the_skills_name_reaches_what_only_the_remote_holds(self):
        line, _ = planted()["github-token"]
        self.commit("a.txt", "base\n")
        self.add_pushed_upstream()
        other = os.path.join(self.root, "other")
        self.git("clone", "-q", os.path.join(self.root, "remote.git"), other)
        self.git("checkout", "-q", "-b", "teammate", cwd=other)
        with open(os.path.join(other, "b.txt"), "w") as f:
            f.write(line + "\n")
        self.git("add", "b.txt", cwd=other)
        self.git("commit", "-q", "-m", "c", cwd=other)
        self.git("push", "-q", "origin", "teammate", cwd=other)
        self.assertEqual(self.scan("--all").returncode, 0, "not fetched yet")
        fetch = re.search(r"`git (fetch origin '[^`]+')`", read_skill("public-ready")).group(1).split()
        self.git(*[word.strip("'") for word in fetch])
        p = self.scan("--all")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("b.txt:1 github-token", p.stdout)
        for name in ("hackathon", "public-ready"):
            self.assertIn(" ".join(fetch), read_skill(name), name)

    def test_the_public_ready_fallback_catches_names_in_any_case(self):
        skill = read_skill("public-ready")
        command = re.search(r"(?m)^\s*(git log --all --name-only --format=%h .*)$", skill).group(1)
        for line in ("API_KEY=abc", "DB_PASSWORD=x", '"pass' + 'word": "y"', "client_secret: z"):
            with self.subTest(line):
                self.commit("cfg.txt", line + "\n", line)
                hits = subprocess.run(shlex.split(command), cwd=self.work, env=self.env,
                                      capture_output=True, text=True)
                self.assertEqual(hits.returncode, 0, hits.stderr)
                self.assertIn(self.git("rev-parse", "--short", "HEAD"), hits.stdout)
                self.git("rm", "-q", "cfg.txt")
                self.git("commit", "-q", "-m", "gone")

    def test_all_refuses_a_ref_it_cannot_read(self):
        line, secret = planted()["github-token"]
        self.commit("a.txt", "base\n")
        path = os.path.join(self.root, "loose")
        with open(path, "w") as f:
            f.write(line + "\n")
        blob = self.git("hash-object", "-w", path)
        self.git("tag", "blobtag", blob)
        p = self.scan("--all")
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIn("refs/tags/blobtag", p.stderr)
        self.assertNotIn(secret, p.stderr + p.stdout)
        self.git("tag", "-d", "blobtag")
        self.git("tag", "-a", "-m", "ok", "v1")
        self.assertEqual(self.scan("--all").returncode, 0)


class TheKickoffFiles(unittest.TestCase):
    """What another machine, or a session after /clear, reads. Other skills read these names."""

    @staticmethod
    def read(*rest):
        with open(os.path.join(SKILL, *rest), encoding="utf-8") as f:
            return f.read()

    def test_the_event_profile_has_the_live_and_venue_fields_and_who_to_ask(self):
        for text in (self.read("templates", "EVENT.md"), self.read("SKILL.md")):
            self.assertIn("What must run live", text)
            self.assertIn("Venue screen size and network", text)
        self.assertIn("Who to ask when a field is unknown", self.read("templates", "EVENT.md"))

    def test_demo_md_names_each_skill_and_when_it_is_due(self):
        text = self.read("templates", "DEMO.md")
        self.assertIn("## Due", text)
        self.assertIn("not this event", text)
        for row in ("`/interview`", "`/demo-first-scope`", "`/demo-video`", "`/pitch`",
                    "`/public-ready` before submitting", "`/public-ready` after judging"):
            with self.subTest(row):
                self.assertRegex(text, rf"(?m)^\| {re.escape(row)} \|")

    def test_the_project_file_survives_a_clear(self):
        text = self.read("templates", "project-CLAUDE.md")
        self.assertIn("`VISION.md`", text)
        self.assertIn("/interview", text)
        self.assertIn("goes away when the mode ends", text.splitlines()[0])

    def test_pitch_is_skipped_only_with_no_talk_no_table_and_no_slides(self):
        self.assertRegex(self.read("SKILL.md"), r"\| `/pitch` \| `EVENT.md` has no talk, no table and no slides \|")

    def test_the_commit_question_covers_every_private_file(self):
        step = re.search(r"(?m)^6\. .*$", self.read("SKILL.md")).group(0)
        for name in ("EVENT.md", "DEMO.md", "ACCESS.md", "VISION.md", "PITCH.md", "git add -A"):
            with self.subTest(name):
                self.assertIn(name, step)

    def test_a_plugin_turned_off_is_logged_to_be_undone(self):
        step = re.search(r"(?m)^5\. .*$", self.read("SKILL.md")).group(0)
        self.assertIn("ACCESS.md", step)
        self.assertIn("enabledPlugins", self.read("templates", "ACCESS.md"))

    def test_the_terms_mean_something_on_another_machine(self):
        for text in (self.read("SKILL.md"), self.read("templates", "project-CLAUDE.md")):
            self.assertIn("390 and at least 1024 wide", text)
            self.assertIn("pre-merge trial runs", text)
            self.assertIn("long planning and status documents", text)
            self.assertNotIn("lane trials", text)
            self.assertNotIn("SPEC, PLAN, STATUS", text)

    def test_the_clock_examples_match_their_percentages(self):
        text = self.read("SKILL.md")
        self.assertIn("plan ends Sat 17:00, demo path Sat 21:00, freeze Sun 07:30", text)
        self.assertIn("plan ends Sat 12:00, demo path Sat 14:30, freeze Sun 09:15", text)

    def test_the_gitignore_matches_what_the_scan_flags(self):
        scanner = self.read("scripts", "secret-scan")
        words = re.search(r'SAFE_WORDS = r"([a-z|?]+)"', scanner).group(1)
        safe = words.replace("defaults?", "default|defaults").split("|")
        safe_names = [form.format(w) for w in safe
                      for form in SAFE_FORMS]
        with tempfile.TemporaryDirectory() as tmp:
            # Only the template applies: no global excludes, no outer repo.
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            env.update(HOME=tmp, XDG_CONFIG_HOME=tmp, GIT_CONFIG_NOSYSTEM="1")
            repo = os.path.join(tmp, "repo")
            subprocess.run(["git", "init", "-q", repo], check=True, env=env)
            with open(os.path.join(repo, ".gitignore"), "w") as f:
                f.write(self.read("templates", "gitignore"))

            def ignored(name):
                return subprocess.run(["git", "-C", repo, "check-ignore", "-q", "--", name], env=env).returncode == 0
            for name in FLAGGED_AND_IGNORED + CLEAN_AND_IGNORED:
                with self.subTest(name):
                    self.assertTrue(ignored(name), name)
            for name in FLAGGED_NOT_IGNORED + CLEAN_AND_KEPT + tuple(safe_names):
                with self.subTest(name):
                    self.assertFalse(ignored(name), name)

    def test_the_gitignore_says_how_to_keep_a_keynote_deck(self):
        self.assertIn("!pitch.key", self.read("templates", "gitignore"))

    def test_the_gitignore_says_how_to_keep_other_lookalike_files(self):
        text = self.read("templates", "gitignore")
        for line in ("!environment.env", "`--allow-name environment.env`", "!debug.keystore",
                     "`--allow-name debug.keystore`"):
            with self.subTest(line):
                self.assertIn(line, text)

    def test_the_skill_describes_the_scan_as_it_now_works(self):
        text = self.read("SKILL.md")
        self.assertIn("secret-scan [--remote R] [REF ...]", text)
        self.assertNotIn("@{push}", text)
        for word in ("--allow-name", "--tags", "--all", "untracked `.env`",
                     "exit 0 doesn't prove"):
            with self.subTest(word):
                self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
