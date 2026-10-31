"""hooks/sandbox-caches.sh: a SessionStart hook that points sandboxed Bash's package managers at
caches of their own, so the sandbox can keep the caches unsandboxed code runs from read-only
(stdlib only). Sandbox gap N1: plugin MCP servers run unsandboxed from ~/.npm/_npx, and npx
reuses a tree there without rechecking it. N3: bun's global installs (the status line's
ccstatusline) are hardlinks into ~/.bun/install/cache, and the same holds for uv, pip, pnpm and
node-gyp, whose caches unsandboxed installs and runs reuse. Playwright's browsers get no var:
sandboxed Playwright launches them read-only from their default dir.

Each test runs the hook with bash the way Claude Code does, then sources the env file the way
Claude Code inlines it into each Bash command: inside the sandbox, where the sandbox runtime sets
SANDBOX_RUNTIME=1, and outside it. The env starts clean of every CLAUDE*, SANDBOX_RUNTIME and cache
var below, and HOME and XDG_STATE_HOME point into a temp dir."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "sandbox-caches.sh")
PAYLOAD = ('{"hook_event_name": "SessionStart", "source": "startup", '
           '"session_id": "abcdef12-0000", "cwd": "/"}')
# Each var and the dir under ~/.cache/claude-sandbox it points sandboxed Bash at.
CACHES = (
    ("npm_config_cache", "npm"),
    ("BUN_INSTALL_CACHE_DIR", "bun"),
    ("UV_CACHE_DIR", "uv"),
    ("PIP_CACHE_DIR", "pip"),
    ("PNPM_HOME", "pnpm"),
    ("npm_config_devdir", "node-gyp"),
)
# Plus one value: sandboxed uv runs Hayden's Pythons read-only and never downloads one. And one
# var left unset: sandboxed Playwright launches Hayden's browsers read-only from its default dir.
VARS = tuple(v for v, _ in CACHES) + ("UV_PYTHON_DOWNLOADS", "PLAYWRIGHT_BROWSERS_PATH")
SHOW = 'source "$1"; printf "%s\\n"' + "".join(f' "${{{v}-unset}}"' for v in VARS)
UNSET = ["unset"] * len(VARS)


class SandboxCaches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home dir")  # a space, to prove the quoting
        os.makedirs(self.home)
        self.root = os.path.join(self.home, ".cache", "claude-sandbox")
        self.dirs = [os.path.join(self.root, d) for _, d in CACHES]
        self.want = self.dirs + ["never", "unset"]
        self.envfile = os.path.join(self.tmp, "session-env.sh")
        self.logfile = os.path.join(self.tmp, "state", "dotclaude", "sandbox-caches.log")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "SANDBOX_RUNTIME", "BUN_", "UV_", "PIP_",
                                         "PNPM_", "PLAYWRIGHT_"))
                    and not k.lower().startswith("npm_config_")}
        self.env.update(HOME=self.home, XDG_STATE_HOME=os.path.join(self.tmp, "state"))

    def run_hook(self, env_file=None):
        env = dict(self.env)
        if env_file is not False:
            env["CLAUDE_ENV_FILE"] = env_file or self.envfile
        p = subprocess.run(["bash", HOOK], input=PAYLOAD, capture_output=True, text=True,
                           timeout=10, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        self.assertEqual(p.stdout, "")  # silent: nothing for the model to act on

    def sourced(self, shell="bash", sandboxed=True):
        """The cache vars, in VARS order, as a Bash command sees them once the env file is
        sourced."""
        env = dict(self.env, SANDBOX_RUNTIME="1") if sandboxed else self.env
        p = subprocess.run([shell, "-c", SHOW, "_", self.envfile], capture_output=True,
                           text=True, env=env, check=True)
        return p.stdout.splitlines()

    def logged(self):
        try:
            with open(self.logfile) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def test_a_sandboxed_command_gets_the_caches_and_the_dirs_exist(self):
        # The sandbox skips a missing allowWrite path and ~/.cache is read-only, so sandboxed
        # tools can't create the dirs themselves: the hook (unsandboxed) must.
        self.run_hook()
        self.assertEqual(self.sourced(), self.want)
        for d in (self.root, *self.dirs):
            self.assertTrue(os.path.isdir(d), d)
        self.assertEqual(stat.S_IMODE(os.stat(self.root).st_mode), 0o700)
        self.assertEqual(self.logged(), "")

    def test_an_unsandboxed_command_keeps_the_defaults(self):
        # A sandbox-off command or an excluded `claude -p` must not carry the vars: the child
        # claude's MCP servers would then npx from a dir sandboxed Bash can write.
        self.run_hook()
        self.assertEqual(self.sourced(sandboxed=False), UNSET)

    @unittest.skipUnless(shutil.which("zsh"), "zsh not installed")
    def test_zsh_reads_the_same_line(self):
        # Claude Code runs Bash commands in the user's shell, zsh on HAYPC.
        self.run_hook()
        self.assertEqual(self.sourced("zsh"), self.want)
        self.assertEqual(self.sourced("zsh", sandboxed=False), UNSET)

    def test_ends_another_hooks_unterminated_line_first(self):
        with open(self.envfile, "w") as f:
            f.write("export OTHER=1")
        self.run_hook()
        with open(self.envfile) as f:
            text = f.read()
        self.assertTrue(text.startswith("export OTHER=1\n"), text)
        self.assertEqual(self.sourced(), self.want)

    def test_a_rerun_on_compact_keeps_one_value(self):
        self.run_hook()
        self.run_hook()
        self.assertEqual(self.sourced(), self.want)

    def test_an_existing_dir_keeps_its_contents(self):
        os.makedirs(self.want[0])
        keep = os.path.join(self.want[0], "keep")
        open(keep, "w").close()
        self.run_hook()
        self.assertTrue(os.path.exists(keep))

    def test_no_env_file_is_silent_and_logged(self):
        # Fails open: sandboxed tools then fall back to their default caches, which they can't
        # write, so the sandbox still holds; the tool reports the write error.
        self.run_hook(env_file=False)
        self.assertFalse(os.path.exists(self.envfile))
        self.assertIn("CLAUDE_ENV_FILE is unset", self.logged())

    def test_an_unwritable_env_file_is_silent_and_logged(self):
        os.mkdir(self.envfile)
        self.run_hook()
        self.assertIn("can't write", self.logged())

    def test_an_unreadable_env_file_still_gets_one_clean_line(self):
        # The newline guard's tail fails here; its error must reach neither the file nor stderr.
        with open(self.envfile, "w") as f:
            f.write("export OTHER=1\n")
        os.chmod(self.envfile, 0o200)
        self.run_hook()
        os.chmod(self.envfile, 0o600)
        with open(self.envfile) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[1].startswith("if [ -n "), lines)
        self.assertEqual(self.sourced(), self.want)

    def test_an_unwritable_log_dir_stays_silent(self):
        # The log line's own redirect errors must not reach stderr (run_hook checks it is empty).
        os.makedirs(os.path.join(self.tmp, "state"))
        open(os.path.join(self.tmp, "state", "dotclaude"), "w").close()  # a file, not a dir
        self.run_hook(env_file=False)

    def test_a_cache_path_that_is_a_file_writes_nothing_and_logs(self):
        os.makedirs(self.root)
        open(self.want[1], "w").close()
        self.run_hook()
        self.assertFalse(os.path.exists(self.envfile))
        self.assertIn("can't create", self.logged())


if __name__ == "__main__":
    unittest.main()
